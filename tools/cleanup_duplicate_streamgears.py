"""彻底清理重复的 streamgears / ffmpeg 录制进程 + 让孤儿分段被正确恢复。

问题复盘（最初的重启方式有缺陷）：
    只 Stop-Process 了 main.py 的 python 进程，但 streamgears_wrapper
    是它们的**子进程**，没被一起杀掉。结果：
      · 老 streamgears 继续写 [正在录制]xxx.flv.part
      · 新 DMR 又起了一对新的 streamgears
      · 同一个主播有两对进程在录同一个流 → 孤儿分段

正确做法：
    1. 停守护（防止它拉起新的）
    2. 停 DMR 主进程
    3. **停所有 streamgears_wrapper 子进程**   <- 最初漏了这步
    4. **停所有录制用的 ffmpeg**（判据是命令行含 -segment_time）<- 2026-10-19 补上
    5. 等孤儿文件沉淀（> 2 分钟，让 DMR 的恢复阈值能识别）
    6. 重新启动 → DMR 的 recover_ffmpeg_segments / recover_part 接手孤儿分段

⚠️ 2026-10-19 修复：本文件曾被一次提交**误删为只剩几个查询字符串**（145 行 → 46 行），
   运行时静默返回 0、什么都不做 —— 比报错更危险。现已恢复完整流程，
   并在结尾用退出码表达"是否真的重启成功"。

用法：
    .venv\\Scripts\\python.exe tools\\cleanup_duplicate_streamgears.py
    .venv\\Scripts\\python.exe tools\\cleanup_duplicate_streamgears.py --dry-run
"""
import glob
import os
import subprocess
import sys
import time

UP = r'F:\DanmakuRender_AutoUp'
DRY_RUN = '--dry-run' in sys.argv


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


def pids(query):
    return [x for x in ps(query).split() if x.isdigit()]


CMD_Q = ("Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
         "Where-Object { $_.CommandLine -like '*Start_Render*' } | "
         "ForEach-Object { $_.ProcessId }")
DMR_Q = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*main.py*' } | "
         "ForEach-Object { $_.ProcessId }")
SG_Q = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*streamgears_wrapper*' } | "
        "ForEach-Object { $_.ProcessId }")
# 录制用的 ffmpeg：只有 DMR 录制命令带 -segment_time（批量转码没有）。
# ⚠️ 不要用中文路径做判据：中文经 Python -> powershell -Command 传递会乱码。
FF_Q = ("Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe'\" | "
        "Where-Object { $_.CommandLine -like '*-segment_time*' } | "
        "ForEach-Object { $_.ProcessId }")

if DRY_RUN:
    print('=' * 78)
    print('DRY-RUN：只查看，不做任何停止/启动')
    print('=' * 78)
    print(f'  守护 cmd          : {pids(CMD_Q)}')
    print(f'  DMR main.py       : {pids(DMR_Q)}')
    print(f'  streamgears 子进程: {pids(SG_Q)}')
    print(f'  录制 ffmpeg       : {pids(FF_Q)}')
    raise SystemExit(0)

print('=' * 78)
print('1. 停止前状态')
print('=' * 78)
print(f'  守护 cmd          : {pids(CMD_Q)}')
print(f'  DMR main.py       : {pids(DMR_Q)}')
print(f'  streamgears 子进程: {pids(SG_Q)}')
print(f'  录制 ffmpeg       : {pids(FF_Q)}')

print()
print('=' * 78)
print('2. 按顺序彻底停止（守护 → DMR → streamgears → ffmpeg）')
print('=' * 78)
for pid in pids(CMD_Q):
    ps(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue")
    print(f'  停守护 {pid}')
time.sleep(2)
for pid in reversed(pids(DMR_Q)):
    ps(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue")
    print(f'  停 DMR {pid}')
time.sleep(3)
for pid in pids(SG_Q):
    ps(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue")
    print(f'  停 streamgears {pid}')
for pid in pids(FF_Q):
    ps(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue")
    print(f'  停录制 ffmpeg {pid}')
time.sleep(3)

print()
print(f'  停止后 -> 守护={pids(CMD_Q) or "✅"}  DMR={pids(DMR_Q) or "✅"}  '
      f'streamgears={pids(SG_Q) or "✅"}  ffmpeg={pids(FF_Q) or "✅"}')

print()
print('=' * 78)
print('3. 列出 [正在录制] 孤儿文件')
print('=' * 78)
base = os.path.join(UP, '直播回放')
parts = []
for root, dirs, files in os.walk(base):
    for f in files:
        if f.startswith('[正在录制]'):
            p = os.path.join(root, f)
            try:
                parts.append((p, os.path.getsize(p), os.path.getmtime(p),
                              os.path.basename(root)))
            except OSError:
                continue
for p, sz, mt, task in sorted(parts, key=lambda x: -x[1]):
    age = (time.time() - mt) / 60
    print(f'  {sz/1024/1024:>8.1f} MB  {age:>5.1f}分钟前  [{task}] '
          f'{os.path.basename(p)[:65]}')

print()
print('=' * 78)
print('4. 等 150 秒让孤儿文件沉淀（DMR 恢复阈值是 2 分钟）')
print('=' * 78)
for i in range(5):
    time.sleep(30)
    n = sum(1 for r, d, fs in os.walk(base) for f in fs
            if f.startswith('[正在录制]'))
    print(f'    +{(i+1)*30}s  剩余 [正在录制] 文件: {n} 个')

print()
print('=' * 78)
print('5. 重新启动 DMR（恢复器会接管孤儿分段）')
print('=' * 78)
subprocess.Popen(['explorer.exe', os.path.join(UP, 'Start_Render.bat')],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
started = False
for i in range(24):
    time.sleep(5)
    nd, nc = len(pids(DMR_Q)), len(pids(CMD_Q))
    if nd and nc:
        print(f'    +{(i+1)*5}s  DMR={nd} 守护={nc}')
        started = True
        break
    if i % 2 == 0:
        print(f'    +{(i+1)*5}s  DMR={nd} 守护={nc}')

print()
print('=' * 78)
print('6. 恢复结果')
print('=' * 78)
print(f'  守护={pids(CMD_Q) or "❌"}  DMR={pids(DMR_Q) or "❌"}')
print(f'  streamgears={pids(SG_Q) or "（无）"}  ffmpeg={pids(FF_Q) or "（无）"}')
print()
left = []
for root, dirs, files in os.walk(base):
    for f in files:
        if f.startswith('[正在录制]'):
            p = os.path.join(root, f)
            try:
                left.append((p, os.path.getsize(p), os.path.basename(root)))
            except OSError:
                continue
print(f'  剩余 [正在录制] 文件: {len(left)} 个')
for p, sz, task in sorted(left, key=lambda x: -x[1]):
    print(f'    {sz/1024/1024:>8.1f} MB  [{task}] {os.path.basename(p)[:65]}')

# 日志里的恢复记录
logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
              key=os.path.getmtime, reverse=True)
if logs:
    print()
    print(f'  日志 {os.path.basename(logs[0])} 里的恢复记录:')
    txt = open(logs[0], encoding='utf-8', errors='replace').read()
    for line in txt.split('\n')[-160:]:
        if '[恢复]' in line or '恢复阶段完成' in line:
            print(f'    {line.strip()[:150]}')

if not started:
    print()
    print('❌ 30 秒内没有检测到新的 DMR 进程 —— 重启可能失败，请手动双击 Start_Render.bat。')
    raise SystemExit(1)
