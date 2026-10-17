"""建立 CD2 稳定性观察机制：记录看门狗拉起次数 + 上传成功率。"""
import glob
import json
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
print('CD2 稳定性观察报告')
print('=' * 78)
print(f'  生成时间: {time.strftime("%Y-%m-%d %H:%M:%S")}')
print()

print('[1] 看门狗拉起记录（关键指标）')
state = os.path.join(UP, '.temp', 'cd2_watchdog_state.json')
if os.path.exists(state):
    d = json.load(open(state, encoding='utf-8'))
    rs = d.get('restarts') or []
    print(f'  累计拉起 {len(rs)} 次')
    for r in rs:
        print(f'    {r.get("time")}  进程={r.get("proc")} 端口={r.get("port")} 结果={"成功" if r.get("ok") else "失败"}')
    if not rs:
        print(f'  ✅ 从建立至今 CD2 一次都没崩过')
    elif len(rs) == 1:
        print(f'  ⚠ 崩过 1 次（就是建立看门狗时的那次测试）')
    else:
        print(f'  🔴 崩过 {len(rs)} 次 —— 建议考虑换 BaiduPCS-Go')
else:
    print('  （还没有状态文件 —— 说明看门狗从没触发过拉起，CD2 一直正常 ✅）')

print()
print('[2] 看门狗日志')
lg = os.path.join(UP, 'logs', 'cd2_watchdog.log')
if os.path.exists(lg):
    lines = [l for l in open(lg, encoding='utf-8', errors='replace').read().split('\n') if l.strip()]
    print(f'  {len(lines)} 条记录，尾部 6 条:')
    for l in lines[-6:]:
        print(f'    {l}')
else:
    print('  （无日志 = 一直正常，静默模式）')

print()
print('[3] DMR 上传成功率（从最近的日志统计）')
logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
              key=os.path.getmtime, reverse=True)[:3]
ok_n, fail_n = 0, 0
conn_fail = 0
for lg in logs:
    try:
        txt = open(lg, encoding='utf-8', errors='replace').read()
    except Exception:
        continue
    for line in txt.split('\n'):
        if '上传完成' in line:
            ok_n += 1
        if 'upload failed' in line:
            fail_n += 1
        if 'connection refused' in line or 'actively refused' in line:
            conn_fail += 1
print(f'  上传成功: {ok_n} 次')
print(f'  上传失败: {fail_n} 次')
print(f'  其中 CD2 连接被拒: {conn_fail} 次')
if ok_n + fail_n > 0:
    rate = ok_n / (ok_n + fail_n) * 100
    print(f'  成功率  : {rate:.1f}%')

print()
print('[4] 失败上传队列')
p = os.path.join(UP, '.temp', 'failed_uploads.json')
if os.path.exists(p):
    try:
        d = json.loads(open(p, encoding='utf-8', errors='replace').read())
        print(f'  待补传: {len(d)} 条')
        for k, v in list(d.items())[:5]:
            fs = [f.get('path') if isinstance(f, dict) else f for f in (v.get('files') or [])]
            print(f'    {fs}')
        if d:
            print(f'  ⚠ 有失败任务，跑 retry_failed_uploads.py 补传')
    except Exception as e:
        print(f'  解析失败: {e}')

print()
print('[5] 当前组件状态')
print('  CD2 应用: ' + (ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | "
                    "ForEach-Object { 'PID ' + $_.Id + ' (运行 ' + "
                    "[math]::Round(((Get-Date) - $_.StartTime).TotalHours,1) + ' 小时)' }") or '未运行'))
print('  CD2 旧服务: ' + ps("Get-Service CloudDrive2 | ForEach-Object { $_.Status.ToString() + ' / ' + $_.StartType.ToString() }"))
print('  DMR: ' + (ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                  "Where-Object { $_.CommandLine -like '*main.py*' } | "
                  "ForEach-Object { 'PID ' + $_.ProcessId }") or '未运行'))

print()
print('=' * 78)
print('结论')
print('=' * 78)
print('  切换 BaiduPCS-Go 的触发条件（任一满足就切）：')
print('    □ 看门狗拉起记录 ≥ 2 次（反复崩）')
print('    □ 审计发现新的"本地有云端无"文件且原因是上传失败')
print('    □ 需要严格限速（路由器设不了）')
print('  迁移手册: F:\\DanmakuRender_AutoUp\\docs\\上传方案备选-BaiduPCS-Go迁移手册.md')
