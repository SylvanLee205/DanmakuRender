"""CD2 已重启，补传之前失败的文件。"""
import json
import os
import subprocess
import time

UP = r'F:\DanmakuRender_AutoUp'
RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
os.chdir(UP)

print('=' * 78)
print('1. CD2 状态确认')
print('=' * 78)


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('  进程: ' + (ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | "
                    "ForEach-Object { 'PID ' + $_.Id + ' 启动 ' + $_.StartTime.ToString('HH:mm:ss') }") or '未运行'))
print('  29798: ' + ps("(Get-NetTCPConnection -LocalPort 29798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count.ToString()").strip() + ' 个监听')
r = subprocess.run([RCLONE, 'lsf', 'cd2:百度网盘/DMR录播', '--max-depth', '1'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=300)
print(f'  云端连通: exit={r.returncode}  {len([x for x in r.stdout.split(chr(10)) if x.strip()])} 个目录')
if r.returncode != 0:
    print(f'    {(r.stderr or "")[:300]}')
    raise SystemExit('CD2 还没好，先别补传')

print()
print('=' * 78)
print('2. 失败队列里的文件，逐个补传')
print('=' * 78)
p = os.path.join(UP, '.temp', 'failed_uploads.json')
d = json.loads(open(p, encoding='utf-8', errors='replace').read())

uploaded, failed = [], []
for uuid, task in d.items():
    files = task.get('files') or []
    src = task.get('source') or ''
    # source 形如 'replay/掉了颗兔牙' → 任务名
    taskname = src.split('/', 1)[1] if '/' in src else src
    for f in files:
        fp = f.get('path') if isinstance(f, dict) else str(f)
        if not fp:
            continue
        # 修掉相对路径里混用的反斜杠（Windows 能处理 /，但混用会出问题）
        real = os.path.normpath(os.path.join(UP, fp.lstrip('./\\')))
        print(f'\n  --- {os.path.basename(fp)}')
        print(f'      任务名    : {taskname}')
        print(f'      实际路径  : {real}')
        print(f'      存在      : {os.path.exists(real)}')
        if not os.path.exists(real):
            print(f'      ⚠ 找不到文件，跳过')
            failed.append(fp)
            continue
        size = os.path.getsize(real)
        print(f'      大小      : {size} 字节 ({size/1024/1024:.1f} MB)')
        dest = f'cd2:百度网盘/DMR录播/{taskname}/{os.path.basename(real)}'
        print(f'      目标      : {dest}')
        # 用 copyto 明确指定目标名，避免受 CD2 目录解析影响
        rr = subprocess.run([RCLONE, 'copyto', real, dest, '--retries', '5',
                             '--low-level-retries', '10'],
                            capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=3600)
        print(f'      rclone exit={rr.returncode}')
        if rr.returncode != 0:
            print(f'        {(rr.stderr or "")[:400]}')
            failed.append(fp)
        else:
            uploaded.append((real, size, dest))

print()
print('=' * 78)
print('3. 等 60 秒后核对云端字节')
print('=' * 78)
time.sleep(60)
ok = 0
for real, size, dest in uploaded:
    taskname = dest.split('/')[2]
    rr = subprocess.run([RCLONE, 'lsf', f'cd2:百度网盘/DMR录播/{taskname}', '--format', 'sp'],
                        capture_output=True, text=True, encoding='utf-8',
                        errors='replace', timeout=300)
    cloud = {}
    for x in rr.stdout.split('\n'):
        x = x.strip()
        if ';' in x:
            sz, nm = x.split(';', 1)
            cloud[nm] = sz
    nm = os.path.basename(real)
    cs = cloud.get(nm)
    if cs == str(size):
        print(f'  ✅ {nm}  字节一致 ({size})')
        ok += 1
    elif cs:
        print(f'  ⚠ {nm}  云端 {cs} vs 本地 {size}')
    else:
        print(f'  ❌ {nm}  云端还没有')

print()
print('=' * 78)
print(f'补传结果: {ok}/{len(uploaded)} 成功')
if failed:
    print(f'仍有 {len(failed)} 个未处理:')
    for f in failed:
        print(f'  {f}')
print('=' * 78)
