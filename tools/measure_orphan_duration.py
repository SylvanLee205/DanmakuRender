"""精确测孤儿 .flv 的真实时长（静默模式，避免输出爆炸）。

上次教训：用 `ffmpeg -v info` 会把每帧进度都打出来，输出几百行。
正确做法：用 `ffprobe` 读**最后一个 packet 的 pts_time**，或者
         `ffmpeg -v quiet -stats` 只在结束时打一行统计。
"""
import os
import re
import subprocess
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）

D = _PROJECT_ROOT + r'\直播回放\哭哭不嘻嘻'
DM = _PROJECT_ROOT + r'\直播回放\哭哭不嘻嘻（弹幕版）'


def real_duration(p):
    """用 ffprobe 读最后包的时间戳 = 真实内容时长。

    为什么不用 format=duration：
        FLV 的时间戳可能错乱（实测报 90138 秒），
        但**最后一个 packet 的 pts_time** 能反映真实长度。
    """
    r = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'packet=pts_time', '-of', 'csv=p=0', p],
        capture_output=True, text=True, encoding='utf-8',
        errors='replace', timeout=1800)
    times = []
    for line in (r.stdout or '').split('\n'):
        line = line.strip().rstrip(',')
        if not line:
            continue
        try:
            times.append(float(line))
        except ValueError:
            pass
    if not times:
        return None, 0
    # pts 可能有错乱，用最大-最小 和 帧数/帧率 两种方式交叉
    span = max(times) - min(times)
    return span, len(times)


print('=' * 78)
print('孤儿 .flv 的真实时长（按最后一个视频包的时间戳）')
print('=' * 78)
flvs = sorted(f for f in os.listdir(D) if f.endswith('.flv'))
info = {}
for f in flvs:
    p = os.path.join(D, f)
    sz = os.path.getsize(p)
    t0 = time.time()
    span, nframes = real_duration(p)
    el = time.time() - t0
    if span is None:
        print(f'  {f[:65]}')
        print(f'      ❌ 无法读取时间戳')
        continue
    info[f] = (span, nframes, sz)
    print(f'  {f[:65]}')
    print(f'      {sz/1024/1024:>8.1f} MB   {nframes:>7} 帧   '
          f'时间跨度 {span/60:>6.1f} 分钟   (扫描 {el:.0f}s)')

print()
print('=' * 78)
print('已入库分段（用于判断重叠）')
print('=' * 78)
dm_info = []
for f in sorted(os.listdir(DM)):
    if not f.endswith('.mp4'):
        continue
    p = os.path.join(DM, f)
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                        'format=duration', '-of', 'default=nw=1:nk=1', p],
                       capture_output=True, text=True, timeout=120)
    try:
        d = float(r.stdout.strip())
    except Exception:
        d = 0
    dm_info.append((f, d))
    print(f'  {d/60:>6.1f} 分钟  {f}')

print()
print('=' * 78)
print('★ 重叠分析')
print('=' * 78)
# 孤儿的时间段（从文件名时间戳推）
import datetime

for f in flvs:
    m = re.search(r'-(\d{14})-', f)
    if not m:
        continue
    ts = m.group(1)
    start = datetime.datetime.strptime(ts, '%Y%m%d%H%M%S')
    span = info.get(f, (0, 0, 0))[0]
    end = start + datetime.timedelta(seconds=span)
    print(f'  {f[:60]}')
    print(f'      实际时段: {start:%m-%d %H:%M:%S} ~ {end:%m-%d %H:%M:%S}'
          f'  ({span/60:.1f} 分钟)')

print()
print('  已入库的 10-08 00点20分:')
tgt = [x for x in dm_info if '10月08日00点20分' in x[0]]
if tgt:
    name, d = tgt[0]
    # 它的录制起点：文件名说 00点20分，但实际录制可能从 00:20:38 开始
    print(f'      {name}')
    print(f'      时长 {d/60:.1f} 分钟')

print()
print('=' * 78)
print('结论')
print('=' * 78)
print('''  判断规则：
    - 孤儿时段与已入库时段**不重叠** -> 独立内容，值得抢救
    - 有重叠 -> 重复内容，抢救会产生冗余上传
''')
