"""一键体检。出任何问题先跑这个 —— 它把"哪里坏了、怎么修"直接说清楚。

设计目标：**用户不需要懂代码**。
    每条检查都给出「现状 + 处理办法」，能用一句话说清就不写两行。

用法：
    python tools\\doctor.py            # 全文
    python tools\\doctor.py --brief    # 只显示有问题的项
    python tools\\doctor.py --export   # 另外打包一份诊断包到 .temp\\ 便于发给 AI

退出码：0 = 全部通过（可能有警告）；1 = 有严重问题。
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

IS_WIN = sys.platform == 'win32'

OK, WARN, BAD = 'OK', 'WARN', 'BAD'
ICON = {OK: '✅', WARN: '⚠️ ', BAD: '❌'}

results = []


def add(level, title, detail='', hint=''):
    results.append(dict(level=level, title=title, detail=detail, hint=hint))


def hr(title=''):
    print()
    print('─' * 74)
    if title:
        print(f'  {title}')
        print('─' * 74)


# ───────────────────────────── 各检查项 ─────────────────────────────

def chk_python():
    v = sys.version_info
    ver = f'{v.major}.{v.minor}.{v.micro}'
    in_venv = (hasattr(sys, 'real_prefix')
               or sys.prefix != getattr(sys, 'base_prefix', sys.prefix))
    loc = '项目 .venv' if os.path.abspath(sys.executable).lower().startswith(
        os.path.abspath(os.path.join(PROJ, '.venv')).lower()) else sys.executable

    if (v.major, v.minor) < (3, 9):
        add(BAD, 'Python 版本过低', f'{ver}（{loc}）',
            '装 3.11 或更高：https://www.python.org/downloads/  勾选 Add to PATH')
    elif not in_venv:
        add(WARN, 'Python 可用，但不在项目虚拟环境里', f'{ver}（{loc}）',
            '双击 Setup.bat 会建 .venv。用系统 Python 也能跑，只是依赖可能互相干扰')
    else:
        add(OK, 'Python', f'{ver}（{loc}）')


def chk_deps():
    mods = ['requests', 'aiohttp', 'jsengine', 'lxml', 'yaml', 'stream_gears',
            'websocket', 'brotli', 'yutto', 'easydict', 'streamlink', 'm3u8',
            'gmssl', 'rsa', 'PIL', 'fontTools', 'flask', 'psutil']
    bad = []
    for m in mods:
        try:
            __import__(m)
        except Exception:
            bad.append(m)
    if bad:
        add(BAD, 'Python 依赖缺失', ', '.join(bad),
            '双击 Setup.bat，或执行：.venv\\Scripts\\python.exe -m pip install -r requirements.txt')
    else:
        add(OK, 'Python 依赖', f'{len(mods)} 个模块全部可导入')


def chk_tools():
    try:
        from DMR.utils import toolsmgr
    except Exception as e:
        add(BAD, '工具模块无法导入', repr(e), '代码可能不完整，重新下载项目')
        return {}
    found = {}
    for name, required in (('ffmpeg', True), ('ffprobe', True),
                           ('rclone', True), ('biliup', False)):
        p = toolsmgr.find_tool(name)
        found[name] = p
        if p:
            add(OK, f'{name}', p)
        elif required and name == 'rclone':
            add(WARN, f'{name} 未找到', '',
                '网盘上传会跳过，录制不受影响。装好后重跑本检查（或放 tools\\rclone.exe）')
        elif required:
            add(BAD, f'{name} 未找到', '',
                '没有它无法录制。双击 Setup.bat 自动下载，或装到 PATH')
        else:
            add(WARN, f'{name}（可选）未找到', '',
                '只有 B 站上传才需要。用 rclone 传网盘的话可以忽略')
    return found


def chk_dirs():
    need = ['configs', 'logs', '.temp']
    miss = [d for d in need if not os.path.isdir(os.path.join(PROJ, d))]
    if miss:
        add(WARN, '目录缺失', ', '.join(miss), '双击 Setup.bat 会自动创建')
    else:
        add(OK, '目录结构', 'configs / logs / .temp 都在')


def chk_configs():
    cfg = os.path.join(PROJ, 'configs')
    if not os.path.isdir(cfg):
        add(BAD, 'configs 目录不存在', '', '双击 Setup.bat')
        return
    tasks = [f for f in os.listdir(cfg)
             if f.startswith('DMR-') and f.endswith('.yml')]
    g = os.path.join(cfg, 'global.yml')
    if not os.path.exists(g):
        add(BAD, 'configs/global.yml 不存在', '', '双击 Setup.bat 会从默认配置生成')
    else:
        try:
            import yaml
            with open(g, encoding='utf-8') as f:
                d = yaml.safe_load(f) or {}
            need = ['download_args', 'render_args', 'upload_args']
            miss = [k for k in need if k not in d]
            if miss:
                add(WARN, 'global.yml 缺少关键段', ', '.join(miss),
                    '恢复：python tools\\backup_configs.py restore <快照名>')
            else:
                add(OK, 'global.yml', f'{len(d)} 个顶级配置段，关键段齐全')
        except Exception as e:
            add(BAD, 'global.yml 解析失败', repr(e),
                'YAML 语法错误。用 python tools\\backup_configs.py restore 恢复最近的快照')

    if not tasks:
        add(WARN, '一个主播任务都没有', 'configs/ 下没有 DMR-*.yml',
            '双击 Add_Room.bat 粘贴直播间链接即可新增')
    else:
        add(OK, '主播任务', f'{len(tasks)} 个')


def chk_state():
    db = os.path.join(PROJ, 'logs', 'dmr_state.db')
    if not os.path.exists(db):
        add(WARN, '状态库不存在', db, '首次启动 DMR 会自动创建')
        return
    try:
        import sqlite3
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=5)
        cur = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        n_sess = n_art = 0
        if 'sessions' in tables:
            n_sess = con.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
        if 'artifacts' in tables:
            n_art = con.execute('SELECT COUNT(*) FROM artifacts').fetchone()[0]
        con.close()
        size = os.path.getsize(db) / 1024 / 1024
        add(OK, '状态库', f'{size:.1f} MB，{n_sess} 个场次 / {n_art} 个产物')
    except Exception as e:
        add(BAD, '状态库读取失败', repr(e),
            '可能被占用或损坏。先停 DMR，再备份后删除 logs\\dmr_state.db 重建')


def chk_disk():
    try:
        from DMR.paths import data_root
        root = data_root()
    except Exception:
        root = PROJ
    try:
        du = shutil.disk_usage(root)
    except OSError as e:
        add(BAD, '磁盘不可读', f'{root}: {e}', '录制盘可能掉线了')
        return
    free_gb = du.free / 1024 ** 3
    total_gb = du.total / 1024 ** 3
    drive = os.path.splitdrive(root)[0]
    if free_gb < 20:
        add(BAD, '磁盘空间不足', f'{drive} 剩 {free_gb:.1f} GB / 共 {total_gb:.0f} GB',
            '录制会失败。清理旧视频或换盘（设环境变量 DMR_DATA_ROOT 指向新盘）')
    elif free_gb < 80:
        add(WARN, '磁盘空间偏低', f'{drive} 剩 {free_gb:.1f} GB / 共 {total_gb:.0f} GB',
            '注意清理')
    else:
        add(OK, '磁盘空间', f'{drive} 剩 {free_gb:.1f} GB / 共 {total_gb:.0f} GB')


def chk_process():
    try:
        import psutil
    except Exception:
        add(WARN, 'psutil 未安装', '', '无法检查进程状态。pip install psutil')
        return
    procs = []
    for p in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmd = ' '.join(p.info.get('cmdline') or [])
        except Exception:
            continue
        if 'main.py' in cmd and PROJ.lower() in cmd.lower().replace('/', '\\'):
            procs.append(p.info['pid'])
    if procs:
        add(OK, 'DMR 进程', f'正在运行 (PID {", ".join(map(str, procs))})')
    else:
        add(WARN, 'DMR 没有在运行', '',
            '双击 Start_DMR.bat 启动；如果刚重启过，双击 Check_After_Reboot.bat')


def chk_tasks():
    if not IS_WIN:
        return
    names = ['DMR_Boot', 'DMR_SessionWatch', 'DMR_Desktop']
    from DMR.paths import system32
    schtasks = system32('schtasks.exe')
    denied = False
    for n in names:
        try:
            r = subprocess.run([schtasks, '/query', '/tn', n, '/fo', 'LIST'],
                               capture_output=True, text=True,
                               encoding='gbk', errors='replace',
                               stdin=subprocess.DEVNULL, timeout=15)
        except Exception as e:
            msg = str(e)
            if ('WinError 5' in msg or 'denied' in msg.lower()
                    or '拒绝访问' in msg or '权限' in msg):
                denied = True
                continue
            add(WARN, f'计划任务 {n}', f'查询失败: {e}', '')
        if r.returncode != 0:
            err = ((r.stderr or '') + (r.stdout or '')).lower()
            if 'denied' in err or '拒绝访问' in err or '权限' in err:
                denied = True
                continue
            if n == 'DMR_Boot':
                add(WARN, '开机任务 DMR_Boot 未注册', '',
                    '双击 Install_Boot_Task.bat（或运行 tools\\install_boot_task.py）')
            continue
        state = ''
        for line in (r.stdout or '').splitlines():
            if '状态' in line or 'Status' in line:
                state = line.split(':', 1)[-1].strip()
                break
        add(OK, f'计划任务 {n}', state or '已注册')

    if denied:
        add(WARN, '计划任务状态查不到（权限不足）', '',
            '用管理员身份运行 Doctor.bat 才能查。不影响使用，只是少一项自检')


def chk_notify():
    """检查通知服务能不能连上（真的发一条太吵，只测 TCP 443）。"""
    import socket
    host = '17530.push.ft07.com'
    try:
        with socket.create_connection((host, 443), timeout=8):
            add(OK, '通知服务连通', f'{host}:443 可达')
    except Exception as e:
        add(WARN, '通知服务连不上', f'{host}:443 — {e}',
            '开播通知会发不出去。检查网络 / 代理 / hosts')


def chk_logs():
    logdir = os.path.join(PROJ, 'logs')
    if not os.path.isdir(logdir):
        return
    logs = [os.path.join(logdir, f) for f in os.listdir(logdir)
            if f.startswith('DMR-') and f.endswith('.log')]
    if not logs:
        add(WARN, '还没有运行日志', '', '正常启动一次后就会有')
        return
    latest = max(logs, key=os.path.getmtime)
    age_min = (time.time() - os.path.getmtime(latest)) / 60
    size_mb = os.path.getsize(latest) / 1024 / 1024

    n_err = 0
    try:
        with open(latest, encoding='utf-8', errors='replace') as f:
            tail = f.readlines()[-4000:]
        n_err = sum(1 for ln in tail if '][ERROR]' in ln or '][error]' in ln)
    except OSError:
        pass

    title = f'最近日志 {os.path.basename(latest)}'
    detail = f'{size_mb:.1f} MB，{age_min:.0f} 分钟前更新，尾部 {n_err} 条 ERROR'
    if n_err > 20:
        add(WARN, title, detail, '错误偏多，看 Watch_DMR_Log.bat 或把日志发给 AI 分析')
    else:
        add(OK, title, detail)


def chk_startup_error():
    f = os.path.join(PROJ, 'logs', 'startup_error.log')
    if not os.path.exists(f):
        return
    try:
        with open(f, encoding='utf-8', errors='replace') as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    except OSError:
        return
    if not lines:
        return
    # 只关心**最近 24 小时**的。这个文件是追加写的，几周前的旧错误
    # 留在里面会让人误以为"现在还是坏的"。
    cutoff = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() - 86400))
    recent = [ln for ln in lines if ln[:19] >= cutoff]
    if recent:
        add(WARN, '最近 24 小时有启动期错误', recent[-1][:120],
            '该文件记录"程序没起来"的原因。上面的时间戳能看出是哪次启动')
    else:
        add(OK, '启动期错误日志', f'共 {len(lines)} 条历史记录，最近 24 小时无新增')


# ───────────────────────────── 汇总 ─────────────────────────────
def render(brief=False):
    hr('体检结果')
    n_bad = n_warn = 0
    for r in results:
        if brief and r['level'] == OK:
            continue
        if r['level'] == BAD:
            n_bad += 1
        elif r['level'] == WARN:
            n_warn += 1
        line = f'  {ICON[r["level"]]} {r["title"]}'
        if r['detail']:
            line += f'  —  {r["detail"]}'
        print(line)
        if r['hint'] and r['level'] != OK:
            print(f'        → {r["hint"]}')

    hr()
    if n_bad:
        print(f'  ❌ {n_bad} 项严重问题，{n_warn} 项警告 —— 按上面的 → 提示处理。')
    elif n_warn:
        print(f'  ⚠️  全部功能可用，{n_warn} 项建议关注。')
    else:
        print('  ✅ 全部检查通过。')
    print()
    return n_bad


def export_pack():
    """打包一份诊断包：方便把现场发给别人/AI 看。"""
    import zipfile
    os.makedirs(os.path.join(PROJ, '.temp'), exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    out = os.path.join(PROJ, '.temp', f'诊断包-{stamp}.zip')
    logdir = os.path.join(PROJ, 'logs')
    n = 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 报告正文
        buf = []
        for r in results:
            buf.append(f'{r["level"]}\t{r["title"]}\t{r["detail"]}\t{r["hint"]}')
        zf.writestr('doctor.txt', '\n'.join(buf))
        zf.writestr('env.txt', '\n'.join([
            f'python={sys.version}',
            f'executable={sys.executable}',
            f'platform={sys.platform}',
            f'cwd={os.getcwd()}',
            f'project={PROJ}',
        ]))
        # 最近 3 个日志（只截尾部 3000 行，避免包太大）
        if os.path.isdir(logdir):
            logs = sorted((os.path.join(logdir, f) for f in os.listdir(logdir)
                           if f.endswith('.log')), key=os.path.getmtime)[-3:]
            for lp in logs:
                try:
                    with open(lp, encoding='utf-8', errors='replace') as f:
                        tail = f.readlines()[-3000:]
                    zf.writestr(f'logs/{os.path.basename(lp)}', ''.join(tail))
                    n += 1
                except OSError:
                    pass
        # 配置（只放 global.yml 和任务清单，不含 cookie）
        g = os.path.join(PROJ, 'configs', 'global.yml')
        if os.path.exists(g):
            zf.write(g, 'configs/global.yml')
        cfg = os.path.join(PROJ, 'configs')
        if os.path.isdir(cfg):
            tasks = sorted(f for f in os.listdir(cfg)
                           if f.startswith('DMR-') and f.endswith('.yml'))
            zf.writestr('configs/任务清单.txt', '\n'.join(tasks))
    size = os.path.getsize(out) / 1024
    print(f'  诊断包已生成: {out}  ({size:.0f} KB, 含 {n} 个日志尾部)')
    return out


def main():
    ap = argparse.ArgumentParser(description='DanmakuRepo 一键体检')
    ap.add_argument('--brief', action='store_true', help='只显示非 OK 的项')
    ap.add_argument('--export', action='store_true', help='打包诊断包')
    args = ap.parse_args()

    hr('DanmakuRepo 体检')
    print(f'  项目: {PROJ}')
    print(f'  时间: {time.strftime("%Y-%m-%d %H:%M:%S")}')

    for fn in (chk_python, chk_deps, chk_tools, chk_dirs, chk_configs,
               chk_state, chk_disk, chk_process, chk_tasks, chk_notify,
               chk_logs, chk_startup_error):
        try:
            fn()
        except Exception as e:
            add(WARN, f'检查项 {fn.__name__} 自身出错', repr(e), '把这条发给 AI')

    n_bad = render(args.brief)
    if args.export:
        export_pack()
    return 1 if n_bad else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
