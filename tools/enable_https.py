"""启用服务版 CD2 的 HTTPS（附加式，不破坏现有 HTTP）。

配置：
  http_port = 19798   (保持)
  https_port = 19799  (新增启用)
  enable_https = false -> true
  证书: 自签名，2026-10-01 生成，2027-10-01 到期

为什么加 HTTPS：
  1. Tailscale 本身已加密（WireGuard），但到 CD2 这一段是明文 HTTP
  2. 浏览器会标记"不安全"，且部分浏览器 API 要求安全上下文
  3. 附加式改动 —— HTTP 仍然可用，不会把自己锁在外面

⚠️ 自签名证书浏览器会警告"不受信任"。
   - 手机/tailscale 访问：点"继续访问"即可，或用 tailscale 的 MagicDNS + 证书
   - 想消除警告需要受信任证书（Tailscale 可以签发，但那是另一件事）
"""
import json
import os
import shutil
import subprocess
import time

SVC_ROOT = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'
CFG = os.path.join(SVC_ROOT, 'config.toml')
SVC = 'CloudDrive2'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 改前状态')
print('=' * 78)
_ps_cmd = (f'Select-String -Path "{CFG}" -Pattern "enable_https" | '
           f'ForEach-Object {{ $_.Line.Trim() }}')
print(f'  enable_https: {ps(_ps_cmd)}')
print(f'  19799 监听: {ps("(Get-NetTCPConnection -LocalPort 19799 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")}')

print()
print('=' * 78)
print('2. 备份配置')
print('=' * 78)
bk = CFG + '.bak-' + time.strftime('%Y%m%d-%H%M%S')
shutil.copy2(CFG, bk)
print(f'  已备份: {bk}')

print()
print('=' * 78)
print('3. 改 enable_https = false -> true')
print('=' * 78)
# ⚠️ config.toml 里 [[mount_points]] 的 name 是 GBK 乱码显示，
# 但文件本身大概率是 UTF-8。用二进制读+精确定位替换，避免整体重写破坏编码。
raw = open(CFG, 'rb').read()
old = b'enable_https = false'
new = b'enable_https = true'
if old not in raw:
    print('  ⚠ 找不到 "enable_https = false"，检查当前值：')
    for line in raw.split(b'\n'):
        if b'enable_https' in line:
            print(f'    {line!r}')
    raise SystemExit(1)
raw2 = raw.replace(old, new, 1)
open(CFG, 'wb').write(raw2)
print('  ✅ 已改为 enable_https = true')

# 校验
chk = open(CFG, 'rb').read()
print(f'  校验: enable_https = true 出现 {chk.count(b"enable_https = true")} 次, '
      f'false 出现 {chk.count(b"enable_https = false")} 次')

print()
print('=' * 78)
print('4. 重启服务生效')
print('=' * 78)
ps(f"Restart-Service {SVC} -Force")
for i in range(15):
    time.sleep(5)
    st = ps(f"(Get-Service {SVC}).Status.ToString()")
    n98 = ps("(Get-NetTCPConnection -LocalPort 19798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")
    n99 = ps("(Get-NetTCPConnection -LocalPort 19799 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")
    print(f'    +{(i+1)*5:>3}s  服务={st}  19798={n98}  19799={n99}')
    if st == 'Running' and n99 not in ('', '0'):
        break

print()
print('=' * 78)
print('5. 验证 HTTP 和 HTTPS 都可用')
print('=' * 78)
import ssl
import urllib.request
import urllib.error

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE      # 自签名证书


def probe(url, use_ssl=False):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10,
                                    context=ctx if use_ssl else None) as r:
            body = r.read()
            return f'HTTP {r.status}  {len(body)} 字节'
    except urllib.error.HTTPError as e:
        return f'HTTP {e.code}' + (' (401=正常需认证)' if e.code == 401 else '')
    except Exception as e:
        return f'× {type(e).__name__}: {str(e)[:60]}'


print(f'  http://127.0.0.1:19798/   -> {probe("http://127.0.0.1:19798/")}')
print(f'  https://127.0.0.1:19799/  -> {probe("https://127.0.0.1:19799/", True)}')
print(f'  http://127.0.0.1:19798/dav  -> {probe("http://127.0.0.1:19798/dav")}')
print(f'  https://127.0.0.1:19799/dav -> {probe("https://127.0.0.1:19799/dav", True)}')

# Tailscale IP
tsip = ps("& 'C:\\Program Files\\Tailscale\\tailscale.exe' ip -4 2>$null | Select-Object -First 1")
tsip = tsip.strip().split('\n')[0].strip() if tsip else ''
if tsip and tsip[0].isdigit():
    print(f'  https://{tsip}:19799/  -> {probe(f"https://{tsip}:19799/", True)}')
    print(f'  （手机用这个地址: https://{tsip}:19799/）')

print()
print('=' * 78)
print('6. rclone（走 127.0.0.1:19798 HTTP，不受影响）')
print('=' * 78)
r = subprocess.run([r'C:\User Program Files\rclone-v1.75.1\rclone.exe',
                    'lsf', 'cd2:百度网盘/DMR录播', '--max-depth', '1'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=300)
print(f'  exit={r.returncode}  '
      f'{len([x for x in r.stdout.split(chr(10)) if x.strip()])} 个目录')
if r.returncode != 0:
    print(f'  ⚠ {(r.stderr or "")[:200]}')
    print('  回滚: 把 enable_https 改回 false 并重启服务')

print()
print('=' * 78)
print('7. 证书信息')
print('=' * 78)
_crt = os.path.join(SVC_ROOT, 'certs', 'server.crt')
_cert_cmd = (f"& certutil -dump '{_crt}' 2>&1 | "
             f"Select-String -Pattern 'Subject:|Issuer:|NotAfter' | "
             f"Select-Object -First 4 | ForEach-Object {{ '  ' + $_.Line.Trim() }}")
print(ps(_cert_cmd))
