"""清理无效的限速方案：QoS 策略 + CD2 的限速设置。

保留：CD2 file_log_level = Info（排查能力，与限速无关）
"""
import json
import os
import subprocess
import time

POLICY = 'DMR-CloudDrive-UploadLimit'
NEW = os.path.join(os.environ['LOCALAPPDATA'], 'CloudDrive.WinUI')
APP = r'C:\Program Files\CloudDrive\CloudDrive.exe'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 删除 QoS 策略')
print('=' * 78)
print('  删除前:')
out = ps(f"Get-NetQosPolicy -Name '{POLICY}' -ErrorAction SilentlyContinue | "
         "ForEach-Object { '  ' + $_.Name + '  ' + $_.AppPathNameMatchCondition }")
print(out or '  （不存在）')

ps(f"Remove-NetQosPolicy -Name '{POLICY}' -Confirm:$false -ErrorAction SilentlyContinue")
time.sleep(2)

print('  删除后:')
out = ps(f"Get-NetQosPolicy -Name '{POLICY}' -ErrorAction SilentlyContinue | "
         "ForEach-Object { $_.Name }")
print(f'  {"  " + out if out else "  ✅ 已删除（无同名策略）"}')

reg = f"HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\QoS\\{POLICY}"
out = ps(f"if (Test-Path '{reg}') {{ 'still exists' }} else {{ 'gone' }}")
print(f'  注册表: {"⚠ 还在" if "still" in out else "✅ 已清除"}')

print()
print('  全部 QoS 策略（确认系统干净）:')
out = ps("Get-NetQosPolicy -ErrorAction SilentlyContinue | "
         "ForEach-Object { '  ' + $_.Name }")
print(out or '  ✅ 没有任何 QoS 策略')

print()
print('=' * 78)
print('2. 清除 CD2 的限速设置（保留 file_log_level = Info）')
print('=' * 78)
p = os.path.join(NEW, 'systemsettings.json')
d = json.loads(open(p, encoding='utf-8', errors='replace').read())
old = d.get('max_upload_speed_kbyps')
d['max_upload_speed_kbyps'] = 0.0
with open(p, 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
print(f'  systemsettings.json: max_upload_speed_kbyps  {old} → 0.0（不限速）')
print(f'  file_log_level 保持: {d.get("file_log_level")}  ← 这个保留，是排查能力')

p2 = os.path.join(NEW, 'cloudapidata.json')
d2 = json.loads(open(p2, encoding='utf-8', errors='replace').read())
accounts = d2 if isinstance(d2, list) else [d2]
for a in accounts:
    dc = a.get('downloader_config')
    if isinstance(dc, dict) and 'max_upload_speed_kbyps' in dc:
        o = dc.pop('max_upload_speed_kbyps')
        print(f'  cloudapidata [{a.get("dir_name")}]: 移除 max_upload_speed_kbyps (原 {o})')
with open(p2, 'w', encoding='utf-8') as f:
    json.dump(d2, f, ensure_ascii=False, indent=2)

print()
print('=' * 78)
print('3. 重启 CD2 让清理生效')
print('=' * 78)
ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue")
time.sleep(8)
subprocess.Popen([APP, '--autostart'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(25)
print('  CD2: ' + (ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | "
                    "ForEach-Object { 'PID ' + $_.Id + ' 启动 ' + $_.StartTime.ToString('HH:mm:ss') }") or '未启动'))

print()
print('=' * 78)
print('4. 清理后确认')
print('=' * 78)
d = json.loads(open(p, encoding='utf-8', errors='replace').read())
print(f'  max_upload_speed_kbyps = {d.get("max_upload_speed_kbyps")}  (0 = 不限速 ✓)')
print(f'  file_log_level         = {d.get("file_log_level")}  (保留 Info)')
try:
    import urllib.request
    try:
        urllib.request.urlopen('http://127.0.0.1:29798/dav', timeout=8)
    except urllib.error.HTTPError as e:
        print(f'  WebDAV: HTTP {e.code} {"(401=正常)" if e.code == 401 else ""}')
except Exception as e:
    print(f'  WebDAV: {e}')
