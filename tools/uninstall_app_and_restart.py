"""卸载 CD2 应用版 + 重启 DMR（让 --quiet 生效）。

顺序（重要）：
  1. 停 DMR（避免卸载过程中它有动作）
  2. 卸载应用版（MSI）
  3. 清理残留配置目录
  4. 确认服务版没事
  5. 重启 DMR（用 explorer.exe 拉起，避免成为本会话子进程）
  6. 验证

⚠️ 绝对不要碰 CloudDrive2（服务版）：
   C:\\Program Files\\CloudDrive2\\  +  服务名 CloudDrive2
"""
import os
import shutil
import subprocess
import time

UP = r'F:\DanmakuRender_AutoUp'
APP_DIR = r'C:\Program Files\CloudDrive'
APP_CFG = os.path.join(os.environ['LOCALAPPDATA'], 'CloudDrive.WinUI')
SVC_DIR = r'C:\Program Files\CloudDrive2'
SVC_NAME = 'CloudDrive2'
# MSI 产品码（来自注册表）
MSI_CODE = '{0DF12034-98D0-4E04-9232-07AAF0946A93}'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


def dmr_pids():
    out = ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*main.py*' } | "
             "ForEach-Object { $_.ProcessId }")
    return [int(x) for x in out.split() if x.strip().isdigit()]


print('=' * 78)
print('1. 停止 DMR')
print('=' * 78)
pids = dmr_pids()
print(f'  找到 DMR 进程: {pids}')
for p in pids:
    ps(f"Stop-Process -Id {p} -Force -ErrorAction SilentlyContinue")
time.sleep(3)
# 兜底：按命令行精确杀
ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
   "Where-Object { $_.CommandLine -like '*main.py*' } | "
   "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
time.sleep(5)
left = dmr_pids()
print(f'  剩余 DMR 进程: {left if left else "✅ 已全部停止"}')

# 顺便看 streamgears 子进程
sg = ps("(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*streamgears_wrapper*' } | "
        "Measure-Object).Count")
print(f'  streamgears 下载子进程: {sg} 个')

print()
print('=' * 78)
print('2. 卸载应用版（MSI 静默卸载）')
print('=' * 78)
print(f'  目标: CloudDrive 1.1.1.1  (MSI {MSI_CODE})')
print(f'  ⚠️ 不会碰 CloudDrive2（服务版）')
print()
r = subprocess.run(['msiexec.exe', '/X', MSI_CODE, '/quiet', '/norestart'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=900)
print(f'  msiexec exit={r.returncode}')
if r.stdout.strip():
    print(f'  输出: {r.stdout.strip()[:300]}')
if r.stderr.strip():
    print(f'  错误: {r.stderr.strip()[:300]}')

# 等卸载完成
for i in range(24):
    time.sleep(5)
    exists = os.path.exists(APP_DIR)
    reg = ps(f"if (Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{MSI_CODE}' "
             f"-ErrorAction SilentlyContinue) {{ 'yes' }} else {{ 'no' }}")
    if not exists and reg.strip() == 'no':
        print(f'  ✅ 卸载完成（{(i+1)*5} 秒）')
        break
    if i % 3 == 0:
        print(f'    +{(i+1)*5}s  目录存在={exists}  注册表={reg.strip()}')
else:
    print('  ⚠ 卸载可能没完成，检查一下')

print()
print('  卸载后状态:')
print(f'    程序目录存在: {os.path.exists(APP_DIR)}')
reg = ps(f"if (Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{MSI_CODE}' "
         f"-ErrorAction SilentlyContinue) {{ '还在' }} else {{ '✅ 已移除' }}")
print(f'    注册表条目: {reg.strip()}')

print()
print('=' * 78)
print('3. 清理残留配置目录')
print('=' * 78)
if os.path.isdir(APP_CFG):
    # 先备份（万一要回滚）
    bkdst = os.path.join(r'F:\_CD2配置备份_20261005',
                         '应用版配置_final_' + time.strftime('%Y%m%d-%H%M%S'))
    try:
        shutil.copytree(APP_CFG, bkdst)
        print(f'  已备份配置到 {bkdst}')
    except Exception as e:
        print(f'  备份失败（继续）: {e}')
    try:
        shutil.rmtree(APP_CFG, ignore_errors=True)
        time.sleep(2)
        print(f'  {"✅ 已删除" if not os.path.exists(APP_CFG) else "⚠ 还残留"} {APP_CFG}')
    except Exception as e:
        print(f'  删除失败: {e}')
else:
    print(f'  ✅ 配置目录本来就不存在')

# 残留目录检查
for d in (APP_DIR,):
    if os.path.exists(d):
        rest = []
        for root, dirs, files in os.walk(d):
            rest += files
        print(f'  ⚠ {d} 还有 {len(rest)} 个文件残留')

print()
print('=' * 78)
print('4. 确认服务版完好（关键！）')
print('=' * 78)
svc = ps(f"(Get-Service {SVC_NAME}).Status.ToString() + ' / ' + "
         f"(Get-Service {SVC_NAME}).StartType.ToString()")
print(f'  服务版状态: {svc}')
print(f'  服务版目录: {"✅ 存在" if os.path.exists(SVC_DIR) else "❌ 不见了！"}')
print(f'  19798 监听: {ps("(Get-NetTCPConnection -LocalPort 19798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")} 个')
print(f'  29798 监听: {ps("(Get-NetTCPConnection -LocalPort 29798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")} 个（应为 0）')
r = subprocess.run([r'C:\User Program Files\rclone-v1.75.1\rclone.exe',
                    'lsf', 'cd2:百度网盘/DMR录播', '--max-depth', '1'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=300)
print(f'  rclone 读云端: exit={r.returncode}  '
      f'{len([x for x in r.stdout.split(chr(10)) if x.strip()])} 个目录')

print()
print('=' * 78)
print('5. 重启 DMR（--quiet 生效）')
print('=' * 78)
print('  用 explorer.exe 拉起（避免成为本会话子进程，会话结束会被杀）')
subprocess.Popen(['explorer.exe', os.path.join(UP, 'Start_Render.bat')],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for i in range(18):
    time.sleep(5)
    p2 = dmr_pids()
    if p2:
        print(f'  ✅ DMR 已启动（{(i+1)*5} 秒）  进程: {p2}')
        break
    if i % 3 == 0:
        print(f'    +{(i+1)*5}s  等待中...')
else:
    print('  ⚠ DMR 好像没起来，检查一下')

time.sleep(10)
print()
print('  最终进程:')
print('    ' + (ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                  "Where-Object { $_.CommandLine -like '*main.py*' } | "
                  "ForEach-Object { 'PID ' + $_.ProcessId }").replace('\n', '\n    ') or '无'))

print()
print('  主进程的父进程（应该是 explorer.exe）：')
print(ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*main.py*' } | "
         "ForEach-Object { $pp = Get-CimInstance Win32_Process -Filter \"ProcessId=$($_.ParentProcessId)\" "
         "-ErrorAction SilentlyContinue; 'PID ' + $_.ProcessId + ' <- ' + $pp.Name }"))

print()
print('  验证 --quiet 生效（看新日志文件是否被创建 + 进程参数）:')
print('    ' + (ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                  "Where-Object { $_.CommandLine -like '*main.py*' } | "
                  "ForEach-Object { $_.CommandLine }").replace('\n', '\n    ') or '无'))
