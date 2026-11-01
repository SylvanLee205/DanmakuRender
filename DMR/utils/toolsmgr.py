"""外部可执行文件的定位与安装（ffmpeg / ffprobe / rclone / biliup）。

设计原则
--------
1. **位置无关**
   项目 ``tools/`` 目录、系统 PATH、winget / scoop / chocolatey 的安装位置、
   以及常见的 ``C:\\Program Files\\...`` 都会被查到。项目放在哪个盘都行。

2. **版本无关**
   只验证"这个 exe 能跑起来"，**不校验版本号**。
   ffmpeg 6.0 / 7.1 / 8.0、rclone 1.6x / 1.7x 都直接用。
   上游哪天停止维护某个旧版本，用户装新版照样能跑。

3. **绝不阻塞无人值守启动**
   计划任务 / session 0 里没有控制台，任何 ``input()`` 都会挂死或 EOFError
   （2026-10-19 踩过：表现为"程序根本没启动，连一行日志都没有"）。
   本模块**一个 input() 都没有**；需要交互的安装流程在 ``tools/bootstrap.py``。

4. **失败可见**
   找不到会写 ``logs/startup_error.log`` 并在 stdout 打印处理办法，
   而不是静默返回 None 让后面某个 subprocess 报个看不懂的 WinError 2。

5. **可覆盖**
   环境变量 ``DMR_FFMPEG`` / ``DMR_FFPROBE`` / ``DMR_RCLONE`` / ``DMR_BILIUP``
   指定绝对路径时优先使用（便携部署、多版本共存时用）。
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile


__all__ = (
    'check_ffmpeg', 'check_ffprobe', 'check_rclone', 'check_biliup',
    'ToolsList', 'find_tool', 'install_tool', 'TOOL_SPECS',
)

#: 项目根（本文件在 <ROOT>/DMR/utils/，上跳三层）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOLS_DIR = os.path.join(_ROOT, 'tools')


def _log_error(msg: str) -> None:
    """把启动期错误同时写到 logs/startup_error.log（session 0 没有控制台）。"""
    try:
        from datetime import datetime
        d = os.path.join(_ROOT, 'logs')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'startup_error.log'), 'a', encoding='utf-8') as f:
            f.write(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n')
    except Exception:
        pass


def _registry_path_dirs() -> list:
    """从注册表读**最新的** PATH，而不是当前进程继承的那份。

    ⚠️ 为什么必须这么做：
        进程的 PATH 是启动那一刻的快照。用户刚装完 ffmpeg（安装程序改了
        系统 PATH），如果 DMR 是从开机任务启动的、或者这个 shell 比安装
        更早，就会「明明装了却说找不到」。读注册表能拿到最新值。

    实测本机就是这种情况：ffmpeg 在 `C:\\User Program Files\\FFmpeg\\bin`、
    rclone 在 `C:\\User Program Files\\rclone-v1.75.1`，都在注册表 PATH 里，
    但进程环境里没有。
    """
    if sys.platform != 'win32':
        return []
    try:
        import winreg
    except ImportError:
        return []

    dirs = []
    keys = (
        (winreg.HKEY_LOCAL_MACHINE,
         r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path'),
        (winreg.HKEY_CURRENT_USER, r'Environment', 'Path'),
    )
    for hive, subkey, vname in keys:
        try:
            with winreg.OpenKey(hive, subkey) as k:
                val, _ = winreg.QueryValueEx(k, vname)
        except OSError:
            continue
        if not isinstance(val, str):
            continue
        # REG_EXPAND_SZ 里可能有 %SystemRoot% 之类
        val = os.path.expandvars(val)
        for d in val.split(';'):
            d = d.strip().strip('"')
            if d and d not in dirs:
                dirs.append(d)
    return dirs


def _scan_program_dirs(name: str) -> list:
    """在 Program Files 类目录下找名字含工具名的子目录。

    覆盖「解压到 C:\\User Program Files\\rclone-v1.75.1 这种自定义目录」
    的装法 —— 这类路径不在任何一个标准位置，但目录名里有线索。
    """
    if sys.platform != 'win32':
        return []
    roots = [
        os.environ.get('ProgramFiles', r'C:\Program Files'),
        os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
        r'C:\User Program Files',      # 本机实际用的自定义目录
        r'C:\Tools',
        r'D:\Tools',
    ]
    hits = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        try:
            subs = os.listdir(root)
        except OSError:
            continue
        for sub in subs:
            if name.lower() not in sub.lower():
                continue
            base = os.path.join(root, sub)
            if os.path.isdir(base):
                hits.append(base)
                hits.append(os.path.join(base, 'bin'))
    return hits


def _win_common_dirs() -> list:
    """Windows 上各种包管理器/常见安装位置。存在的才返回。"""
    if sys.platform != 'win32':
        return []
    env = os.environ
    cands = [
        os.path.join(env.get('LOCALAPPDATA', ''), 'Microsoft', 'WinGet', 'Links'),
        os.path.join(env.get('PROGRAMDATA', r'C:\ProgramData'), 'chocolatey', 'bin'),
        os.path.join(env.get('USERPROFILE', ''), 'scoop', 'shims'),
        r'C:\Program Files\ffmpeg\bin',
        r'C:\ffmpeg\bin',
        r'C:\Program Files\rclone',
        r'C:\Program Files (x86)\rclone',
        os.path.join(_TOOLS_DIR, 'bin'),
        os.path.join(_TOOLS_DIR, 'ffmpeg', 'bin'),
        os.path.join(_TOOLS_DIR, 'rclone'),
    ]
    return [d for d in cands if d and os.path.isdir(d)]


def _exe(name: str) -> str:
    return name + '.exe' if sys.platform == 'win32' else name


def _is_executable(path: str) -> bool:
    if not path:
        return False
    if os.path.isfile(path):
        return True
    return bool(shutil.which(path))


def _probe(path, args, keyword=None, timeout=20) -> bool:
    """跑一下确认能用。**任何异常都只算 False**，绝不向上抛。"""
    if not _is_executable(path):
        return False
    try:
        r = subprocess.run(
            [path] + list(args),
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=timeout,
            # ⚠️ 必须屏蔽 stdin：某些工具在没有输入时会等 stdin，导致挂死
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        return False
    out = ((r.stdout or '') + (r.stderr or '')).lower()
    if keyword and keyword.lower() not in out:
        # 有些工具 -help 的退出码非 0，所以以输出内容为准
        return False
    return bool(out.strip()) or r.returncode == 0


#: 每个工具的探测规格。
#:   env      : 环境变量名（用户可强制指定）
#:   exe      : 可执行文件名（不含扩展名）
#:   probe    : 用来验证"能跑"的参数
#:   keyword  : 输出里必须出现的关键字（None = 只要能跑就算）
#:   required : 缺失时是否算致命错误（ffmpeg 是硬依赖，其余不是）
TOOL_SPECS = {
    'ffmpeg':  dict(env='DMR_FFMPEG',  exe='ffmpeg',  probe=['-version'], keyword='ffmpeg version',  required=True),
    'ffprobe': dict(env='DMR_FFPROBE', exe='ffprobe', probe=['-version'], keyword='ffprobe version', required=True),
    'rclone':  dict(env='DMR_RCLONE',  exe='rclone',  probe=['version'],  keyword='rclone',          required=False),
    'biliup':  dict(env='DMR_BILIUP',  exe='biliup',  probe=['upload', '-help'], keyword=None,       required=False),
}


#: 找到过的结果缓存，避免每次 get 都去扫注册表和 Program Files
_FOUND: dict = {}


def find_tool(name: str):
    """按优先级找一个工具，返回可用路径；找不到返回 None。

    顺序：环境变量 → 项目 tools/ → PATH → 注册表 PATH → 常见安装目录
          → Program Files 下的同名子目录。
    """
    spec = TOOL_SPECS.get(name)
    if not spec:
        return None
    if name in _FOUND:
        return _FOUND[name] or None

    hit = _find_tool_uncached(name, spec)
    _FOUND[name] = hit or ''
    return hit


def _find_tool_uncached(name: str, spec: dict):
    seen = set()

    def _try(path):
        if not path or path in seen:
            return None
        seen.add(path)
        return path if _probe(path, spec['probe'], spec['keyword']) else None

    # 1) 环境变量（允许写目录，也允许写完整文件名）
    env_val = os.environ.get(spec['env'])
    if env_val:
        hit = _try(env_val.strip('"'))
        if hit:
            return hit
        if os.path.isdir(env_val):
            hit = _try(os.path.join(env_val, _exe(spec['exe'])))
            if hit:
                return hit

    # 2) 项目 tools/（含常见子目录）
    for d in (_TOOLS_DIR, os.path.join(_TOOLS_DIR, 'bin'),
              os.path.join(_TOOLS_DIR, spec['exe']),
              os.path.join(_TOOLS_DIR, spec['exe'], 'bin')):
        hit = _try(os.path.join(d, _exe(spec['exe'])))
        if hit:
            return hit

    # 3) PATH（进程继承的那份）
    hit = _try(shutil.which(spec['exe']))
    if hit:
        return hit

    # 4) 注册表里的最新 PATH —— 进程环境的 PATH 可能是安装之前的旧快照
    for d in _registry_path_dirs():
        hit = _try(os.path.join(d, _exe(spec['exe'])))
        if hit:
            return hit

    # 5) 常见包管理器目录
    for d in _win_common_dirs():
        hit = _try(os.path.join(d, _exe(spec['exe'])))
        if hit:
            return hit

    # 6) Program Files 类目录下名字含工具名的子目录（自定义安装位置）
    for d in _scan_program_dirs(spec['exe']):
        hit = _try(os.path.join(d, _exe(spec['exe'])))
        if hit:
            return hit

    return None


def _explain(name: str) -> str:
    spec = TOOL_SPECS[name]
    exe = _exe(spec['exe'])
    return (
        f'找不到 {name}。请任选一种方式：\n'
        f'  1) 装到系统 PATH      —— 装完新开一个命令行，`where {spec["exe"]}` 能看到即可\n'
        f'  2) 放到 {_TOOLS_DIR}\\{exe}\n'
        f'  3) 双击项目根目录的 Setup.bat，让脚本自动下载到 tools\\\n'
        f'  4) 设环境变量 {spec["env"]}=D:\\path\\to\\{exe}\n'
        f'（本项目不校验版本，任何较新的版本都可以用）'
    )


def check_ffmpeg() -> bool:
    """定位 ffmpeg + ffprobe。缺任何一个都算失败。

    ⚠️ 2026-11-02 重写：原版在找不到时会 ``input()`` 等回车再自动下载。
        在计划任务 / session 0 下那是**永久卡死**。现在只做定位 + 报错。
    """
    ok = True
    for name in ('ffmpeg', 'ffprobe'):
        path = find_tool(name)
        if path:
            ToolsList.set(name, path)
        else:
            ok = False
            print(f'[DMR] {_explain(name)}')
            _log_error(f'{name} 未找到。')
    return ok


def check_ffprobe() -> bool:
    return check_ffmpeg()


def check_rclone() -> bool:
    """定位 rclone（网盘上传用）。没装不影响录制，只影响上传。"""
    path = find_tool('rclone')
    if path:
        ToolsList.set('rclone', path)
        return True
    print('[DMR] 未找到 rclone —— 网盘上传会跳过。' + _explain('rclone'))
    _log_error('rclone 未找到，上传功能不可用。')
    return False


def check_biliup() -> bool:
    """定位 biliup（B 站上传用）。

    ⚠️ 2026-11-02：以前缺了会 ``raise RuntimeError``，把整个程序拦住。
       但它是**可选**的 —— 用 rclone 传网盘的话根本不需要它。
       现在找不到只返回 False。
    """
    path = find_tool('biliup')
    if path:
        ToolsList.set('biliup', path)
        return True
    return False


# ─────────────────────────── 下载安装（供 Setup.bat 调用） ───────────────────────────

def _download(url: str, dst: str, show_progress=True) -> bool:
    import requests
    try:
        with requests.get(url, stream=True, timeout=60, allow_redirects=True) as r:
            r.raise_for_status()
            total = int(r.headers.get('Content-Length') or 0)
            got = 0
            tmp = dst + '.part'
            with open(tmp, 'wb') as f:
                for chunk in r.iter_content(256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    got += len(chunk)
                    if show_progress and total:
                        pct = got * 100 // total
                        print(f'\r    下载中 {pct:3d}%  {got/1024/1024:6.1f} MB', end='', flush=True)
            if show_progress:
                print()
            os.replace(tmp, dst)
        return True
    except Exception as e:
        print(f'\n    下载失败: {e}')
        return False


def _github_latest_asset(repo: str, pattern_fn):
    """取 GitHub 最新 release 里匹配的 asset 下载地址。**不写死版本号。**"""
    import requests
    r = requests.get(f'https://api.github.com/repos/{repo}/releases/latest',
                     timeout=30, headers={'Accept': 'application/vnd.github+json'})
    r.raise_for_status()
    data = r.json()
    tag = data.get('tag_name', '')
    for a in data.get('assets', []):
        name = a.get('name', '')
        if pattern_fn(name):
            return a.get('browser_download_url'), name, tag
    raise RuntimeError(f'{repo} 最新版 {tag} 里找不到匹配的安装包')


def install_tool(name: str, force=False) -> bool:
    """把工具下载到项目 tools/ 目录。返回是否成功。

    全部走"最新版"，不锁版本号 —— 上游发新版直接就能装上。
    """
    os.makedirs(_TOOLS_DIR, exist_ok=True)

    if not force:
        hit = find_tool(name)
        if hit:
            print(f'  {name} 已可用: {hit}')
            return True

    if name in ('ffmpeg', 'ffprobe'):
        return _install_ffmpeg()
    if name == 'rclone':
        return _install_rclone()
    if name == 'biliup':
        return _install_biliup()
    print(f'  不知道如何安装 {name}')
    return False


def _install_ffmpeg() -> bool:
    """ffmpeg：优先 gyan.dev 的 release-essentials（永远是 latest）。"""
    import io
    zip_path = os.path.join(_TOOLS_DIR, '_ffmpeg_download.zip')
    urls = [
        'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip',
        'https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip',
    ]
    for url in urls:
        print(f'  下载 ffmpeg: {url}')
        if not _download(url, zip_path):
            continue
        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                want = {}
                for n in names:
                    base = os.path.basename(n).lower()
                    if base in ('ffmpeg.exe', 'ffprobe.exe'):
                        want[base] = n
                if 'ffmpeg.exe' not in want or 'ffprobe.exe' not in want:
                    print('    ⚠️ 压缩包里没有 ffmpeg.exe/ffprobe.exe，换下一个源')
                    continue
                for base, member in want.items():
                    with zf.open(member) as src, open(os.path.join(_TOOLS_DIR, base), 'wb') as dst:
                        shutil.copyfileobj(src, dst)
            os.remove(zip_path)
            print(f'    ✅ 已安装到 {_TOOLS_DIR}')
            return check_ffmpeg()
        except Exception as e:
            print(f'    解压失败: {e}')
    try:
        os.remove(zip_path)
    except OSError:
        pass
    print('  ❌ ffmpeg 自动安装失败。请手动下载：https://www.gyan.dev/ffmpeg/builds/')
    return False


def _install_rclone() -> bool:
    zip_path = os.path.join(_TOOLS_DIR, '_rclone_download.zip')
    try:
        url, fname, tag = _github_latest_asset(
            'rclone/rclone',
            lambda n: n.startswith('rclone-v') and 'windows-amd64' in n and n.endswith('.zip'))
    except Exception as e:
        print(f'  ❌ 查询 rclone 最新版失败: {e}')
        print('     手动下载: https://rclone.org/downloads/')
        return False
    print(f'  下载 rclone {tag}: {fname}')
    if not _download(url, zip_path):
        return False
    try:
        with zipfile.ZipFile(zip_path) as zf:
            member = next((n for n in zf.namelist()
                           if os.path.basename(n).lower() == 'rclone.exe'), None)
            if not member:
                print('    ⚠️ 压缩包里没有 rclone.exe')
                return False
            with zf.open(member) as src, open(os.path.join(_TOOLS_DIR, 'rclone.exe'), 'wb') as dst:
                shutil.copyfileobj(src, dst)
        os.remove(zip_path)
        print(f'    ✅ 已安装到 {_TOOLS_DIR}')
        return check_rclone()
    except Exception as e:
        print(f'    解压失败: {e}')
        return False


def _install_biliup() -> bool:
    """biliup：从 GitHub 最新 release 拿 Windows 包（不再写死 v1.1.28）。"""
    zip_path = os.path.join(_TOOLS_DIR, '_biliup_download.zip')
    try:
        url, fname, tag = _github_latest_asset(
            'biliup/biliup',
            lambda n: 'windows' in n.lower() and n.endswith('.zip'))
    except Exception as e:
        print(f'  ❌ 查询 biliup 最新版失败: {e}')
        print('     手动下载: https://github.com/biliup/biliup/releases')
        return False
    print(f'  下载 biliup {tag}: {fname}')
    if not _download(url, zip_path):
        return False
    try:
        with zipfile.ZipFile(zip_path) as zf:
            member = next((n for n in zf.namelist()
                           if os.path.basename(n).lower() == 'biliup.exe'), None)
            if not member:
                print('    ⚠️ 压缩包里没有 biliup.exe')
                return False
            with zf.open(member) as src, open(os.path.join(_TOOLS_DIR, 'biliup.exe'), 'wb') as dst:
                shutil.copyfileobj(src, dst)
        os.remove(zip_path)
        print(f'    ✅ 已安装到 {_TOOLS_DIR}')
        return check_biliup()
    except Exception as e:
        print(f'    解压失败: {e}')
        return False


class ToolsList(dict):
    """工具路径注册表。``ToolsList.get('ffmpeg')`` 返回可直接执行的路径。"""

    _tools = {}

    @classmethod
    def get(cls, name: str, auto_install=True):
        if not cls._tools.get(name) and auto_install:
            if name == 'biliup':
                check_biliup()
            elif name in ('ffmpeg', 'ffprobe'):
                check_ffmpeg()
            elif name == 'rclone':
                check_rclone()
        return cls._tools.get(name)

    @classmethod
    def set(cls, name: str, path: str):
        cls._tools[name] = path

    @classmethod
    def all(cls) -> dict:
        """当前已定位的所有工具（诊断用）。"""
        return dict(cls._tools)
