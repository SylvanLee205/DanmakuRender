"""DMR 状态一键检查 —— 回答"程序到底在不在监听"。

用法:
    python tools\\check_dmr_alive.py

判断逻辑：
    1. 守护 cmd 进程在不在      -> 不在 = 崩溃后不会自动重启
    2. DMR python 进程在不在    -> 不在 = 程序没跑
    3. 日志最后写入时间          -> 太久没写 = 可能真卡死
    4. 心跳行                   -> 每 30 分钟一行，证明还活着
    5. 最近的开播/渲染/上传记录  -> 说明业务在跑
"""
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


print('=' * 70)
print(f'DMR 状态检查   {time.strftime("%Y-%m-%d %H:%M:%S")}')
print('=' * 70)

# 1. 守护进程
cmd_pids = ps("Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
              "Where-Object { $_.CommandLine -like '*Start_Render*' } | "
              "ForEach-Object { $_.ProcessId }").split()
print(f'\n[守护进程] {"✅ 在" if cmd_pids else "❌ 不在"}'
      + (f'  PID {", ".join(cmd_pids)}' if cmd_pids else '  ← 崩溃后不会自动重启！'))

# 2. DMR 进程
py = ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*main.py*' } | "
        "ForEach-Object { $_.ProcessId }").split()
print(f'[DMR 进程] {"✅ 在" if py else "❌ 不在"}'
      + (f'  PID {", ".join(py)}' if py else '  ← 程序没在跑！'))

if py:
    info = ps("Get-Process -Id " + ",".join(py) + " -ErrorAction SilentlyContinue | "
              "Sort-Object StartTime | Select-Object -Last 1 | "
              "ForEach-Object { '启动 ' + $_.StartTime.ToString('MM-dd HH:mm:ss') + "
              "'   内存 ' + [math]::Round($_.WorkingSet64/1MB) + ' MB' }")
    print(f'          {info}')

# 3. 日志文件
logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
              key=os.path.getmtime, reverse=True)
print()
if not logs:
    print('[日志] ❌ 找不到日志文件')
else:
    lg = logs[0]
    age = time.time() - os.path.getmtime(lg)
    print(f'[日志] {os.path.basename(lg)}  最后写入 {int(age)} 秒前')
    if age < 300:
        print(f'       ✅ 5 分钟内有写入')
    elif age < 3600:
        print(f'       🟠 {int(age/60)} 分钟没写（可能只是没事件）')
    else:
        print(f'       ⚠ {age/3600:.1f} 小时没写 —— 检查是否真卡死')

    txt = open(lg, encoding='utf-8', errors='replace').read()

    # 4. 心跳
    hb = re.findall(r'\[心跳\] (.+)', txt)
    print(f'\n[心跳] {len(hb)} 条' + (f'  最新: {hb[-1]}' if hb else '（每 30 分钟一条，刚启动的话还没有）'))

    # 5. 业务活动
    print('\n[最近活动]')
    for pat, label in ((r'(.+?): 直播开始', '开播'),
                       (r'(.+?): (.+?) 渲染完成', '渲染完成'),
                       (r'正在上传: (.+)', '正在上传'),
                       (r'(.+?): (.+?) 上传完成', '上传完成'),
                       (r'正在清理原文件: (.+)', '清理')):
        hits = re.findall(pat, txt)
        if hits:
            last = hits[-1]
            last = last if isinstance(last, str) else ' / '.join(last)
            print(f'   {label}: {len(hits)} 次   最近: {last[:60]}')
    if not any(re.findall(p, txt) for p in
               (r'直播开始', r'渲染完成', r'上传完成', r'正在清理')):
        print('   （重启后还没有业务活动）')

# 6. 定时任务/服务
print('\n[相关服务]')
print('   CD2: ' + ps("(Get-Service CloudDrive2).Status.ToString() + ' / ' + "
                   "(Get-Service CloudDrive2).StartType.ToString()"))

print()
print('=' * 70)
print('结论')
print('=' * 70)
ok = bool(cmd_pids) and bool(py)
if ok:
    print('  ✅ DMR 正在运行并在监听。')
    print('     控制台长时间空白是正常的 —— 说明当前没有主播开播。')
    print('     有主播开播/渲染/上传时会输出。')
else:
    print('  ❌ 有问题：')
    if not cmd_pids:
        print('     - 守护进程不在：崩溃后不会自动重启')
        print('       修复：双击 Start_Render.bat')
    if not py:
        print('     - DMR 没在跑')
        print('       修复：双击 Start_Render.bat')
