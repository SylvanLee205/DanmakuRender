"""查 哭哭不嘻嘻 的弹幕文件为什么是 0 字节。

对比：其他正在录制/刚录完的任务，它们的 .ass 有多大？
"""
import os
import subprocess
import time

REPLAY = r'F:\DanmakuRender_AutoUp\直播回放'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 哭哭不嘻嘻 的 .ass 详情（含大小变化观察）')
print('=' * 78)
d = os.path.join(REPLAY, '哭哭不嘻嘻')
for f in sorted(os.listdir(d)):
    if f.endswith('.ass'):
        p = os.path.join(d, f)
        st = os.stat(p)
        print(f'  {f}')
        print(f'      大小 {st.st_size} 字节   修改 {time.strftime("%H:%M:%S", time.localtime(st.st_mtime))}')

print()
print('  观察 30 秒（看有没有写入）:')
p = None
for f in os.listdir(d):
    if f.endswith('.ass') and '正在录制' in f:
        p = os.path.join(d, f)
        break
if p:
    s1 = os.path.getsize(p)
    m1 = os.path.getmtime(p)
    time.sleep(30)
    s2 = os.path.getsize(p)
    m2 = os.path.getmtime(p)
    print(f'    大小: {s1} -> {s2} 字节')
    print(f'    修改时间: {time.strftime("%H:%M:%S", time.localtime(m1))} -> '
          f'{time.strftime("%H:%M:%S", time.localtime(m2))}')
    if s2 > s1 or m2 > m1:
        print('    ✅ 有写入活动')
    else:
        print('    ⚠️ 30 秒内无写入 —— 弹幕可能真的没在记录')

print()
print('=' * 78)
print('2. 对照：其他任务正在录制的 .ass 大小')
print('=' * 78)
rows = []
for task in sorted(os.listdir(REPLAY)):
    sub = os.path.join(REPLAY, task)
    if not os.path.isdir(sub) or task.endswith('（弹幕版）'):
        continue
    for f in os.listdir(sub):
        if f.endswith('.ass') and '正在录制' in f:
            pp = os.path.join(sub, f)
            try:
                rows.append((os.path.getsize(pp), task, f,
                             os.path.getmtime(pp)))
            except Exception:
                pass
if rows:
    for sz, task, f, mt in sorted(rows, reverse=True):
        print(f'  {sz:>10} 字节  {time.strftime("%H:%M:%S", time.localtime(mt))}  '
              f'[{task}] {f[:50]}')
else:
    print('  （只有哭哭不嘻嘻在录）')

print()
print('=' * 78)
print('3. 已完成录制的分段，它们的 .ass 有多大（正常值参考）')
print('=' * 78)
done = []
for task in sorted(os.listdir(REPLAY)):
    sub = os.path.join(REPLAY, task)
    if not os.path.isdir(sub) or task.endswith('（弹幕版）'):
        continue
    for f in os.listdir(sub):
        if f.endswith('.ass') and '正在录制' not in f:
            pp = os.path.join(sub, f)
            try:
                done.append((os.path.getsize(pp), task, f))
            except Exception:
                pass
for sz, task, f in sorted(done, reverse=True)[:10]:
    print(f'  {sz:>10} 字节  [{task}] {f[:55]}')
if not done:
    print('  （没有已完成的 .ass —— 都被清理了，正常）')

print()
print('=' * 78)
print('4. DMR 日志里有没有弹幕相关错误')
print('=' * 78)
import glob
logs = sorted(glob.glob(r'F:\DanmakuRender_AutoUp\logs\DMR-2026*.log'),
              key=os.path.getmtime, reverse=True)
hits = []
for lg in logs[:2]:
    for line in open(lg, encoding='utf-8', errors='replace'):
        if ('弹幕' in line or 'danmaku' in line.lower() or '.ass' in line) and \
           not line.strip().startswith('"'):
            hits.append(line.strip())
for l in hits[-15:]:
    print(f'  {l[:170]}')
if not hits:
    print('  （无弹幕相关日志）')

print()
print('=' * 78)
print('5. 结论')
print('=' * 78)
print('''  弹幕 .ass 是随直播**实时写入**的。
  如果长时间 0 字节且无写入活动，说明弹幕没被记录 ——
  但这不影响视频录制，且 DMR 后续仍会渲染（没弹幕就渲染不出弹幕版）。
''')
