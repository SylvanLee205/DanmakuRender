"""干净地停止 DMR（含守护进程与所有录制子进程）。

为什么需要单独一个"停止"脚本
--------------------------
`Start_Render.bat` 是**守护循环**：程序退出后 10 秒会自己再拉起来。
所以"停"不能只关掉窗口或按 Ctrl+C —— 那只会让守护脚本把程序重新拉起。

正确顺序（少一步就会留孤儿）：
    1. 先停守护 cmd      —— 否则它会立刻重新拉起 DMR
    2. 再停 DMR python   —— 从子到父（venv 启动器 → 真正的 C:\\Python311 进程）
    3. 最后停录制子进程  —— streamgears_wrapper 与录制用 ffmpeg（判据 -segment_time）
       这两类是 DMR 的子进程，只杀 python 会让它们继续写文件，产生
       重复录制和孤儿 `[正在录制]` 分段（2026-10-07 踩过）。

用法：
    .venv\\Scripts\\python.exe tools\\stop_dmr.py --dry-run   # 只看会停什么
    .venv\\Scripts\\python.exe tools\\stop_dmr.py             # 优雅停止（默认）
    .venv\\Scripts\\python.exe tools\\stop_dmr.py --force     # 跳过优雅，直接硬杀
    .venv\\Scripts\\python.exe tools\\stop_dmr.py --timeout 60  # 优雅等待秒数

2026-10-30 改动：进程发现从"调 powershell.exe"改为 **psutil**。
原来用 `subprocess.run(['powershell', ...])` 列进程，而某些环境（无人值守 /
沙箱 / PATH 被裁剪）里 powershell 根本不在 PATH 上 —— 实测报
`FileNotFoundError: [WinError 2]`，脚本在"停止前"就崩，一个进程都停不掉。
psutil 本来就是 requirements.txt 里的依赖，不依赖任何外部可执行文件。

2026-11-02 改动：默认改为**优雅停止**。
原来直接 psutil.kill() 是硬杀，ffmpeg 来不及收尾：正在录的分段停留在
`[正在录制]` 状态、rename 不执行，正在渲染的任务也半途而废。
现在先创建 `.temp/graceful_stop_<PID>`，DMR 主循环（main.py）轮询到这个
标志后走 `dmr.stop()`：
    ffmpeg 收到 'q'（ffmpeg.py 的 communicate('q')）→ 优雅写完当前段
    → segment_callback() 把它改名成正式名
    → 下次启动 reconciler 发现目录里有源视频，自动补派渲染
标志文件带 PID，绝不会误伤别的实例；DMR 退出时自己删除，这里也有兜底清理。
"""
import os
import sys
import time

try:
    import psutil
except ImportError:  # pragma: no cover
    print('缺少 psutil：请先 .venv\\Scripts\\pip install psutil')
    print('（它在 requirements.txt 里，正常环境不该出现这条）')
    sys.exit(2)

UP = r'F:\DanmakuRender_AutoUp'
DRY_RUN = '--dry-run' in sys.argv
FORCE = '--force' in sys.argv
GRACEFUL_TIMEOUT = 180          # 等 DMR 自己收尾的最长秒数


def _opt_int(name, default):
    """解析 --name N。"""
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            try:
                return int(sys.argv[i + 1])
            except ValueError:
                pass
    return default


GRACEFUL_TIMEOUT = _opt_int('--timeout', GRACEFUL_TIMEOUT)

# stdout/stderr 可能是管道（被别的程序捕获）或 GBK 控制台：
# 下面的 ⚠️/❌/✅ 不在 GBK 字符集里，print 会直接 UnicodeEncodeError 崩掉。
# 2026-10-20 实测：迁移时 stop_dmr 在"停止前"之后神秘消失、进程一个没停，
# 就是这句炸的 —— 无人值守场景必须容忍编码问题。
try:
    sys.stdout.reconfigure(errors='replace')
    sys.stderr.reconfigure(errors='replace')
except Exception:
    pass


def _iter_procs():
    """遍历进程，容忍进程在遍历途中退出。"""
    try:
        return list(psutil.process_iter(['pid', 'name', 'cmdline']))
    except Exception:
        return []


def _cmdline_has(cmdline, needle):
    return any(needle in (a or '') for a in (cmdline or []))


def pids_cmd():
    """守护循环的 cmd（命令行里含 Start_Render）。"""
    return [p.info['pid'] for p in _iter_procs()
            if (p.info['name'] or '').lower() == 'cmd.exe'
            and _cmdline_has(p.info['cmdline'], 'Start_Render')]


def pids_dmr():
    """DMR 主进程（python 跑 main.py）。"""
    return [p.info['pid'] for p in _iter_procs()
            if (p.info['name'] or '').lower() == 'python.exe'
            and _cmdline_has(p.info['cmdline'], 'main.py')]


def pids_sg():
    """streamgears 包装进程。"""
    return [p.info['pid'] for p in _iter_procs()
            if (p.info['name'] or '').lower() == 'python.exe'
            and _cmdline_has(p.info['cmdline'], 'streamgears_wrapper')]


def pids_ff():
    """录制用 ffmpeg（判据 -segment_time，与渲染用的区分开）。"""
    return [p.info['pid'] for p in _iter_procs()
            if (p.info['name'] or '').lower() == 'ffmpeg.exe'
            and _cmdline_has(p.info['cmdline'], '-segment_time')]


# 兼容旧名字（别处/文档里可能还引用着）
CMD_Q, DMR_Q, SG_Q, FF_Q = pids_cmd, pids_dmr, pids_sg, pids_ff


def recording_files():
    base = os.path.join(UP, '直播回放')
    out = []
    for root, dirs, files in os.walk(base):
        for f in files:
            if f.startswith('[正在录制]'):
                p = os.path.join(root, f)
                try:
                    out.append((p, os.path.getsize(p)))
                except OSError:
                    continue
    return out


def show_state(tag):
    print(f'  {tag}: 守护={pids_cmd() or "无"}  DMR={pids_dmr() or "无"}  '
          f'streamgears={pids_sg() or "无"}  ffmpeg={pids_ff() or "无"}')


def _flag_path(pid):
    return os.path.join(UP, '.temp', f'graceful_stop_{pid}')


def _write_flag(pid):
    path = _flag_path(pid)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f'requested by stop_dmr.py (pid {os.getpid()})')
        return True
    except OSError as e:
        print(f'    ❌ 无法创建优雅停止标志 {path}: {e}')
        return False


def _clear_flags():
    """删掉所有优雅停止标志。

    正常路径下 DMR 退出前会自己删；这里兜底清残留。
    残留标志很危险 —— 下次 DMR 一启动就会发现它，立刻退出，
    于是陷入"启动即退出"的崩溃循环。
    """
    d = os.path.join(UP, '.temp')
    removed = 0
    try:
        for n in os.listdir(d):
            if n.startswith('graceful_stop_'):
                try:
                    os.remove(os.path.join(d, n))
                    removed += 1
                except OSError:
                    pass
    except OSError:
        pass
    return removed


def graceful_stop(dmr_pids, timeout):
    """请求优雅停止并等待 DMR 自己退出。

    :return: True=全部自行退出；False=超时，调用方应转硬杀
    """
    print(f'\n  [2/3] 请求优雅停止（最多等 {timeout} 秒）')
    print('       正在录的分段会写完并改名成正式名；')
    print('       正在渲染的会被中断，但源视频还在，下次启动自动补派渲染。')
    for pid in dmr_pids:
        if _write_flag(pid):
            print(f'       已通知 DMR PID {pid}')

    t0 = time.time()
    last = -1
    while time.time() - t0 < timeout:
        if not pids_dmr():
            return True
        el = int(time.time() - t0)
        if el - last >= 15:
            print(f'       等待中 {el}s：DMR 仍在收尾，录制中 ffmpeg {len(pids_ff())} 个')
            last = el
        time.sleep(1)
    return False


def kill(pid_list, label):
    for pid in pid_list:
        try:
            psutil.Process(pid).kill()
        except psutil.NoSuchProcess:
            print(f'    停 {label} {pid}（已自行退出）')
            continue
        except psutil.AccessDenied as e:
            print(f'    ❌ 停 {label} {pid} 失败：权限不足（{e}）')
            continue
        except Exception as e:
            print(f'    ❌ 停 {label} {pid} 失败：{type(e).__name__}: {e}')
            continue
        print(f'    停 {label} {pid}')


def main() -> int:
    print('=' * 78)
    print('停止 DMR' + ('（DRY-RUN，不会动任何进程）' if DRY_RUN else ''))
    print('=' * 78)
    show_state('停止前')

    parts = recording_files()
    if parts:
        print(f'\n  ⚠️ 发现 {len(parts)} 个 [正在录制] 文件：')
        for p, sz in sorted(parts, key=lambda x: -x[1])[:10]:
            print(f'     {sz/1024/1024:>8.1f} MB  {os.path.basename(p)[:70]}')
        print('     这些是正在写入/刚中断的分段；停止后它们会被保留，')
        print('     下次启动时 recover 流程会按规则接管（不是丢失）。')

    if DRY_RUN:
        print('\n  DRY-RUN 结束：以上就是要停的进程。')
        return 0

    print('\n  [1/3] 停止守护（防止它重新拉起 DMR）')
    kill(pids_cmd(), '守护')
    time.sleep(2)

    dmr = pids_dmr()
    if not dmr:
        print('\n  [2/3] 没有 DMR 主进程需要停止')
    elif FORCE:
        print(f'\n  [2/3] 强制停止 DMR 主进程（--force，跳过优雅收尾）')
        kill(list(reversed(dmr)), 'DMR')
        time.sleep(3)
    else:
        if not graceful_stop(dmr, GRACEFUL_TIMEOUT):
            print(f'\n  ⚠️ 等了 {GRACEFUL_TIMEOUT} 秒 DMR 仍未退出，转为硬杀。')
            kill(list(reversed(pids_dmr())), 'DMR')
            time.sleep(3)

    print('\n  [3/3] 停止录制子进程')
    kill(pids_sg(), 'streamgears')
    kill(pids_ff(), 'ffmpeg')
    time.sleep(2)

    n = _clear_flags()
    if n:
        print(f'     已清理 {n} 个残留的优雅停止标志')

    print()
    show_state('停止后')

    left = pids_cmd() + pids_dmr() + pids_sg() + pids_ff()
    if left:
        print('\n  ❌ 仍有进程未退出，请再跑一次本脚本，或检查是否有权限问题。')
        return 1

    # 优雅停止是否奏效，最直接的证据就是有没有 [正在录制] 残留
    leftover = recording_files()
    if leftover:
        print(f'\n  ⚠️ 仍有 {len(leftover)} 个 [正在录制] 文件没能改名：')
        for p, sz in sorted(leftover, key=lambda x: -x[1])[:10]:
            print(f'     {sz/1024/1024:>8.1f} MB  {os.path.basename(p)[:70]}')
        print('     这些分段内容通常完整，只是没走到 rename；下次启动 reconciler')
        print('     可能不会自动接管它们，需要时可用 tools/rename_orphans.py 处理。')
    else:
        print('\n  ✅ 已全部停止，且没有 [正在录制] 残留（优雅收尾成功）。')
    print('     要重新启动请双击 Start_DMR.bat。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
