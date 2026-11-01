"""实时看 DMR 在干什么 —— 用来替代"那个控制台窗口"。

为什么需要它
------------
开机任务在 session 0 运行时是没有窗口的；即使 DMR 跑在用户会话里，
RDP 断开后窗口也看不见。这个脚本提供一个"随log滚动 + 定期状态行"的窗口：
不用登录桌面、不用翻文件，双击就能看到程序还活着没、最近在录谁。

用法（双击桌面 `DMR-看实时日志.bat`）：
    .venv\\Scripts\\python.exe tools\\watch_log.py
    Ctrl+C 退出。
"""
import glob
import os
import subprocess
import sys
import time

UP = r'F:\DanmakuRepo'
LOGDIR = os.path.join(UP, 'logs')
TAIL_LINES = 40
STATUS_EVERY = 15

DMR_Q = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*main.py*' } | "
         "ForEach-Object { $_.ProcessId }")


def newest_log():
    files = glob.glob(os.path.join(LOGDIR, 'DMR-*.log'))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def dmr_pids():
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', DMR_Q],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=30)
        return [x for x in (r.stdout or '').split() if x.isdigit()]
    except Exception:
        return []


def tail_bytes(path: str, nbytes: int = 20000) -> tuple:
    """返回 (最后一段文本, 文件末尾偏移)。"""
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - nbytes))
        data = f.read()
    text = data.decode('utf-8', errors='replace')
    # 去掉可能被截断的第一行
    idx = text.find('\n')
    if idx >= 0:
        text = text[idx + 1:]
    return text, size


def main() -> int:
    print('=' * 78)
    print('DMR 实时日志   (Ctrl+C 退出)')
    print('=' * 78)
    pids = dmr_pids()
    print(f'当前 DMR: {"运行中 PID " + ", ".join(pids) if pids else "❌ 未运行"}')

    cur = None
    pos = 0
    last_status = 0.0

    while True:
        nf = newest_log()
        if nf is None:
            print('（还没找到日志文件，5 秒后重试）')
            time.sleep(5)
            continue

        if nf != cur:
            cur = nf
            text, pos = tail_bytes(cur)
            print()
            print(f'--- 跟随 {os.path.basename(cur)}（最近 {TAIL_LINES} 行起）---')
            lines = text.splitlines()[-TAIL_LINES:]
            for line in lines:
                print(line)

        try:
            with open(cur, 'rb') as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
            if chunk:
                sys.stdout.write(chunk.decode('utf-8', errors='replace'))
                sys.stdout.flush()
                last_status = 0.0      # 有新内容就尽快刷新状态行
        except OSError:
            pass

        now = time.time()
        if now - last_status >= STATUS_EVERY:
            last_status = now
            pids = dmr_pids()
            age = int(now - os.path.getmtime(cur)) if os.path.exists(cur) else -1
            state = ('运行中 PID ' + ','.join(pids)) if pids else '❌ 未运行'
            print()
            print(f'[状态 {time.strftime("%H:%M:%S")}] DMR {state}   '
                  f'日志 {age}s 前更新   {os.path.basename(cur)}')
            print()

        time.sleep(1)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n已退出监视（DMR 不受影响，它仍在后台运行）。')
