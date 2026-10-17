"""对比两个 CD2 产品的 WebDAV 能力，为版本选择提供依据。"""
import json
import os
import subprocess

print('=' * 78)
print('1. 旧服务版 CloudDrive2 的 WebDAV 配置')
print('=' * 78)
old = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'
wb = os.path.join(old, 'webdav_config.json')
if os.path.exists(wb):
    d = json.loads(open(wb, encoding='utf-8', errors='replace').read())
    print(f'  {json.dumps(d, ensure_ascii=False, indent=2)}')
print()
cfg = os.path.join(old, 'config.toml')
if os.path.exists(cfg):
    print(f'  config.toml:')
    print('  ' + open(cfg, encoding='utf-8', errors='replace').read().replace('\n', '\n  '))

print()
print('=' * 78)
print('2. 新应用版 CloudDrive 的 WebDAV 配置')
print('=' * 78)
new = os.path.join(os.environ['LOCALAPPDATA'], 'CloudDrive.WinUI')
cfg2 = os.path.join(new, 'config.toml')
if os.path.exists(cfg2):
    print('  config.toml:')
    print('  ' + open(cfg2, encoding='utf-8', errors='replace').read().replace('\n', '\n  '))

print()
print('=' * 78)
print('3. 新应用支持哪些命令行参数')
print('=' * 78)
cli = r'C:\Program Files\CloudDrive\CloudDrive.exe'
for args in (['--help'], ['-h'], ['--version']):
    try:
        r = subprocess.run([cli] + args, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=15)
        out = ((r.stdout or '') + (r.stderr or '')).strip()
        print(f'  {cli} {" ".join(args)}  → exit={r.returncode}')
        if out:
            print('    ' + out[:600].replace('\n', '\n    '))
    except Exception as e:
        print(f'  {" ".join(args)} → {type(e).__name__}: {e}')

print()
print('=' * 78)
print('4. 两边的账号配置是否一致')
print('=' * 78)
for label, base in (('旧服务', old), ('新应用', new)):
    p = os.path.join(base, 'cloudapidata.json')
    if not os.path.exists(p):
        print(f'  【{label}】无配置')
        continue
    d = json.loads(open(p, encoding='utf-8', errors='replace').read())
    for a in (d if isinstance(d, list) else [d]):
        li = a.get('login_info') or {}
        dc = a.get('downloader_config') or {}
        print(f'  【{label}】name={li.get("name")} user={li.get("username")} '
              f'dir={a.get("dir_name")} sync={a.get("sync_to_cloud")} '
              f'up_threads={dc.get("max_upload_threads")}')

print()
print('=' * 78)
print('5. 各自的端口监听情况')
print('=' * 78)
r = subprocess.run(['powershell', '-NoProfile', '-Command',
                    "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
                    "Where-Object { $_.LocalPort -in 19798,29798 } | "
                    "ForEach-Object { $_.LocalAddress + ':' + $_.LocalPort + ' pid=' + $_.OwningProcess }"],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')
for l in r.stdout.split('\n'):
    if l.strip():
        print(f'  {l.strip()}')
print()
print('=' * 78)
print('6. 磁盘占用对比')
print('=' * 78)
for label, base in (('旧服务', old), ('新应用', new)):
    tot = 0
    for root, dirs, files in os.walk(base):
        for f in files:
            try:
                tot += os.path.getsize(os.path.join(root, f))
            except Exception:
                pass
    print(f'  【{label}】{tot/1024/1024:.1f} MB   ({base})')
