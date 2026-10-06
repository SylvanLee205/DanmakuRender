"""切换到 CD2 核心服务版（clouddrive.exe，端口 19798）。

前提（已核实）：
  - 两个产品用同一个百度账号（1295761712）、同一目录（/百度网盘）
  - 服务版 config.toml: webdav_root = "/"，端口 19798
  - 服务版配置目录: C:\\Windows\\System32\\config\\systemprofile\\Waytech\\CloudDrive2\\
  - 服务版当前 Stopped / Disabled
  - 应用版 clouddrive.exe 端口 29798，当前在跑

用户偏好服务版的真实理由：
  - 跑在 Session 0（SYSTEM），**不弹控制台窗口**（解决闪窗问题）
  - Windows 服务自带"失败自动重启"（services.msc 可配）
  - 不依赖用户登录/桌面

步骤：
  1. 记录当前状态
  2. 停应用版（先不停，等确认服务版可用再停）
  3. 启动服务版，设为自动启动
  4. 检查 19798 端口和 WebDAV
  5. 【关键】测试服务版能否真的上传到百度（之前"服务版坏了"是端口配错导致的误判）
  6. 如果可用 → 改 rclone 指向 19798，停应用版
  7. 如果不可用 → 回滚，保持应用版
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
RCLONE_CFG = os.path.join(os.environ['APPDATA'], 'rclone', 'rclone.conf')
SVC_NAME = 'CloudDrive2'
SVC_PORT = 19798
APP_PORT = 29798
SVC_ROOT = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


def webdav_ok(port):
    import urllib.request
    import urllib.error
    try:
        urllib.request.urlopen(f'http://127.0.0.1:{port}/dav', timeout=8)
        return 'ok'
    except urllib.error.HTTPError as e:
        return f'HTTP {e.code}' + (' (401=正常)' if e.code == 401 else '')
    except Exception as e:
        return f'× {type(e).__name__}'


print('=' * 78)
print('步骤 0：记录当前状态')
print('=' * 78)
svc_state = ps(f"(Get-Service {SVC_NAME}).Status.ToString() + ' / ' + "
               f"(Get-Service {SVC_NAME}).StartType.ToString()")
print(f'  服务版: {svc_state}')
print(f'  应用版进程: ' + (ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | "
                     "ForEach-Object { 'PID ' + $_.Id }") or '未运行'))
print(f'  应用版 WebDAV({APP_PORT}): {webdav_ok(APP_PORT)}')
print(f'  服务版 WebDAV({SVC_PORT}): {webdav_ok(SVC_PORT)}')

# 备份 rclone 配置
bk = RCLONE_CFG + '.bak-before-svc-' + time.strftime('%Y%m%d-%H%M%S')
shutil.copy2(RCLONE_CFG, bk)
print(f'  rclone 配置已备份: {bk}')

print()
print('=' * 78)
print('步骤 1：启动服务版并设为自动启动')
print('=' * 78)
ps(f"Set-Service -Name {SVC_NAME} -StartupType Automatic")
ps(f"Start-Service -Name {SVC_NAME}")
for i in range(12):
    time.sleep(5)
    st = ps(f"(Get-Service {SVC_NAME}).Status.ToString()")
    dav = webdav_ok(SVC_PORT)
    print(f'    +{(i+1)*5:>3}s  服务={st}  WebDAV={dav}')
    if '401' in dav:
        break

print()
svc_state2 = ps(f"(Get-Service {SVC_NAME}).Status.ToString() + ' / ' + "
                f"(Get-Service {SVC_NAME}).StartType.ToString()")
print(f'  服务状态: {svc_state2}')

print()
print('=' * 78)
print('步骤 2：检查服务版能不能看到云端文件（WebDAV 通不通）')
print('=' * 78)
# 临时切 rclone 到服务版端口测
cfg = open(RCLONE_CFG, encoding='utf-8').read()
print(f'  当前 rclone 配置:')
for l in cfg.split('\n'):
    if l.strip() and ('[' in l or 'url' in l):
        print(f'    {l.strip()}')

# 用环境变量覆盖 url 测（不改配置文件）
r = subprocess.run([RCLONE, 'lsf', 'cd2:百度网盘/DMR录播', '--max-depth', '1',
                    '--rc', '--rc-no-auth'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=300)
print(f'\n  应用版({APP_PORT}) 读取测试: exit={r.returncode}  '
      f'{len([x for x in r.stdout.split(chr(10)) if x.strip()])} 个目录')

# 改配置到服务版端口
new_cfg = cfg.replace(f'localhost:{APP_PORT}', f'localhost:{SVC_PORT}')
open(RCLONE_CFG, 'w', encoding='utf-8').write(new_cfg)
print(f'\n  ✅ rclone 配置已改为 localhost:{SVC_PORT}')

r2 = subprocess.run([RCLONE, 'lsf', 'cd2:百度网盘/DMR录播', '--max-depth', '1'],
                    capture_output=True, text=True, encoding='utf-8',
                    errors='replace', timeout=300)
dirs = [x.strip() for x in r2.stdout.split('\n') if x.strip()]
print(f'  服务版({SVC_PORT}) 读取测试: exit={r2.returncode}  {len(dirs)} 个目录')
if r2.returncode != 0:
    print(f'    stderr: {(r2.stderr or "")[:300]}')
    print('\n  ❌ 服务版读不到云端 —— 回滚到应用版')
    open(RCLONE_CFG, 'w', encoding='utf-8').write(cfg)
    print(f'  已回滚 rclone 配置为 localhost:{APP_PORT}')
    sys.exit(1)
for d in dirs[:15]:
    print(f'    {d.rstrip("/")}')

print()
print('=' * 78)
print('步骤 3：★ 关键测试 —— 服务版能否真的上传到百度')
print('=' * 78)
print('  （之前认为"服务版上传线程坏了"是我把端口配错导致的误判，')
print('    现在两版都指向同一个账号和目录，要重新验证）')
print()

# 造 2MB 测试文件
testf = os.path.join(os.environ['TEMP'], 'svc_upload_test.bin')
with open(testf, 'wb') as f:
    f.write(os.urandom(2 * 1024 * 1024))
testname = 'svc_probe_' + time.strftime('%H%M%S') + '.bin'
dest = f'cd2:百度网盘/DMR录播/__svctest__/{testname}'
r3 = subprocess.run([RCLONE, 'copyto', testf, dest, '--retries', '1'],
                    capture_output=True, text=True, encoding='utf-8',
                    errors='replace', timeout=300)
print(f'  rclone copyto exit={r3.returncode}（本地回环总是 0，要看服务端）')
print(f'  等 60 秒让服务版异步上传...')
time.sleep(60)

# 查服务版缓存确认
def svc_cache_files():
    dst = os.path.join(os.environ['TEMP'], 'svccache')
    os.makedirs(dst, exist_ok=True)
    found = []
    for root, dirs, files in os.walk(SVC_ROOT):
        for f in files:
            if f.startswith('dir_cache.sqlite'):
                try:
                    shutil.copy2(os.path.join(root, f), os.path.join(dst, f))
                    found.append(os.path.join(root, f))
                except Exception:
                    pass
    out = set()
    p = os.path.join(dst, 'dir_cache.sqlite')
    if os.path.exists(p):
        try:
            con = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
            cur = con.cursor()
            cur.execute("SELECT id FROM cached_item WHERE path LIKE ?", ('%__svctest__%',))
            for (did,) in cur.fetchall():
                cur.execute('SELECT name FROM files WHERE parent_id=?', (did,))
                out |= set(r[0] for r in cur.fetchall())
            con.close()
        except Exception as e:
            return {f'err: {e}'}
    return out

print(f'  服务版缓存里找测试文件:')
cached = svc_cache_files()
print(f'    {cached if cached else "(空)"}')

# 再看服务版日志有没有 PermissionDenied
svc_logs = []
for root, dirs, files in os.walk(SVC_ROOT):
    for f in files:
        if f.endswith('.log'):
            svc_logs.append(os.path.join(root, f))
svc_logs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
if svc_logs:
    latest = svc_logs[0]
    print(f'  服务版最新日志: {latest}')
    t = open(latest, encoding='utf-8', errors='replace').read()
    hits = [l for l in t.split('\n') if testname in l or '__svctest__' in l]
    print(f'    含测试文件的行: {len(hits)}')
    for l in hits[-6:]:
        print(f'      {l[:170]}')

if testname in cached:
    print()
    print('  ✅✅ 服务版上传成功！可以切换。')
    svc_works = True
else:
    print()
    print('  ⚠ 缓存里没找到 —— 可能还在传，或上传失败。')
    print('     给它再多一点时间...')
    time.sleep(90)
    cached = svc_cache_files()
    svc_works = testname in cached
    print(f'     再查: {"✅ 找到了" if svc_works else "❌ 还是没有"}')

print()
print('=' * 78)
print('步骤 4：清理测试文件')
print('=' * 78)
subprocess.run([RCLONE, 'purge', 'cd2:百度网盘/DMR录播/__svctest__'],
               capture_output=True, text=True, encoding='utf-8',
               errors='replace', timeout=300)
try:
    os.remove(testf)
except Exception:
    pass
print('  已清理')

print()
print('=' * 78)
print('结论')
print('=' * 78)
if svc_works:
    print('  ✅ 服务版可用。保持 rclone 指向 19798。')
    print('  接下来要做：')
    print('    1. 停掉应用版（clouddrive.exe）')
    print('    2. 关闭应用版开机自启（HKCU Run 键）')
    print('    3. 配置服务版"失败自动重启"（services.msc > 恢复）')
    print('    4. 删除/停用 CD2 看门狗任务（服务版不需要，且它会去启动应用版）')
else:
    print('  ❌ 服务版上传不行。回滚 rclone 到应用版端口。')
    open(RCLONE_CFG, 'w', encoding='utf-8').write(cfg)
    print(f'  已回滚为 localhost:{APP_PORT}')
