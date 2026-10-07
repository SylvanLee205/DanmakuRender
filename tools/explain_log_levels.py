"""验证日志级别过滤：哪些能在控制台看到，哪些只在日志文件里。"""
import glob
import os
import re
import subprocess
import time

UP = r'F:\DanmakuRender_AutoUp'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 当前 DMR 状态')
print('=' * 78)
print('  守护 cmd: ' + (ps("Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
                   "Where-Object { $_.CommandLine -like '*Start_Render*' } | "
                   "ForEach-Object { 'PID ' + $_.ProcessId }").replace('\n', ' ') or '无'))
print('  DMR:      ' + (ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                  "Where-Object { $_.CommandLine -like '*main.py*' } | "
                  "ForEach-Object { $_.ProcessId }").replace('\n', ' ') or '无'))
print('  现在:     ' + ps("(Get-Date).ToString('yyyy-MM-dd HH:mm:ss')"))

print()
print('=' * 78)
print('2. ★ 各消息的级别归属（决定控制台可见性）')
print('=' * 78)
rows = [
    ('下载任务 xxx 已启动。',              'engine',    'INFO',     '❌ 控制台不显示'),
    ('{"source": "downloader", ...}',      'engine',    'DEBUG',    '❌ 控制台不显示'),
    ('xxx: 直播已结束.',                    'liveevents','INFO',     '❌ 控制台不显示'),
    ('xxx: 直播开始.',                      'liveevents','PROGRESS', '✅ 控制台**会**显示'),
    ('xxx: 视频分段 xxx.mkv 录制完成.',      'liveevents','PROGRESS', '✅ 控制台**会**显示'),
    ('正在渲染: xxx.mkv',                   'Render',    'PROGRESS', '✅ 控制台**会**显示'),
    ('xxx: xxx.mp4 渲染完成.',              'liveevents','PROGRESS', '✅ 控制台**会**显示'),
    ('正在上传: xxx.mp4',                   'Uploader',  'PROGRESS', '✅ 控制台**会**显示'),
    ('xxx: xxx.mp4 上传完成.',              'liveevents','PROGRESS', '✅ 控制台**会**显示'),
    ('正在清理原文件: xxx.mkv（含弹幕文件）', 'Cleaner',   'PROGRESS', '✅ 控制台**会**显示'),
    ('xxx: 清理完成: ...',                  'liveevents','PROGRESS', '✅ 控制台**会**显示'),
    ('GOP: 源帧率 22 x 8 = 176 ...',        'dmrender',  'DEBUG',    '❌ 控制台不显示'),
]
print(f'  {"消息":44} {"级别":10} 控制台')
print('  ' + '-' * 76)
for msg, mod, lvl, vis in rows:
    print(f'  {msg[:42]:44} {lvl:10} {vis}')

print()
print('=' * 78)
print('3. 你贴的那段日志，逐行解释')
print('=' * 78)
explain = [
    ('[engine][info]: 下载任务 U 已启动。',
     '任务 U 的监视线程起来了。这是内部状态，控制台不显示（你不需要看）'),
    ('[engine][debug]: {source: downloader, event: liveend, ...}',
     '引擎内部消息字典。纯调试信息，控制台不显示'),
    ('[liveevents][info]: U: 直播已结束.',
     'U 这个主播**当前没在播**。控制台不显示'),
    ('[liveevents][info]: 一一一天: 直播开始.',
     '★ 一一一天**开播了**！控制台**会显示**这一条'),
]
for log, exp in explain:
    print(f'\n  {log}')
    print(f'      -> {exp}')

print()
print('=' * 78)
print('4. 实际日志文件里搜"直播开始"和"直播已结束"')
print('=' * 78)
logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
              key=os.path.getmtime, reverse=True)
if logs:
    lg = logs[0]
    txt = open(lg, encoding='utf-8', errors='replace').read()
    start = re.findall(r'\[liveevents\]\[info\]: (.+?): 直播开始', txt)
    end = re.findall(r'\[liveevents\]\[info\]: (.+?): 直播已结束', txt)
    print(f'  {os.path.basename(lg)}:')
    print(f'    "直播开始" {len(start)} 次' + (f'  -> {sorted(set(start))[:10]}' if start else ''))
    print(f'    "直播已结束" {len(end)} 次（每条都在日志文件里，但控制台不显示）')

print()
print('=' * 78)
print('5. 怎么判断"真正启动并在监听了"')
print('=' * 78)
print('''  日志里出现这些就说明监视线程已在工作：
     "[engine][info]: 下载任务 XXX 已启动。"
  每个任务一行，共 30+ 行 —— 这是**启动瞬间**的批量输出。

  之后每个任务会周期性检查主播状态：
     没开播 -> "[liveevents][info]: XXX: 直播已结束."   （控制台不显示）
     开播了 -> "[liveevents][info]: XXX: 直播开始."     （控制台**会**显示）

  ⚠️ 判断"还活着"的方法：
     1) 看守护 cmd 进程在不在（在 = 没崩）
     2) 看日志文件最新修改时间（应该持续更新）
     3) 故意的：如果所有主播都没开播，控制台会一直空白 —— 这是**正常**的，
        不是卡死。区别在于：卡死时日志文件也不再增长。
''')

print('=' * 78)
print('6. 日志文件活跃度（判断程序是否还在工作）')
print('=' * 78)
for lg in logs[:2]:
    mt = os.path.getmtime(lg)
    age = time.time() - mt
    print(f'  {os.path.basename(lg)}  {os.path.getsize(lg):>9} 字节  '
          f'最后写入 {int(age)} 秒前  {"✅ 活跃" if age < 300 else "⚠ 很久没写"}')
