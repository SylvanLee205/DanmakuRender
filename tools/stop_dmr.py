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
    .venv\\Scripts\\python.exe tools\\stop_dmr.py             # 真停（不重启）

2026-10-30 改动：进程发现从"调 powershell.exe"改为 **psutil**。
原来用 `subprocess.run(['powershell', ...])` 列进程，而某些环境（无人值守 /
沙箱 / PATH 被裁剪）里 powershell 根本不在 PATH 上 —— 实测报
`FileNotFoundError: [WinError 2]`，脚本在"停止前"就崩，一个进程都停不掉。
psutil 本来就是 requirements.txt 里的依赖，不依赖任何外部可执行文件。
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

    print('  [2/3] 停止 DMR 主进程（从子到父）')
    kill(list(reversed(pids_dmr())), 'DMR')
    time.sleep(3)

    print('  [3/3] 停止录制子进程')
    kill(pids_sg(), 'streamgears')
    kill(pids_ff(), 'ffmpeg')
    time.sleep(2)

    print()
    show_state('停止后')

    left = pids_cmd() + pids_dmr() + pids_sg() + pids_ff()
    if left:
        print('\n  ❌ 仍有进程未退出，请再跑一次本脚本，或检查是否有权限问题。')
        return 1
    print('\n  ✅ 已全部停止。要重新启动请双击 Start_DMR.bat。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
