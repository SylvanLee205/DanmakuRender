"""限速清理后的最终状态核查。"""
import json
import os
import subprocess

RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
NEW = os.path.join(os.environ['LOCALAPPDATA'], 'CloudDrive.WinUI')


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('最终状态核查')
print('=' * 78)

# 1. rclone 配置没被限速实验污染
print('\n[1] rclone 配置（确认没有 --bwlimit）')
rc = os.path.join(os.environ['APPDATA'], 'rclone', 'rclone.conf')
t = open(rc, encoding='utf-8', errors='replace').read()
print(f'    含 --bwlimit: {"⚠ 有" if "bwlimit" in t else "✅ 无"}')
import re
m = re.search(r'^\[cd2\](.*?)(?=^\[|\Z)', t, re.M | re.S)
for line in m.group(1).strip().split('\n'):
    if 'url' in line:
        print(f'    {line.strip()}')

# 2. DMR 的上传命令没被污染
print('\n[2] DMR 上传命令（global.yml）')
import yaml
g = yaml.safe_load(open(r'F:\DanmakuRender_AutoUp\configs\global.yml', encoding='utf-8'))
dv = (g.get('upload_args_task_default') or {}).get('dm_video') or []
for one in dv:
    cmd = one.get('command') or []
    print(f'    realtime = {one.get("realtime")}')
    print(f'    command  = {" ".join(str(c) for c in cmd)}')
    print(f'    含 bwlimit: {"⚠ 有" if any("bwlimit" in str(c) for c in cmd) else "✅ 无"}')

# 3. QoS 干净
print('\n[3] QoS 策略')
out = ps("Get-NetQosPolicy -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }")
print(f'    {"⚠ " + out if out else "✅ 无任何策略"}')

# 4. CD2 设置
print('\n[4] CD2 设置')
d = json.loads(open(os.path.join(NEW, 'systemsettings.json'),
                    encoding='utf-8', errors='replace').read())
print(f'    max_upload_speed_kbyps = {d.get("max_upload_speed_kbyps")}  (0=不限速)')
print(f'    file_log_level         = {d.get("file_log_level")}  (保留 Info)')
d2 = json.loads(open(os.path.join(NEW, 'cloudapidata.json'),
                     encoding='utf-8', errors='replace').read())
for a in (d2 if isinstance(d2, list) else [d2]):
    dc = a.get('downloader_config') or {}
    print(f'    [{a.get("dir_name")}] threads={dc.get("max_upload_threads")} '
          f'限速键={"有" if "max_upload_speed_kbyps" in dc else "已移除 ✓"}')

# 5. 旧服务
print('\n[5] 旧服务版')
out = ps("Get-Service CloudDrive2 | ForEach-Object { $_.Status.ToString() + ' / ' + $_.StartType.ToString() }")
print(f'    CloudDrive2: {out}')

# 6. 进程
print('\n[6] 运行中的 CD2')
print('    ' + (ps("Get-CimInstance Win32_Process -Filter \"Name='CloudDrive.exe' OR Name='clouddrive.exe'\" | "
                  "ForEach-Object { $_.Name + ' PID=' + $_.ProcessId }") or '无').replace('\n', '\n    '))

# 7. 云端连通性
print('\n[7] 云端连通性')
r = subprocess.run([RCLONE, 'lsf', 'cd2:百度网盘/DMR录播', '--max-depth', '1'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=300)
dirs = [x.strip() for x in r.stdout.split('\n') if x.strip()]
print(f'    DMR录播 下 {len(dirs)} 个目录  {"✅ 正常" if len(dirs) >= 13 else "⚠ 异常"}')

# 8. DMR 进程
print('\n[8] DMR 进程')
print('    ' + (ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                  "Where-Object { $_.CommandLine -like '*main.py*' } | "
                  "ForEach-Object { 'PID ' + $_.ProcessId }") or '未运行').replace('\n', '\n    '))
