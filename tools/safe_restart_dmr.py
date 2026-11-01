"""安全重启 DMR：先确认没在录制，再优雅停止，最后用 bat 拉起。

⚠️ 2026-10-07 的教训：
    用 Stop-Process 直接杀掉 python，导致 streamgears 的 [正在录制] 文件
    没走完改名流程，留下 3 个孤儿分段（1.8 GB，后来抢救回来的）。
    所以重启前必须：
      1. 确认没有 streamgears 在录制（有就等，或明确接受损失）
      2. 尽量优雅停止（先给 DMR 主进程一个机会收尾）
"""
import os
import subprocess
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）


UP = _PROJECT_ROOT


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


SG_Q = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*streamgears_wrapper*' }")
DMR_Q = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*main.py*' }")
CMD_Q = ("Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
         "Where-Object { $_.CommandLine -like '*Start_Render*' }")

print('=' * 78)
print('1. 重启前安全检查')
print('=' * 78)
sg_pids = ps(SG_Q + " | ForEach-Object { $_.ProcessId }").split()
print(f'  录制进程（streamgears）: {len(sg_pids)} 个')
if sg_pids:
    print('  正在录制的任务:')
    for line in ps(SG_Q + " | ForEach-Object { $_.CommandLine }").split('\n'):
        import re
        m = re.search(r'-o\s+\./直播回放/(\S+)', line)
        if m:
            print(f'    {m.group(1)}')

# 找 [正在录制] 文件
part = []
for d in os.listdir(os.path.join(UP, '直播回放')):
    sub = os.path.join(UP, '直播回放', d)
    if not os.path.isdir(sub):
        continue
    for f in os.listdir(sub):
        if f.startswith('[正在录制]'):
            part.append((d, f, os.path.getsize(os.path.join(sub, f))))
print(f'\n  [正在录制] 文件: {len(part)} 个')
for d, f, sz in part:
    print(f'    {sz/1024/1024:>8.2f} MB  [{d}] {f[:60]}')

if sg_pids or part:
    print('\n  ⚠️ 检测到录制活动或中间文件！')
    print('     直接重启会留下孤儿分段（上次就是这样产生的）。')
    if '--force' not in sys.argv:
        print('\n     如果确认可以中断，加 --force 重跑。')
        sys.exit(1)
    print('     --force 已指定，继续。')

print()
print('=' * 78)
print('2. 停止守护进程（否则它会立刻拉起 DMR）')
print('=' * 78)
cmd_pids = ps(CMD_Q + " | ForEach-Object { $_.ProcessId }").split()
print(f'  守护 cmd: {cmd_pids or "无"}')
for pid in cmd_pids:
    ps(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue")
time.sleep(3)
print(f'  停止后: {ps(CMD_Q + " | ForEach-Object { $_.ProcessId }").split() or "✅ 已停"}')

print()
print('=' * 78)
print('3. 停止 DMR')
print('=' * 78)
dmr_pids = ps(DMR_Q + " | ForEach-Object { $_.ProcessId }").split()
print(f'  DMR: {dmr_pids or "无"}')
# 先尝试温和停止（Stop-Process 不带 -Force 会发关闭信号给有窗口的进程；
# python 控制台程序通常直接被杀，所以这里还是用 -Force，但顺序从子到父）
for pid in reversed(dmr_pids):
    ps(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue")
time.sleep(5)
left = ps(DMR_Q + " | ForEach-Object { $_.ProcessId }").split()
print(f'  停止后: {left or "✅ 已停"}')

print()
print('=' * 78)
print('4. 通过 Start_Render.bat 重新拉起（恢复守护 + 通知）')
print('=' * 78)
subprocess.Popen(['explorer.exe', os.path.join(UP, 'Start_Render.bat')],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print('  已发起，等待启动...')

for i in range(20):
    time.sleep(5)
    n_dmr = len(ps(DMR_Q + " | ForEach-Object { $_.ProcessId }").split())
    n_cmd = len(ps(CMD_Q + " | ForEach-Object { $_.ProcessId }").split())
    if n_dmr and n_cmd:
        print(f'    +{(i+1)*5}s  DMR={n_dmr} 个  守护={n_cmd} 个  ✅')
        break
    if i % 2 == 0:
        print(f'    +{(i+1)*5}s  DMR={n_dmr} 个  守护={n_cmd} 个')

print()
print('=' * 78)
print('5. 最终状态')
print('=' * 78)
print(f'  守护 cmd: {ps(CMD_Q + " | ForEach-Object { $_.ProcessId }").split() or "❌"}')
print(f'  DMR py  : {ps(DMR_Q + " | ForEach-Object { $_.ProcessId }").split() or "❌"}')
q = ps(DMR_Q + " | ForEach-Object { $_.CommandLine }")
print(f'  --quiet 生效: {"✅" if "--quiet" in q else "❌"}')
print(f'  CD2: {ps("(Get-Service CloudDrive2).Status.ToString()")}  '
      f'19798={ps("(Get-NetTCPConnection -LocalPort 19798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")}')

# 验证下播通知已去掉
print()
print('  验证下播通知已关闭:')
src = open(os.path.join(UP, 'DMR', 'Task', 'liveevents.py'), encoding='utf-8').read()
i = src.find("if kind == 'end':")
seg = src[i:i + 160] if i > 0 else ''
print('    ' + seg.replace('\n', '\n    ')[:300])
print(f'    {"✅ 下播直接 return" if "return" in seg else "⚠️ 需检查"}')
