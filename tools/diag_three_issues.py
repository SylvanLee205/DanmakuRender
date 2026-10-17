"""诊断三个问题：DMR 是否卡死、HTTPS 19799 为什么没反应、WebDAV 状况。"""
import glob
import os
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('【问题1】DMR 是不是真卡死了')
print('=' * 78)
p = ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
       "Where-Object { $_.CommandLine -like '*main.py*' } | "
       "ForEach-Object { $_.ProcessId }")
print(f'  DMR 进程: {p or "❌ 不存在（真的挂了）"}')
print()
if p:
    info = ps("Get-Process python -ErrorAction SilentlyContinue | "
              "Select-Object Id,@{n='CPU秒';e={[math]::Round($_.CPU,1)}},"
              "@{n='内存MB';e={[math]::Round($_.WorkingSet64/1MB,1)}},"
              "@{n='线程';e={$_.Threads.Count}},Responding | Format-Table -AutoSize | Out-String")
    print(info)

# 日志是否还在增长
logs = sorted(glob.glob(r'F:\DanmakuRender_AutoUp\logs\DMR-2026*.log'),
              key=os.path.getmtime, reverse=True)
print('  最近日志文件:')
for lg in logs[:3]:
    mt = time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(lg)))
    print(f'    {os.path.basename(lg)}  {os.path.getsize(lg):>9} 字节  改于 {mt}')

if logs:
    lg = logs[0]
    sz1 = os.path.getsize(lg)
    print(f'\n  观察 {os.path.basename(lg)} 是否在写入（等 30 秒）...')
    time.sleep(30)
    sz2 = os.path.getsize(lg)
    print(f'    30 秒前 {sz1} 字节 -> 现在 {sz2} 字节  差 {sz2 - sz1}')
    print(f'    {"✅ 日志在增长，程序活着" if sz2 > sz1 else "⚠ 日志没变（可能只是没事件）"}')
    txt = open(lg, encoding='utf-8', errors='replace').read()
    lines = [l for l in txt.split('\n') if l.strip()]
    print(f'\n  日志尾部 12 行:')
    for l in lines[-12:]:
        print(f'    {l[:165]}')

print()
print('=' * 78)
print('【问题2】HTTPS 19799 为什么没反应')
print('=' * 78)
print(f'  19798 监听: {ps("(Get-NetTCPConnection -LocalPort 19798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")}')
print(f'  19799 监听: {ps("(Get-NetTCPConnection -LocalPort 19799 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")}')
print('  监听地址明细:')
print(ps("Get-NetTCPConnection -LocalPort 19798,19799 -State Listen -ErrorAction SilentlyContinue | "
         "ForEach-Object { '    ' + $_.LocalAddress + ':' + $_.LocalPort + '  PID ' + $_.OwningProcess }"))


def probe(url, use_ssl=False, timeout=10):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=ctx if use_ssl else None) as r:
            return f'HTTP {r.status}  {len(r.read())} 字节'
    except urllib.error.HTTPError as e:
        return f'HTTP {e.code}'
    except Exception as e:
        return f'× {type(e).__name__}: {str(e)[:70]}'


tsip = ps("& 'C:\\Program Files\\Tailscale\\tailscale.exe' ip -4 2>$null | Select-Object -First 1")
tsip = tsip.strip().split('\n')[0].strip() if tsip else ''
print(f'\n  Tailscale IP: {tsip}')
print('  本机自测:')
print(f'    http  //127.0.0.1:19798/  -> {probe("http://127.0.0.1:19798/")}')
print(f'    https //127.0.0.1:19799/  -> {probe("https://127.0.0.1:19799/", True)}')
if tsip:
    print(f'    http  //{tsip}:19798/  -> {probe(f"http://{tsip}:19798/")}')
    print(f'    https //{tsip}:19799/  -> {probe(f"https://{tsip}:19799/", True)}')

print()
print('  证书与 TLS 详情:')
try:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection(('127.0.0.1', 19799), timeout=8) as sock:
        with ctx.wrap_socket(sock, server_hostname='127.0.0.1') as ssock:
            cert = ssock.getpeercert()
            print(f'    TLS 版本: {ssock.version()}')
            print(f'    加密套件: {ssock.cipher()[0]}')
            print(f'    证书主题: {cert.get("subject")}')
            print(f'    证书颁发: {cert.get("issuer")}')
            print(f'    有效期至: {cert.get("notAfter")}')
except Exception as e:
    print(f'    × {type(e).__name__}: {e}')

print()
print('=' * 78)
print('【问题3】WebDAV 状况')
print('=' * 78)
RC = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
cfg = os.path.join(os.environ['APPDATA'], 'rclone', 'rclone.conf')
print('  rclone 配置:')
txt = open(cfg, encoding='utf-8').read()
import re
m = re.search(r'^\[cd2\](.*?)(?=^\[|\Z)', txt, re.M | re.S)
for l in (m.group(1) if m else '').split('\n'):
    if l.strip() and 'pass' not in l.lower():
        print(f'    {l.strip()}')
r = subprocess.run([RC, 'lsf', 'cd2:百度网盘/DMR录播', '--max-depth', '1'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=300)
print(f'\n  rclone lsf: exit={r.returncode}  '
      f'{len([x for x in r.stdout.split(chr(10)) if x.strip()])} 个目录')
if r.returncode != 0:
    print(f'    错误: {(r.stderr or "")[:400]}')

# 队列
import shutil
import sqlite3
SVC = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'
dst = os.path.join(os.environ['TEMP'], 'diag_q')
os.makedirs(dst, exist_ok=True)
for s in ('', '-wal', '-shm'):
    src = os.path.join(SVC, 'clouddrive_data.sqlite' + s)
    if os.path.exists(src):
        try:
            shutil.copy2(src, os.path.join(dst, 'clouddrive_data.sqlite' + s))
        except Exception:
            pass
try:
    con = sqlite3.connect(f'file:{os.path.join(dst, "clouddrive_data.sqlite")}?mode=ro', uri=True)
    cur = con.cursor()
    cur.execute('SELECT filename, size FROM transfer_tasks')
    rows = cur.fetchall()
    print(f'\n  CD2 队列: {len(rows)} 条')
    for f, s in rows:
        print(f'    {f}  ({s} 字节)')
    con.close()
except Exception as e:
    print(f'  队列查询失败: {e}')

print()
print('  服务版日志尾部:')
lgd = os.path.join(SVC, 'log')
today = time.strftime('%Y-%m-%d') + '.log'
fp = os.path.join(lgd, today)
if os.path.exists(fp):
    lines = open(fp, encoding='utf-8', errors='replace').read().split('\n')
    for l in lines[-12:]:
        if l.strip():
            print(f'    {l[:170]}')
