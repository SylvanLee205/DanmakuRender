"""卸载应用版 + 重启 DMR 后的最终核查。"""
import glob
import json
import os
import shutil
import sqlite3
import subprocess
import time

RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
SVC_ROOT = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'
UP = r'F:\DanmakuRender_AutoUp'
TMP = os.environ['TEMP']


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 应用版是否彻底移除')
print('=' * 78)
APP_DIR = r'C:\Program Files\CloudDrive'
appcfg = os.path.join(os.environ['LOCALAPPDATA'], 'CloudDrive.WinUI')
print(f'  C:\\Program Files\\CloudDrive        : '
      f'{"⚠ 还在" if os.path.exists(APP_DIR) else "✅ 已删除"}')
print(f'  %LOCALAPPDATA%\\CloudDrive.WinUI     : '
      f'{"⚠ 还在" if os.path.exists(appcfg) else "✅ 已删除"}')
print(f'  HKCU Run 键 CloudDrive              : ' +
      (ps("(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' "
          "-ErrorAction SilentlyContinue).CloudDrive") or '✅ 已移除'))
for code in ('{0DF12034-98D0-4E04-9232-07AAF0946A93}',
             '{56DE8EB4-7DF2-4E04-BDF4-8033BAE562E5}'):
    r = ps(f"if (Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{code}' "
           f"-ErrorAction SilentlyContinue) {{ '还在' }} else {{ 'no' }}")
    print(f'  注册表 {code[:20]}…  : {"⚠ 还在" if r.strip() == "还在" else "✅ 已移除"}')
print(f'  29798 监听                          : '
      f'{ps("(Get-NetTCPConnection -LocalPort 29798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")} 个（应 0）')
APP_PROC_CMD = ("Get-CimInstance Win32_Process -Filter \"Name='clouddrive.exe'\" | "
                "Where-Object { $_.ExecutablePath -like '*Program Files\\CloudDrive\\*' } | "
                "ForEach-Object { $_.ProcessId }")
print(f'  应用版进程                          : ' + (ps(APP_PROC_CMD) or '✅ 无'))

print()
print('=' * 78)
print('2. 服务版是否完好（关键）')
print('=' * 78)
SVC_DIR = r'C:\Program Files\CloudDrive2'
print('  服务: ' + ps("(Get-Service CloudDrive2).Status.ToString() + ' / ' + "
                   "(Get-Service CloudDrive2).StartType.ToString()"))
print('  目录: ' + ('✅ 存在' if os.path.exists(SVC_DIR) else '❌ 不见了'))
print('  配置: ' + ('✅ 存在' if os.path.exists(SVC_ROOT) else '❌ 不见了'))
print(f'  19798 监听: {ps("(Get-NetTCPConnection -LocalPort 19798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")} 个')
print('  恢复配置:')
out = ps("sc.exe qfailure CloudDrive2")
for l in out.split('\n'):
    if 'RESTART' in l or 'RESET_PERIOD' in l:
        print(f'    {l.strip()}')
r = subprocess.run([RCLONE, 'lsf', 'cd2:百度网盘/DMR录播', '--max-depth', '1'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=300)
print(f'  rclone 读云端: exit={r.returncode}  '
      f'{len([x for x in r.stdout.split(chr(10)) if x.strip()])} 个目录')

print()
print('=' * 78)
print('3. DMR 状态')
print('=' * 78)
p = ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
       "Where-Object { $_.CommandLine -like '*main.py*' } | "
       "ForEach-Object { 'PID ' + $_.ProcessId + '  ' + $_.CommandLine }")
print(f'  进程: {len([x for x in p.split(chr(10)) if x.strip()])} 个')
for l in p.split('\n'):
    if l.strip():
        print(f'    {l.strip()}')
print(f'  --quiet 生效: {"✅ 是" if "--quiet" in p else "❌ 否"}')

# 日志文件
logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
              key=os.path.getmtime, reverse=True)
if logs:
    lg = logs[0]
    sz = os.path.getsize(lg)
    t = open(lg, encoding='utf-8', errors='replace').read()
    dbg = t.count('[debug]')
    inf = t.count('[info]')
    print(f'  最新日志: {os.path.basename(lg)}  ({sz} 字节)')
    print(f'     含 [debug] {dbg} 条、[info] {inf} 条'
          f'  -> {"✅ 日志文件保留全量" if dbg > 0 else "（还没产生 debug）"}')

print()
print('=' * 78)
print('4. 启动脚本最终内容')
print('=' * 78)
bt = os.path.join(UP, 'Start_Render.bat')
if os.path.exists(bt):
    for i, l in enumerate(open(bt, encoding='utf-8').read().splitlines(), 1):
        if 'curl' in l or 'python' in l or l.startswith('title'):
            print(f'  L{i}: {l}')

print()
print('=' * 78)
print('5. 审计（服务版口径 + 跳过规则识别）')
print('=' * 78)
r = subprocess.run([os.path.join(UP, '.venv', 'Scripts', 'python.exe'),
                    os.path.join(UP, 'tools', 'audit_cloud.py')],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=1800, cwd=UP)
for l in r.stdout.split('\n'):
    if any(k in l for k in ('合计', '清单来源', '跳过上传规则', '丢失')):
        print(f'  {l.strip()}')

print()
print('=' * 78)
print('6. 当前架构')
print('=' * 78)
print('  DMR (python main.py --quiet)')
print('    |- 录制抖音 -> 直播回放/<任务>/')
print('    |- ffmpeg 渲染弹幕 -> 直播回放/<任务>（弹幕版）/')
print('    `- rclone copy  -->  WebDAV http://localhost:19798/dav')
print('                          |')
print('                          `- CloudDrive2 服务版 (SYSTEM, 19798, 服务自愈)')
print('                               `- 百度网盘 /百度网盘/DMR录播/<任务>/')
print()
print('  远程访问: http://100.75.58.27:19798/  (Tailscale, 管理界面无认证)')
