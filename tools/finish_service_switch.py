"""完成服务版切换收尾：
  1. 停掉应用版并禁用其开机自启
  2. 配置服务版"失败自动重启"
  3. 删除 CD2 看门狗（服务版自带自愈，看门狗只会去启动应用版）
  4. 清理闪窗相关的 VBS
  5. 最终验证
"""
import json
import os
import shutil
import sqlite3
import subprocess
import time

RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
RCLONE_CFG = os.path.join(os.environ['APPDATA'], 'rclone', 'rclone.conf')
SVC_NAME = 'CloudDrive2'
SVC_PORT = 19798
APP_EXE = r'C:\Program Files\CloudDrive\CloudDrive.exe'
SVC_ROOT = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'
UP = r'F:\DanmakuRender_AutoUp'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 停掉应用版')
print('=' * 78)
ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | "
   "Stop-Process -Force -ErrorAction SilentlyContinue")
time.sleep(5)
left = ps("(Get-Process CloudDrive -ErrorAction SilentlyContinue | Measure-Object).Count")
print(f'  clouddrive.exe 进程数: {left}  {"✅ 已停" if left == "0" else "⚠ 还在"}')

print()
print('=' * 78)
print('2. 关闭应用版开机自启（HKCU Run 键）')
print('=' * 78)
before = ps("(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' "
            "-ErrorAction SilentlyContinue).CloudDrive")
print(f'  改前: {before or "(无)"}')
if before:
    # 备份原值
    bkf = os.path.join(UP, '.temp', 'cd2_app_autostart_backup.txt')
    os.makedirs(os.path.dirname(bkf), exist_ok=True)
    with open(bkf, 'w', encoding='utf-8') as f:
        f.write(str(before))
    print(f'  原值已备份到 {bkf}')
    ps("Remove-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' "
       "-Name 'CloudDrive' -Force -ErrorAction SilentlyContinue")
    after = ps("(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' "
               "-ErrorAction SilentlyContinue).CloudDrive")
    print(f'  改后: {after or "✅ 已移除"}')
else:
    print('  ✅ 本来就没有')

print()
print('=' * 78)
print('3. 配置服务版"失败自动重启"')
print('=' * 78)
# sc.exe failure: reset= 天数, restart= 延迟(毫秒)
cmds = [
    f'sc.exe failure {SVC_NAME} reset= 86400 actions= restart/5000/restart/15000/restart/60000',
    f'sc.exe config {SVC_NAME} start= auto',
]
for c in cmds:
    r = subprocess.run(c.split(), capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=60)
    print(f'  {c.split()[1]} {c.split()[2]}: exit={r.returncode}  '
          f'{(r.stdout or r.stderr or "").strip()[:120]}')

print()
print('  验证恢复配置:')
out = ps(f"sc.exe qfailure {SVC_NAME}")
for l in out.split('\n'):
    if l.strip() and any(k in l for k in ('RESET', 'RESTART', 'FAILURE_ACTIONS', '命令')):
        print(f'    {l.strip()}')
if not any('RESTART' in l for l in out.split('\n')):
    for l in out.split('\n')[:12]:
        if l.strip():
            print(f'    {l.strip()}')

print()
print('=' * 78)
print('4. 删除 CD2 看门狗（服务版自带自愈，且它会去启动应用版）')
print('=' * 78)
out = ps("Get-ScheduledTask -TaskName 'DanmakuRender_CD2守护' -ErrorAction SilentlyContinue | "
         "ForEach-Object { $_.TaskName }")
if out.strip():
    # 先备份任务定义
    xml = ps("Export-ScheduledTask -TaskName 'DanmakuRender_CD2守护' -ErrorAction SilentlyContinue")
    bkx = os.path.join(UP, '.temp', 'cd2_watchdog_task_backup.xml')
    os.makedirs(os.path.dirname(bkx), exist_ok=True)
    with open(bkx, 'w', encoding='utf-8') as f:
        f.write(xml)
    print(f'  任务定义已备份到 {bkx}')
    ps("Unregister-ScheduledTask -TaskName 'DanmakuRender_CD2守护' -Confirm:$false")
    print('  ✅ 已删除')
else:
    print('  任务不存在')

# 清 VBS
vbs = os.path.join(UP, 'tools', 'run_watchdog_hidden.vbs')
if os.path.exists(vbs):
    os.remove(vbs)
    print('  ✅ 已删除静默启动器 run_watchdog_hidden.vbs（不再需要）')

print()
print('=' * 78)
print('5. 最终验证')
print('=' * 78)
svc = ps(f"(Get-Service {SVC_NAME}).Status.ToString() + ' / ' + "
         f"(Get-Service {SVC_NAME}).StartType.ToString()")
print(f'  服务版: {svc}')
print(f'  应用版进程: ' + (ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | "
                     "ForEach-Object { 'PID ' + $_.Id }") or '✅ 未运行'))


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


print(f'  服务版 WebDAV({SVC_PORT}): {webdav_ok(SVC_PORT)}')
print(f'  应用版 WebDAV(29798): {webdav_ok(29798)}')

cfg = open(RCLONE_CFG, encoding='utf-8').read()
url = [l.strip() for l in cfg.split('\n') if 'url' in l and 'localhost' in l]
print(f'  rclone 配置: {url}')

r = subprocess.run([RCLONE, 'lsf', 'cd2:百度网盘/DMR录播', '--max-depth', '1'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=300)
print(f'  rclone 读取云端: exit={r.returncode}  '
      f'{len([x for x in r.stdout.split(chr(10)) if x.strip()])} 个目录')

print()
print('=' * 78)
print('6. 服务版当前设置')
print('=' * 78)
for f in ('systemsettings.json', 'cloudapidata.json'):
    p = os.path.join(SVC_ROOT, f)
    if os.path.exists(p):
        try:
            d = json.loads(open(p, encoding='utf-8', errors='replace').read())
            print(f'  {f}: 可读')
            if f == 'systemsettings.json':
                for k in ('file_log_level', 'max_upload_speed_kbyps',
                          'upload_delay_secs', 'max_process_tasks'):
                    if k in d:
                        print(f'      {k} = {d[k]}')
        except Exception as e:
            print(f'  {f}: 解析失败 {e}')
    else:
        print(f'  {f}: 不存在')

print()
print('  服务版 config.toml:')
ct = os.path.join(SVC_ROOT, 'config.toml')
if os.path.exists(ct):
    for l in open(ct, encoding='utf-8', errors='replace').read().split('\n'):
        if l.strip() and not l.strip().startswith('#'):
            print(f'      {l.strip()}')

print()
print('=' * 78)
print('完成')
print('=' * 78)
print('  现在的架构:')
print(f'    DMR -> rclone -> 服务版 CD2({SVC_PORT}, SYSTEM账户, 服务自愈) -> 百度网盘')
print(f'    应用版已停用，开机自启已移除，看门狗已删除（不再需要）')
