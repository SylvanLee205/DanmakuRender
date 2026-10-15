"""彻底清理重复的 streamgears 进程 + 让孤儿分段被正确恢复。

问题复盘（我的重启方式有缺陷）：
    我只 Stop-Process 了 main.py 的 python 进程，但 streamgears_wrapper
    是它们的**子进程**，没被一起杀掉。结果：
      · 老 streamgears 继续写 [正在录制]xxx.flv.part
      · 新 DMR 又起了一对新的 streamgears
      · 同一个主播有两对进程在录同一个流 → 孤儿分段

正确做法：
    1. 停守护（防止它拉起新的）
    2. 停 DMR 主进程
    3. **停所有 streamgears_wrapper 子进程**   <- 之前漏了这步
    4. 等孤儿 .part 沉淀（> 2 分钟，让 DMR 的恢复阈值能识别）
    5. 重新启动 → DMR 的 recover_part 会把孤儿 .part 改名成正式分段落库
"""
import os
import subprocess
import sys
import time

UP = r'F:\DanmakuRender_AutoUp'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


CMD_Q = ("Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
         "Where-Object { $_.CommandLine -like '*Start_Render*' } | "
         "ForEach-Object { $_.ProcessId }")
DMR_Q = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*main.py*' } | "
         "ForEach-Object { $_.ProcessId }")
SG_Q = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*streamgears_wrapper*' } | "
        "ForEach-Object { $_.ProcessId }")

print('=' * 78)
print('1. 停止前状态')
print('=' * 78)
print(f'  守护 cmd        : {ps(CMD_Q).split()}')
print(f'  DMR main.py     : {ps(DMR_Q).split()}')
print(f'  streamgears 子进程: {ps(SG_Q).split()}')

print()
print('=' * 78)
print('2. 按顺序彻底停止（含 streamgears —— 关键）')
print('=' * 78)
for pid in ps(CMD_Q).split():
    ps(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue")
    print(f'  停守护 {pid}')
time.sleep(2)
for pid in reversed(ps(DMR_Q).split()):
    ps(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue")
    print(f'  停 DMR {pid}')
time.sleep(3)
sg = ps(SG_Q).split()
for pid in sg:
    ps(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue")
    print(f'  停 streamgears {pid}')
time.sleep(3)

left_sg = ps(SG_Q).split()
left_dmr = ps(DMR_Q).split()
left_cmd = ps(CMD_Q).split()
print()
print(f'  停止后 -> 守护={left_cmd or "✅"}  DMR={left_dmr or "✅"}  '
      f'streamgears={left_sg or "✅"}')

print()
print('=' * 78)
print('3. 列出 [正在录制] 孤儿文件')
print('=' * 78)
parts = []
base = os.path.join(UP, '直播回放')
for root, dirs, files in os.walk(base):
    for f in files:
        if f.startswith('[正在录制]'):
            p = os.path.join(root, f)
            parts.append((p, os.path.getsize(p), os.path.getmtime(p),
                          os.path.basename(root)))
for p, sz, mt, task in sorted(parts, key=lambda x: -x[1]):
    age = (time.time() - mt) / 60
    print(f'  {sz/1024/1024:>8.1f} MB  {age:>5.1f}分钟前  [{task}] '
          f'{os.path.basename(p)[:65]}')

print()
print('=' * 78)
print('4. 等 150 秒让孤儿 .part 沉淀（DMR 恢复阈值是 2 分钟）')
print('=' * 78)
for i in range(5):
    time.sleep(30)
    n = sum(1 for r, d, fs in os.walk(base) for f in fs
            if f.startswith('[正在录制]') and f.endswith('.part'))
    print(f'    +{(i+1)*30}s  剩余 .part: {n} 个')

print()
print('=' * 78)
print('5. 重新启动 DMR（它的 recover_part 会接管孤儿 .part）')
print('=' * 78)
subprocess.Popen(['explorer.exe', os.path.join(UP, 'Start_Render.bat')],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for i in range(24):
    time.sleep(5)
    nd, nc = len(ps(DMR_Q).split()), len(ps(CMD_Q).split())
    if nd and nc:
        print(f'    +{(i+1)*5}s  DMR={nd} 守护={nc}')
        break
    if i % 2 == 0:
        print(f'    +{(i+1)*5}s  DMR={nd} 守护={nc}')

print()
print('=' * 78)
print('6. 恢复结果')
print('=' * 78)
print(f'  守护={ps(CMD_Q).split() or "❌"}  DMR={ps(DMR_Q).split() or "❌"}')
print(f'  streamgears={ps(SG_Q).split() or "（无）"}')
print()
left = []
for root, dirs, files in os.walk(base):
    for f in files:
        if f.startswith('[正在录制]'):
            left.append((os.path.join(root, f), os.path.getsize(
                os.path.join(root, f)), os.path.basename(root)))
print(f'  剩余 [正在录制] 文件: {len(left)} 个')
for p, sz, task in sorted(left, key=lambda x: -x[1]):
    print(f'    {sz/1024/1024:>8.1f} MB  [{task}] {os.path.basename(p)[:65]}')

# 日志里的恢复记录
lg = None
import glob
logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
              key=os.path.getmtime, reverse=True)
if logs:
    lg = logs[0]
    print()
    print(f'  日志 {os.path.basename(lg)} 里的恢复记录:')
    txt = open(lg, encoding='utf-8', errors='replace').read()
    for l in txt.split('\n')[-120:]:
        if '[恢复]' in l or '恢复阶段完成' in l:
            print(f'    {l.strip()[:150]}')
