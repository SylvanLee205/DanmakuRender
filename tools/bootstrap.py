"""首次安装 / 环境修复向导。由项目根目录的 Setup.bat 调用。

它做的事（每一步都幂等，可以反复跑）
----------------------------------
1. 检查 Python 版本（3.9+ 都能用，不锁死某个小版本）
2. 没有 .venv 就创建一个，并切换进去继续
3. 安装 requirements.txt（先清华镜像，失败自动回退官方源）
4. 定位 / 下载 ffmpeg、ffprobe、rclone（biliup 可选）
5. 缺 configs/global.yml 时从内置默认配置生成
6. 创建录制目录
7. 可选：创建桌面快捷方式、注册开机计划任务

设计原则
--------
* **不锁版本**：ffmpeg / rclone / biliup 全部装"最新版"；Python 只要 3.9+。
  上游哪天停止维护老版本，用户装新的照样能跑。
* **不猜路径**：所有路径从 DMR.paths 派生，项目放哪个盘都行。
* **可无人值守**：``--yes`` 全程不问问题。
* **失败可续**：任何一步失败都不破坏已完成的部分，重跑即可。

用法：
    python tools\\bootstrap.py           # 交互式
    python tools\\bootstrap.py --yes     # 全部用默认值，不提问
    python tools\\bootstrap.py --skip-tools   # 只修 Python 环境，不动外部工具
"""
import argparse
import os
import subprocess
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_DIR = os.path.join(PROJ, '.venv')
IS_WIN = sys.platform == 'win32'
VENV_PY = os.path.join(VENV_DIR, 'Scripts' if IS_WIN else 'bin',
                       'python.exe' if IS_WIN else 'python')

MIN_PY = (3, 9)
RECOMMENDED_PY = (3, 11)

MIRRORS = [
    'https://pypi.tuna.tsinghua.edu.cn/simple',
    'https://mirrors.aliyun.com/pypi/simple/',
    None,                      # None = PyPI 官方
]

OK = '[ OK ]'
WARN = '[WARN]'
ERR = '[FAIL]'


def hr(title=''):
    print()
    print('=' * 70)
    if title:
        print(f'  {title}')
        print('=' * 70)


def ask(question, default=True, assume_yes=False):
    if assume_yes:
        return default
    try:
        s = input(f'  {question} [{"Y/n" if default else "y/N"}] ').strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default
    if not s:
        return default
    return s in ('y', 'yes', '是', '好')


# ─────────────────────────────── 1. Python ───────────────────────────────
def check_python():
    v = sys.version_info
    print(f'  Python {v.major}.{v.minor}.{v.micro}  ({sys.executable})')
    if (v.major, v.minor) < MIN_PY:
        print(f'  {ERR} 需要 Python {MIN_PY[0]}.{MIN_PY[1]} 或更高。')
        print('        下载: https://www.python.org/downloads/')
        print('        安装时务必勾选 "Add Python to PATH"。')
        return False
    if (v.major, v.minor) < RECOMMENDED_PY:
        print(f'  {WARN} 建议 3.11+（不是必须，{v.major}.{v.minor} 也能跑）')
    return True


def in_venv():
    return (hasattr(sys, 'real_prefix')
            or sys.prefix != getattr(sys, 'base_prefix', sys.prefix))


def ensure_venv(recreate=False):
    """保证 .venv 存在。返回需要用哪个解释器继续（None = 当前就是对的）。"""
    if os.path.abspath(sys.executable).lower() == os.path.abspath(VENV_PY).lower():
        return None
    if in_venv() and os.path.abspath(sys.executable).lower() != os.path.abspath(VENV_PY).lower():
        # 跑在别人的 venv 里 —— 还是在本项目里建一个干净的
        print(f'  {WARN} 当前在另一个虚拟环境里，将在项目内新建 .venv')

    if os.path.exists(VENV_PY) and not recreate:
        print(f'  {OK} 已有虚拟环境: {VENV_DIR}')
        return VENV_PY

    if recreate and os.path.isdir(VENV_DIR):
        import shutil
        print('  删除旧虚拟环境 ...')
        shutil.rmtree(VENV_DIR, ignore_errors=True)

    print('  创建虚拟环境 .venv ...（首次约 10 秒）')
    r = subprocess.run([sys.executable, '-m', 'venv', VENV_DIR])
    if r.returncode != 0 or not os.path.exists(VENV_PY):
        print(f'  {ERR} 创建虚拟环境失败。')
        print('        Debian/Ubuntu 上可能需要: apt install python3-venv')
        return None
    print(f'  {OK} 虚拟环境已创建')
    return VENV_PY


# ─────────────────────────────── 2. 依赖 ───────────────────────────────
def pip_install(req_file):
    base = [sys.executable, '-m', 'pip', 'install', '-r', req_file,
            '--disable-pip-version-check']
    for mirror in MIRRORS:
        cmd = base + (['-i', mirror] if mirror else [])
        label = mirror or 'PyPI 官方源'
        print(f'  使用 {label} 安装依赖 ...')
        try:
            r = subprocess.run(cmd)
        except Exception as e:
            print(f'  {WARN} {e}')
            continue
        if r.returncode == 0:
            print(f'  {OK} 依赖安装完成')
            return True
        print(f'  {WARN} 这个源不行，换下一个 ...')
    print(f'  {ERR} 依赖安装失败。')
    print('        手动执行:')
    print(f'          "{sys.executable}" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple')
    return False


def verify_imports():
    mods = ['requests', 'aiohttp', 'jsengine', 'lxml', 'yaml',
            'stream_gears', 'websocket', 'brotli', 'yutto',
            'easydict', 'streamlink', 'm3u8', 'gmssl', 'rsa',
            'PIL', 'fontTools', 'flask']
    bad = []
    for m in mods:
        try:
            __import__(m)
        except Exception:
            bad.append(m)
    if bad:
        print(f'  {WARN} 以下模块导入失败: {", ".join(bad)}')
        return False
    print(f'  {OK} 依赖自检通过（{len(mods)} 个模块）')
    return True


# ─────────────────────────────── 3. 外部工具 ───────────────────────────────
def setup_tools(assume_yes=False):
    sys.path.insert(0, PROJ)
    from DMR.utils import toolsmgr

    results = {}
    for name, optional in (('ffmpeg', False), ('ffprobe', False),
                           ('rclone', False), ('biliup', True)):
        path = toolsmgr.find_tool(name)
        if path:
            print(f'  {OK} {name:<8} {path}')
            results[name] = path
            continue
        if name in ('ffprobe',):
            continue          # 跟着 ffmpeg 一起
        print(f'  {WARN} {name:<8} 未找到')
        if optional:
            if ask(f'要下载 {name} 吗？（B 站上传才需要，可跳过）', False, assume_yes):
                toolsmgr.install_tool(name)
            continue
        if ask(f'要自动下载 {name} 到 tools\\ 目录吗？（约 30-80 MB）', True, assume_yes):
            if toolsmgr.install_tool(name):
                results[name] = toolsmgr.find_tool(name)
    return results


# ─────────────────────────────── 4. 配置与目录 ───────────────────────────────
def setup_config():
    cfg_dir = os.path.join(PROJ, 'configs')
    os.makedirs(cfg_dir, exist_ok=True)
    global_yml = os.path.join(cfg_dir, 'global.yml')
    if os.path.exists(global_yml):
        print(f'  {OK} configs/global.yml 已存在')
        return True

    default_yml = os.path.join(PROJ, 'DMR', 'Config', 'default.yml')
    if not os.path.exists(default_yml):
        print(f'  {WARN} 找不到内置默认配置 DMR/Config/default.yml')
        return False
    import shutil
    shutil.copy2(default_yml, global_yml)
    print(f'  {OK} 已从内置默认配置生成 configs/global.yml')
    print('        要改下载/渲染/上传参数就编辑它。')
    return True


def setup_dirs():
    for d in ('直播回放', 'logs', '.temp', 'backups'):
        os.makedirs(os.path.join(PROJ, d), exist_ok=True)
    print(f'  {OK} 目录就绪: 直播回放 / logs / .temp / backups')


# ─────────────────────────────── 5. 可选集成 ───────────────────────────────
def setup_desktop(assume_yes=False):
    script = os.path.join(PROJ, 'tools', 'install_desktop_links.py')
    if not os.path.exists(script):
        return
    if not ask('要在桌面创建快捷方式吗？', True, assume_yes):
        return
    subprocess.call([sys.executable, script])


def setup_boot_task(assume_yes=False):
    script = os.path.join(PROJ, 'tools', 'install_boot_task.py')
    if not os.path.exists(script):
        return
    if not ask('要注册"开机自动启动"计划任务吗？（需要管理员权限）', False, assume_yes):
        return
    subprocess.call([sys.executable, script])


# ─────────────────────────────── main ───────────────────────────────
def main():
    ap = argparse.ArgumentParser(description='DanmakuRepo 首次安装 / 环境修复')
    ap.add_argument('--yes', '-y', action='store_true', help='全部使用默认值，不提问')
    ap.add_argument('--skip-tools', action='store_true', help='跳过 ffmpeg/rclone 安装')
    ap.add_argument('--recreate-venv', action='store_true', help='删掉重建虚拟环境')
    args = ap.parse_args()

    hr('DanmakuRepo 安装向导')
    print(f'  项目目录: {PROJ}')

    # ---- Python ----
    hr('1/5  Python')
    if not check_python():
        return 2

    # ---- 虚拟环境：不在 .venv 里就用 .venv 重跑自己 ----
    hr('2/5  虚拟环境')
    target_py = ensure_venv(recreate=args.recreate_venv)
    if target_py is None:
        print(f'  {OK} 当前就是项目虚拟环境')
    elif os.path.abspath(target_py).lower() != os.path.abspath(sys.executable).lower():
        env = os.environ.copy()
        env['DMR_BOOTSTRAP_CHILD'] = '1'
        print(f'  切换解释器重跑: {target_py}')
        return subprocess.call([target_py, os.path.abspath(__file__)] + sys.argv[1:], env=env)

    # ---- 依赖 ----
    hr('3/5  Python 依赖')
    req = os.path.join(PROJ, 'requirements.txt')
    if not os.path.exists(req):
        print(f'  {ERR} 找不到 requirements.txt')
        return 2
    if not verify_imports():
        if not pip_install(req):
            return 3
        if not verify_imports():
            print(f'  {WARN} 依赖装完了但仍有模块导入失败，请把上面的报错发出来。')

    # ---- 外部工具 ----
    hr('4/5  外部工具（ffmpeg / rclone）')
    if args.skip_tools:
        print('  （已跳过）')
    else:
        tools = setup_tools(args.yes)
        if not tools.get('ffmpeg'):
            print(f'\n  {ERR} 没有 ffmpeg 就无法录制 —— 这步必须完成。')
            print('        手动装法（任选）：')
            print('          1) 下载 https://www.gyan.dev/ffmpeg/builds/ 解压后把 bin 目录加进 PATH')
            print('          2) 把 ffmpeg.exe / ffprobe.exe 直接放进 tools\\ 目录')
            print('          3) 重跑本向导并选择自动下载')
        if not tools.get('rclone'):
            print(f'  {WARN} 没有 rclone —— 录制备份不受影响，但网盘上传会跳过。')

    # ---- 配置 ----
    hr('5/5  配置与目录')
    setup_config()
    setup_dirs()

    # ---- 可选 ----
    hr('可选集成')
    setup_desktop(args.yes)
    setup_boot_task(args.yes)

    # ---- 总结 ----
    hr('完成')
    print('  下一步：')
    print('    1) 双击 Start_DMR.bat      启动录制（有窗口，崩溃自动重启）')
    print('    2) 双击 Add_Room.bat       粘贴直播间链接即可新增主播')
    print('    3) 双击 Doctor.bat         任何时候出问题，先跑这个')
    print()
    print('  常用脚本：')
    for f in sorted(os.listdir(PROJ)):
        if f.lower().endswith('.bat') and not f.startswith('_'):
            print(f'    {f}')
    print()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n  已取消。')
        sys.exit(130)
