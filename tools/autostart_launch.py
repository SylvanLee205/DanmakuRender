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

    if FOREGROUND:
        # 计划任务模式：阻塞在此，任务状态与 DMR 同生共死；退出码写日志。
        # 这样"任务在不在跑"和"程序在不在跑"是同一件事，不会出现
        # 任务显示就绪、程序其实早死了的假象。
        log('计划任务模式：前台启动 Start_Render.bat（任务在此阻塞）')
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
