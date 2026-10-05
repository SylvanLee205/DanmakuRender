"""诊断上传失败：DMR 日志 + 云端状态 + CD2 状态。"""
import glob
import json
import os
import re
import subprocess
import time

UP = r'F:\DanmakuRender_AutoUp'
RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
NEW = os.path.join(os.environ['LOCALAPPDATA'], 'CloudDrive.WinUI')

print('=' * 78)
print('1. 最近的 DMR 日志（搜 upload / 错误）')
print('=' * 78)
logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-*.log')),
              key=os.path.getmtime, reverse=True)[:2]
for lg in logs:
    print(f'\n--- {os.path.basename(lg)}  (最后写 {time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(lg)))}) ---')
    txt = open(lg, encoding='utf-8', errors='replace').read()
    lines = txt.split('\n')
    # 找 upload 相关
    hits = [l for l in lines if re.search(
        r'upload|Upload|上传|rclone|错误|error|失败|fail', l, re.I)]
    print(f'  匹配 {len(hits)} 条，尾部 25 条:')
    for l in hits[-25:]:
        print(f'    {l[:170]}')

print()
print('=' * 78)
print('2. 失败上传队列')
print('=' * 78)
for rel in ('.temp/failed_uploads.json', '.temp/failed_render_tasks.json'):
    p = os.path.join(UP, rel)
    if os.path.exists(p):
        mt = time.strftime('%m-%d %H:%M:%S', time.localtime(os.path.getmtime(p)))
        try:
            d = json.loads(open(p, encoding='utf-8', errors='replace').read())
            n = len(d) if isinstance(d, (list, dict)) else '?'
        except Exception as e:
            n = f'解析失败 {e}'
        print(f'  {rel}: {n} 条  (修改 {mt})')
        if isinstance(d, dict) and d:
            for k, v in list(d.items())[:3]:
                print(f'      {k}: {json.dumps(v, ensure_ascii=False, default=str)[:200]}')
    else:
        print(f'  {rel}: 不存在')

print()
print('=' * 78)
print('3. CD2 状态')
print('=' * 78)
def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()

print('  进程: ' + (ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | "
                    "ForEach-Object { 'PID ' + $_.Id + ' 启动 ' + $_.StartTime.ToString('HH:mm:ss') }") or '未运行'))
print('  29798: ' + ps("(Get-NetTCPConnection -LocalPort 29798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count.ToString()").strip() + ' 个监听')
print()
print('  CD2 日志（今天的，尾部 20 行）:')
ld = os.path.join(NEW, 'log')
today = time.strftime('%Y-%m-%d') + '.log'
p = os.path.join(ld, today)
if os.path.exists(p):
    lines = open(p, encoding='utf-8', errors='replace').read().split('\n')
    for l in lines[-20:]:
        if l.strip():
            print(f'    {l[:170]}')
else:
    print('    （无日志）')

print()
print('=' * 78)
print('4. CD2 上传任务队列')
print('=' * 78)
import shutil
import sqlite3
dst = os.path.join(os.environ['TEMP'], 'cd2q_diag')
os.makedirs(dst, exist_ok=True)
for s in ('', '-wal', '-shm'):
    src = os.path.join(NEW, 'clouddrive_data.sqlite' + s)
    if os.path.exists(src):
        try:
            shutil.copy2(src, os.path.join(dst, 'clouddrive_data.sqlite' + s))
        except Exception:
            pass
try:
    con = sqlite3.connect(f'file:{os.path.join(dst, "clouddrive_data.sqlite")}?mode=ro', uri=True)
    cur = con.cursor()
    cur.execute('PRAGMA table_info(transfer_tasks)')
    cols = [r[1] for r in cur.fetchall()]
    cur.execute('SELECT * FROM transfer_tasks')
    rows = cur.fetchall()
    print(f'  队列 {len(rows)} 条')
    for r in rows[:10]:
        d = dict(zip(cols, r))
        print(f'    {d.get("task_type")} {d.get("dest_path")} {d.get("filename")} {d.get("size")}')
    con.close()
except Exception as e:
    print(f'  查询失败: {e}')

print()
print('=' * 78)
print('5. 云端 vvu 和 相扑猫 的最新文件')
print('=' * 78)
for task in ('vvu', '掉了颗兔牙', '相扑猫'):
    r = subprocess.run([RCLONE, 'lsf', f'cd2:百度网盘/DMR录播/{task}', '--format', 'sp'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=300)
    rows = [x.strip() for x in r.stdout.split('\n') if x.strip()]
    print(f'  【{task}】{len(rows)} 个')
    for x in sorted(rows)[-4:]:
        print(f'      {x}')

print()
print('=' * 78)
print('6. 本地 vvu（弹幕版）最新文件')
print('=' * 78)
d = os.path.join(UP, '直播回放', 'vvu（弹幕版）')
if os.path.isdir(d):
    fs = sorted(os.listdir(d))
    for f in fs[-6:]:
        p = os.path.join(d, f)
        print(f'  {os.path.getsize(p)/1024/1024:>8.1f} MB  '
              f'{time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(p)))}  {f}')
