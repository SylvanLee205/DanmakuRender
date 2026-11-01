"""项目路径常量 —— 全项目**唯一**的路径来源。

为什么需要这个模块
------------------
这个项目必须能放在**任意目录**跑：`F:\\DanmakuRepo`、`D:\\直播工具\\DMR`、
甚至 `C:\\Users\\someone\\DanmakuRepo`。所以：

1. **不许写死盘符**。任何 `F:\\DanmakuRepo\\xxx` 都是 bug。
2. **不许依赖"当前工作目录"**。计划任务（session 0）启动时 cwd 常常是
   `C:\\Windows\\System32`，用 `./tools/ffmpeg.exe` 会直接找不到。
3. **不许依赖 Python 的安装位置**。venv / 系统 Python / 便携版都可能。

所有路径一律从 ``ROOT`` 派生，而 ``ROOT`` 是这个文件所在包的上一级 ——
不管谁在什么目录下 import，结果都指向项目根。

外部目录（配置快照、备份盘）可以用环境变量覆盖，见各函数。
"""
import os
import sys

__all__ = (
    'ROOT', 'TOOLS', 'CONFIGS', 'LOGS', 'TEMP', 'BACKUPS', 'DOCS',
    'RECORDINGS', 'SYSTEM32', 'is_frozen',
    'p', 'ensure', 'enter_root', 'system32', 'powershell_exe',
    'snapshot_dir', 'backup_dir', 'release_dir', 'data_root',
)


#: Windows 系统目录（System32）。非 Windows 上没有意义。
SYSTEM32 = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32')


def system32(name: str) -> str:
    """返回 System32 下某个系统工具的**绝对路径**；找不到就退回裸名字。

    ⚠️ 为什么不能直接写 'schtasks' / 'curl.exe'：
        计划任务（session 0）和某些精简过的环境 PATH 里**没有** System32，
        2026-10-19 就因此踩过 FileNotFoundError，表现为"脚本一跑就崩，
        但用户自己开命令行跑又正常"。用绝对路径才稳。
    """
    path = os.path.join(SYSTEM32, name)
    return path if os.path.exists(path) else name


def powershell_exe() -> str:
    """powershell.exe 的绝对路径。

    ⚠️ 实测：在项目自己的 venv 里 `subprocess.run(['powershell', ...])`
        会 FileNotFoundError —— 进程 PATH 不含 PowerShell 目录。
        所以统一走这里。
    """
    cand = os.path.join(SYSTEM32, 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    if os.path.exists(cand):
        return cand
    return 'powershell'


def is_frozen() -> bool:
    """是否被打包成单文件 exe（PyInstaller 等）。

    打包后 ``__file__`` 指向临时解包目录，项目根要取 exe 所在目录。
    目前没有打包，但预留给将来。
    """
    return bool(getattr(sys, 'frozen', False))


#: 项目根目录。本文件位于 ``<ROOT>/DMR/paths.py``，上跳两层即为根。
if is_frozen():
    ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 外部可执行文件（ffmpeg / ffprobe / rclone / biliup）
TOOLS = os.path.join(ROOT, 'tools')
#: 每个主播一个 yml
CONFIGS = os.path.join(ROOT, 'configs')
#: 运行日志
LOGS = os.path.join(ROOT, 'logs')
#: 中间状态（状态库、字形缓存、失败渲染队列…）
TEMP = os.path.join(ROOT, '.temp')
#: 配置快照 / 启动链备份
BACKUPS = os.path.join(ROOT, 'backups')
#: 文档
DOCS = os.path.join(ROOT, 'docs')
#: 默认录制输出根目录（每个任务的实际目录由配置里的 output_dir 决定）
RECORDINGS = os.path.join(ROOT, '直播回放')


def p(*parts: str) -> str:
    """拼出项目内的绝对路径。``p('tools', 'ffmpeg.exe')``"""
    return os.path.join(ROOT, *parts)


def ensure(*parts: str) -> str:
    """拼路径并确保目录存在，返回该路径。"""
    path = os.path.join(ROOT, *parts)
    os.makedirs(path, exist_ok=True)
    return path


def enter_root() -> str:
    """把工作目录切到项目根，并让 ``import tools.xxx`` 可用。幂等。

    ⚠️ 为什么还要 chdir：
        配置里的 ``output_dir: ./直播回放`` 是相对路径，其他模块里也有大量
        ``open('.temp/xxx')`` 这样的写法。chdir 到根目录后它们才对。
        新代码请尽量用 ``p()``，但不必为了这个去改历史代码。

    ⚠️ 必须在**任何**入口（main.py / dryrun.py / render_only.py /
        tools/*.py）最早处调用，否则从计划任务启动时会写错位置。
    """
    os.chdir(ROOT)
    if TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)
    return ROOT


def data_root() -> str:
    """录制数据的总根目录。

    可用环境变量 ``DMR_DATA_ROOT`` 指到别的盘（录制盘独立于项目盘时用）。
    默认就是项目根。
    """
    return os.environ.get('DMR_DATA_ROOT') or ROOT


def snapshot_dir(auto_migrate_legacy=True) -> str:
    """配置快照目录。

    默认 ``<ROOT>/backups/配置快照``（跟着项目走，换机器一起搬）。
    可用 ``DMR_SNAPSHOT_DIR`` 覆盖到别的盘。

    ``auto_migrate_legacy``：旧版本把快照写在 ``F:\\_DMR配置快照``（项目外）。
    首次在新位置找不到历史时，如果旧位置存在就**复制**一份过来 —— 只复制
    不删除，用户的旧数据永远还在原地。
    """
    path = os.environ.get('DMR_SNAPSHOT_DIR') or os.path.join(BACKUPS, '配置快照')
    os.makedirs(path, exist_ok=True)

    if auto_migrate_legacy:
        legacy = 'F:\\_DMR配置快照'
        try:
            empty = not any(os.scandir(path))
        except OSError:
            empty = False
        if empty and os.path.isdir(legacy) and os.path.abspath(legacy) != os.path.abspath(path):
            import shutil
            for name in os.listdir(legacy):
                src = os.path.join(legacy, name)
                dst = os.path.join(path, name)
                if os.path.exists(dst):
                    continue
                try:
                    if os.path.isdir(src):
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
                except OSError:
                    pass
    return path


def backup_dir() -> str:
    """大件备份目录（整包发布、云端打包等）。默认 ``<ROOT>/backups``。"""
    path = os.environ.get('DMR_BACKUP_DIR') or BACKUPS
    os.makedirs(path, exist_ok=True)
    return path


def release_dir() -> str:
    """发布产物目录。默认 ``<ROOT>/backups/release``。"""
    path = os.environ.get('DMR_RELEASE_DIR') or os.path.join(BACKUPS, 'release')
    os.makedirs(path, exist_ok=True)
    return path
