"""验证路由器限速已从 4Mbps 改到 35Mbps，然后补传缺失文件。"""
import os
import shutil
import sqlite3
import subprocess
import time

RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
NEW = os.path.join(os.environ['LOCALAPPDATA'], 'CloudDrive.WinUI')
TMP = os.environ['TEMP']
UP = r'F:\DanmakuRender_AutoUp'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or ''))


def adapter_sent(name='Meta'):
    out = ps(f"(Get-NetAdapterStatistics | Where-Object {{ $_.Name -eq '{name}' }}).SentBytes")
    try:
        return int(out.strip())
    except Exception:
        return None


print('=' * 78)
print('1. 实测上行带宽（确认限速已改到 35Mbps = 4.4 MB/s）')
print('=' * 78)
data = os.path.join(TMP, 'upverify.bin')
with open(data, 'wb') as f:
    f.write(os.urandom(1024 * 1024) * 16)
mark = adapter_sent()
t0 = time.time()
r = subprocess.run(['curl.exe', '-s', '-o', 'NUL', '-w', '%{speed_upload}',
                    '-X', 'POST', '--data-binary', f'@{data}',
                    '--max-time', '180', 'https://speed.cloudflare.com/__up'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=240)
el = time.time() - t0
after = adapter_sent()
print(f'  curl exit={r.returncode}  耗时 {el:.1f}s')
try:
    sp = float(r.stdout.strip())
    print(f'  curl 上报: {sp/1024/1024:.2f} MB/s = {sp*8/1e6:.1f} Mbit/s')
except Exception:
    print(f'  curl 输出: {r.stdout.strip()[:60]}')
if mark and after and el > 0:
    mb = (after - mark) / el / 1024 / 1024
    print(f'  网卡实测: {mb:.2f} MB/s = {mb*8:.1f} Mbit/s')
    if mb > 2.5:
        print(f'  ✅ 上行正常（之前是 0.5 MB/s）')
    elif mb > 1.0:
        print(f'  🟠 上行改善了但还没到 4.4 MB/s')
    else:
        print(f'  🔴 上行仍然很慢')
try:
    os.remove(data)
except Exception:
    pass


def cloud_list(task):
    dst = os.path.join(TMP, 'cd2vf')
    os.makedirs(dst, exist_ok=True)
    for s in ('', '-wal', '-shm'):
        src = os.path.join(NEW, 'dir_cache.sqlite' + s)
        if os.path.exists(src):
            try:
                shutil.copy2(src, os.path.join(dst, 'dir_cache.sqlite' + s))
            except Exception:
                pass
    try:
        con = sqlite3.connect(f'file:{os.path.join(dst, "dir_cache.sqlite")}?mode=ro', uri=True)
        cur = con.cursor()
        cur.execute("SELECT id FROM cached_item WHERE path LIKE ?", (f'%/DMR录播/{task}',))
        out = {}
        for (did,) in cur.fetchall():
            cur.execute('SELECT name, size FROM files WHERE parent_id=?', (did,))
            for nm, sz in cur.fetchall():
                out[nm] = sz
        con.close()
        return out
    except Exception:
        return {}


print()
print('=' * 78)
print('2. 先清理堵塞队列（防单线程被占死）')
print('=' * 78)
r = subprocess.run([os.path.join(UP, '.venv', 'Scripts', 'python.exe'),
                    os.path.join(UP, 'tools', 'cd2_queue_health.py'), '--clean'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=600, cwd=UP)
for l in r.stdout.split('\n'):
    if any(k in l for k in ('队列', '删除', '就绪', '✅', '🔴', '发现')):
        print(f'  {l.strip()}')

print()
print('=' * 78)
print('3. 补传所有缺失文件')
print('=' * 78)
REPLAY = os.path.join(UP, '直播回放')
sent = []
for t in sorted(os.listdir(REPLAY)):
    if not t.endswith('（弹幕版）'):
        continue
    task = t[:-len('（弹幕版）')]
    d = os.path.join(REPLAY, t)
    if not os.path.isdir(d):
        continue
    loc = {f: os.path.getsize(os.path.join(d, f)) for f in os.listdir(d)
           if f.endswith('.mp4')}
    if not loc:
        continue
    # 只补 09-30 之后的（上传流水线启用时间）
    import re
    cf = cloud_list(task)
    miss = {f: s for f, s in loc.items() if f not in cf}
    # 过滤掉流水线启用前的老文件
    miss2 = {}
    for f, s in miss.items():
        m = re.search(r'(\d{4})年(\d{2})月(\d{2})日', f)
        if not m:
            continue
        y, mo, dd = m.groups()
        key = f'{y}-{mo}-{dd}'
        if key >= '2026-09-30':
            miss2[f] = s
    if not miss2:
        continue
    print(f'\n  【{task}】缺 {len(miss2)} 个:')
    for f, s in sorted(miss2.items()):
        p = os.path.join(d, f)
        print(f'      {s/1024/1024:>8.1f} MB  {f}')
        dest = f'cd2:百度网盘/DMR录播/{task}/{f}'
        rr = subprocess.run([RCLONE, 'copyto', p, dest, '--retries', '2'],
                            capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=3600)
        if rr.returncode != 0:
            print(f'        rclone 失败: {(rr.stderr or "")[:200]}')
        else:
            sent.append((task, f, s))

print()
print('=' * 78)
print(f'4. 等 CD2 异步上传（{len(sent)} 个文件）')
print('=' * 78)
total_mb = sum(s for _, _, s in sent) / 1024 / 1024
print(f'  总大小 {total_mb:.1f} MB，按 4.4 MB/s 约需 {total_mb/4.4:.0f} 秒')
waited = 0
while waited < 1800:
    time.sleep(60)
    waited += 60
    done = sum(1 for task, f, s in sent
               if str(cloud_list(task).get(f)) == str(s))
    print(f'    +{waited:>4}s  已确认 {done}/{len(sent)}')
    if done == len(sent):
        break

print()
print('=' * 78)
print('5. 最终验证')
print('=' * 78)
ok = 0
for task, f, s in sent:
    got = cloud_list(task).get(f)
    if str(got) == str(s):
        print(f'  ✅ {f}  ({s} 字节)')
        ok += 1
    else:
        print(f'  ❌ {f}  云端={got} 本地={s}')

print()
print('=' * 78)
print('6. 全量审计')
print('=' * 78)
r = subprocess.run([os.path.join(UP, '.venv', 'Scripts', 'python.exe'),
                    os.path.join(UP, 'tools', 'audit_cloud.py')],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=900, cwd=UP)
for l in r.stdout.split('\n'):
    if any(k in l for k in ('合计', '丢失', '清单来源')):
        print(f'  {l.strip()}')
