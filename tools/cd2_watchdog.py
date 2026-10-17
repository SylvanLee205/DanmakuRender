"""CD2 守护脚本：检查 CloudDrive 是否在运行，挂了就拉起并记录。

背景（2026-10-05 实例）：
    CD2 在 20:34~22:24 之间挂掉（进程消失），之后 2 小时的上传全部失败
    （rclone 报 connection refused）。没人发现、没人拉起，
    DMR 重试 3 次后放弃并写入 failed_uploads.json。

这个脚本由计划任务每 5 分钟调用一次，做三件事：
    1. 检查 CloudDrive.exe 是否在跑
    2. 检查 29798 端口是否在监听（进程在但端口没起 = 半死状态）
    3. 不在/半死 → 拉起它，并把事件写进日志

退出码：0=正常无需处理，1=做了拉起动作，2=脚本自身出错
"""
import json
import os
import subprocess
import sys
import time

APP = r'C:\Program Files\CloudDrive\CloudDrive.exe'
PORT = 29798
ROOT = r'F:\DanmakuRender_AutoUp'
LOGFILE = os.path.join(ROOT, 'logs', 'cd2_watchdog.log')
STATE = os.path.join(ROOT, '.temp', 'cd2_watchdog_state.json')


def log(msg):
    line = f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}'
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOGFILE), exist_ok=True)
        with open(LOGFILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


def proc_running():
    out = ps("(Get-Process CloudDrive -ErrorAction SilentlyContinue | Measure-Object).Count")
    try:
        return int(out.strip()) > 0
    except Exception:
        return False


def port_listening():
    out = ps(f"(Get-NetTCPConnection -LocalPort {PORT} -State Listen "
             f"-ErrorAction SilentlyContinue | Measure-Object).Count")
    try:
        return int(out.strip()) > 0
    except Exception:
        return False


def webdav_ok():
    """真正问一次 WebDAV，确认不是"端口开着但不干活"。"""
    import urllib.request
    import urllib.error
    try:
        urllib.request.urlopen(f'http://127.0.0.1:{PORT}/dav', timeout=8)
        return True
    except urllib.error.HTTPError as e:
        return e.code == 401          # 401 = 服务正常，只是需要认证
    except Exception:
        return False


def start_app():
    log('正在拉起 CloudDrive...')
    try:
        subprocess.Popen([APP, '--autostart'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0))
    except Exception as e:
        log(f'拉起失败: {type(e).__name__}: {e}')
        return False
    # 等它就绪（最多 60 秒）
    for i in range(12):
        time.sleep(5)
        if webdav_ok():
            log(f'CD2 已就绪（等待 {(i+1)*5} 秒）')
            return True
    log('CD2 拉起后 60 秒内仍未就绪，请人工检查')
    return False


def main():
    procs = proc_running()
    port = port_listening()
    web = webdav_ok() if port else False

    if procs and web:
        # 正常，静默退出（避免日志刷屏）
        return 0

    # 异常状态，记录并处理
    log(f'检测到异常: 进程={procs}  端口={port}  WebDAV={web}')

    if procs and not web:
        # 进程在但服务不干活 —— 半死状态，先杀掉再拉起
        log('进程在但 WebDAV 无响应（半死状态），先结束再重启')
        ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | Stop-Process -Force "
           "-ErrorAction SilentlyContinue")
        time.sleep(8)

    ok = start_app()

    # 记录状态供统计
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        d = {}
        if os.path.exists(STATE):
            try:
                d = json.load(open(STATE, encoding='utf-8'))
            except Exception:
                d = {}
        d.setdefault('restarts', [])
        d['restarts'].append({'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                              'proc': procs, 'port': port, 'ok': ok})
        d['restarts'] = d['restarts'][-50:]      # 只留最近 50 次
        d['last_check'] = time.strftime('%Y-%m-%d %H:%M:%S')
        json.dump(d, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    except Exception:
        pass

    return 1 if ok else 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        log(f'脚本异常: {type(e).__name__}: {e}')
        sys.exit(2)
