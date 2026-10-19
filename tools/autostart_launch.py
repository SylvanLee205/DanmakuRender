"""登录/开机时可靠地拉起 DMR（带重试）。

为什么需要它（2026-10-19 事故）
------------------------------
原来自启入口是 `explorer.exe "Start_Render.bat"`。**在登录瞬间 explorer 还没初始化完**，
这个调用会被静默丢弃 —— 实测 10-19 14:44 / 14:52 / 14:54 三次登录，`autostart.log`
都记了「准备启动」，但 DMR 一个都没起来，而且没有任何报错。

现在改为：用 CreateProcess 直接拉起（DETACHED_PROCESS，父进程退出不受影响），
拉起后**等 25 秒再检查一次**，没起来就重试，最多 3 次；每次结果都写 `logs/autostart.log`。
这样即使登录瞬间环境没准备好，后面几次重试也能补上。

用法：
    .venv\\Scripts\\python.exe tools\\autostart_launch.py
    .venv\\Scripts\\python.exe tools\\autostart_launch.py --dry-run
    .venv\\Scripts\\python.exe tools\\autostart_launch.py --foreground
        # 计划任务用：前台阻塞运行 Start_Render.bat，任务会一直显示"运行中"，
        # 且启动/退出都写日志 —— session 0 没有控制台，日志是唯一的观察窗口。
    .venv\\Scripts\\python.exe tools\\autostart_launch.py --boot-fallback 180
        # 开机任务用（推荐）：先等 180 秒，看有没有人登录。
        #   · 有人登录 → 直接退出，交给登录自启去启动（这样 DMR 跑在用户会话里，
        #     桌面上**能看到**控制台窗口，就是以前的样子）
        #   · 没人登录 → 才在当前（session 0）把 DMR 起起来，保证录像不停
        # 这样"可靠性"和"看得见"两边都占。
"""
import os
import subprocess
import sys
import time

UP = r'F:\DanmakuRender_AutoUp'
BAT = os.path.join(UP, 'Start_Render.bat')
LOG = os.path.join(UP, 'logs', 'autostart.log')
DRY_RUN = '--dry-run' in sys.argv
FOREGROUND = '--foreground' in sys.argv
RETRIES = 3
WAIT_AFTER_LAUNCH = 25


def _boot_fallback_seconds():
    """解析 --boot-fallback N；返回 0 表示不使用该模式。"""
    for i, a in enumerate(sys.argv):
        if a == '--boot-fallback':
            try:
                return max(0, int(sys.argv[i + 1]))
            except (IndexError, ValueError):
                return 180
        if a.startswith('--boot-fallback='):
            try:
                return max(0, int(a.split('=', 1)[1]))
            except ValueError:
                return 180
    return 0


BOOT_FALLBACK = _boot_fallback_seconds()

#: 有 Explorer 就说明存在一个已登录的交互桌面
EXPLORER_Q = ("(Get-CimInstance Win32_Process -Filter \"Name='explorer.exe'\" | "
              "Measure-Object).Count")

DMR_Q = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*main.py*' } | "
         "ForEach-Object { $_.ProcessId }")


def log(msg: str) -> None:
    line = f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}'
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass
    print(line)


def running_pids() -> list:
    r = subprocess.run(['powershell', '-NoProfile', '-Command', DMR_Q],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=60)
    return [x for x in (r.stdout or '').split() if x.isdigit()]


def has_desktop_session() -> bool:
    """有没有人登录到桌面（有 explorer 进程就算）。"""
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', EXPLORER_Q],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=60)
        return (r.stdout or '').strip().isdigit() and int(r.stdout.strip()) > 0
    except Exception:
        return False


def launch() -> None:
    """Detached 启动，保证本脚本退出后 DMR 继续跑。"""
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen(
        ['cmd.exe', '/c', BAT],
        cwd=UP,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )


def main() -> int:
    try:
        pids = running_pids()
    except Exception as e:
        # 检测失败时保守跳过：漏启一次可以手点，双开会互相踩状态库。
        log(f'跳过启动：进程检测失败（{type(e).__name__}: {e}）')
        return 0

    if pids:
        log(f'跳过启动：已有 DMR 实例在运行（PID {", ".join(pids)}）。')
        return 0

    # ── 开机任务模式：优先等人登录 ────────────────────────────────────
    # 目的：把"可靠"和"看得见"同时拿到。
    #   · 自动登录正常（绝大多数情况）→ 20 秒内就有人登录 → 这里直接退出，
    #     由登录自启在**用户会话**里启动 DMR，桌面上能看到控制台窗口（老样子）。
    #   · 自动登录失效 / 没人登录 → 等满 N 秒后，在 session 0 起 DMR，录像不停。
    if BOOT_FALLBACK > 0:
        log(f'开机任务：先等 {BOOT_FALLBACK} 秒看有没有人登录（有人登录就交给登录自启，'
            f'这样能看到窗口）。')
        deadline = time.time() + BOOT_FALLBACK
        while time.time() < deadline:
            if running_pids():
                log('等待期间 DMR 已被登录自启拉起，本任务退出。')
                return 0
            if has_desktop_session():
                log(f'检测到已登录的桌面会话，等待登录自启先动手（最多 20 秒）…')
                for _ in range(20):
                    time.sleep(1)
                    if running_pids():
                        log('登录自启已把 DMR 拉起，本任务退出（DMR 在桌面上可见）。')
                        return 0
                log('登录自启 20 秒内没有拉起 DMR，由本任务兜底启动（session 0，无窗口）。')
                break
            time.sleep(5)
        else:
            log(f'等了 {BOOT_FALLBACK} 秒仍无人登录 —— 在后台启动 DMR，保证录像不停。')
        FOREGROUND_LOCAL = True
    else:
        FOREGROUND_LOCAL = FOREGROUND

    # 最后一道防双开：不管从哪条分支走到这里，都再确认一次
    if running_pids():
        log('启动前复查：DMR 已在运行，放弃本次启动。')
        return 0

    if FOREGROUND_LOCAL:
        log('前台启动 Start_Render.bat（任务在此阻塞，任务状态 = DMR 状态）')
        try:
            rc = subprocess.call(['cmd.exe', '/c', BAT], cwd=UP)
            log(f'Start_Render.bat 已退出，returncode={rc}；任务随之结束')
        except Exception as e:
            log(f'前台启动失败（{type(e).__name__}: {e}）')
            return 1
        return 0

    for attempt in range(1, RETRIES + 1):
        if DRY_RUN:
            log(f'[DRY-RUN] 第 {attempt} 次：将 detached 启动 {BAT}')
            return 0
        try:
            log(f'没有检测到 DMR，第 {attempt}/{RETRIES} 次启动 …')
            launch()
        except Exception as e:
            log(f'启动失败（{type(e).__name__}: {e}）')
            time.sleep(5)
            continue

        # 等它把 python 拉起来再复查；进程刚起时查不到是正常的
        for _ in range(WAIT_AFTER_LAUNCH):
            time.sleep(1)
            try:
                if running_pids():
                    log('启动成功，DMR 已在运行。')
                    return 0
            except Exception:
                continue
        log(f'第 {attempt} 次启动后 {WAIT_AFTER_LAUNCH} 秒仍未见进程。')

    log('三次尝试都没能把 DMR 拉起来 —— 请手动双击 Start_Render.bat 并检查日志。')
    return 1


if __name__ == '__main__':
    sys.exit(main())
