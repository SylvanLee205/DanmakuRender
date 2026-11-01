"""检查三个孤儿 .flv 与已入库分段是否有内容重叠（避免重复上传）。

已知：
  孤儿1  22:30:36 → 23:30:35
  孤儿2  23:30:35 → 00:30:37
  孤儿3  00:30:37 → 00:38:42
  已入库 00:20:38 → 00:38:50  -> 哭哭不嘻嘻-2026年10月08日00点20分.mkv (已渲染上传)

问题：孤儿2/3 的时间段和已入库的那个有重叠（00:20~00:38 vs 00:30~00:38）。
      需要确认它们是**独立内容**还是**重复内容**。

方法：
  1. 看已入库分段的实际时长（如果只有 ~18 分钟，说明它是独立的一段）
  2. 从孤儿文件里抽帧/看关键画面时间戳，和已入库的对比
  3. 最可靠：看每个文件的**实际内容时长**（不是 ffprobe 报的错乱值）
     - 用 ffmpeg 解码计数或按码率估算
"""
import json
import os
import subprocess
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）


UP = _PROJECT_ROOT
D = os.path.join(UP, '直播回放', '哭哭不嘻嘻')
DM = os.path.join(UP, '直播回放', '哭哭不嘻嘻（弹幕版）')


def run(cmd, timeout=900):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=timeout)
    return r.returncode, (r.stdout or ''), (r.stderr or '')


print('=' * 78)
print('1. 已入库的那个分段（00点20分）与云端状态')
print('=' * 78)
target = '哭哭不嘻嘻-2026年10月08日00点20分'
mp4 = os.path.join(DM, target + '（弹幕版）.mp4')
mkv = os.path.join(D, target + '.mkv')
for p, label in ((mp4, '弹幕版 mp4'), (mkv, '源 mkv')):
    if os.path.exists(p):
        st = os.stat(p)
        print(f'  ✅ {label}: {st.st_size/1024/1024:.2f} MB  '
              f'{time.strftime("%m-%d %H:%M:%S", time.localtime(st.st_mtime))}')
        rc, so, se = run(['ffprobe', '-v', 'error', '-show_entries',
                          'format=duration', '-of',
                          'default=nw=1:nk=1', p], timeout=120)
        print(f'      ffprobe 时长: {so.strip()} 秒')
    else:
        print(f'  -- {label}: 不存在（{p}）')

print()
print('=' * 78)
print('2. 每个孤儿 .flv 的**真实**内容时长')
print('=' * 78)
print('  方法：用 ffmpeg 完整解码并统计实际时长（-f null 输出）')
for f in sorted(os.listdir(D)):
    if not f.endswith('.flv'):
        continue
    p = os.path.join(D, f)
    sz = os.path.getsize(p)
    print(f'\n  === {f[:70]} ===')
    print(f'      文件大小: {sz/1024/1024:.2f} MB')
    # 用 -progress 拿真实处理时长；这里用 ffmpeg 的统计行
    rc, so, se = run(['ffmpeg', '-v', 'info', '-i', p, '-f', 'null', '-'],
                     timeout=1800)
    # 解析末尾的 time= 或 stream 信息
    lines = [l for l in se.split('\n') if l.strip()]
    for l in lines:
        if 'Duration:' in l or 'time=' in l or 'bitrate:' in l or 'Stream #' in l:
            print(f'      {l.strip()[:150]}')
        if l.strip().startswith('frame=') or l.strip().startswith('size='):
            print(f'      {l.strip()[:150]}')

print()
print('=' * 78)
print('3. 按码率反推真实时长（交叉验证）')
print('=' * 78)
for f in sorted(os.listdir(D)):
    if not f.endswith('.flv'):
        continue
    p = os.path.join(D, f)
    rc, so, se = run(['ffprobe', '-v', 'error', '-show_entries',
                      'format=bit_rate', '-of',
                      'default=nw=1:nk=1', p], timeout=120)
    try:
        br = float(so.strip())
        dur = os.path.getsize(p) * 8 / br
        print(f'  {f[:60]}')
        print(f'      {os.path.getsize(p)/1024/1024:.2f} MB / {br/1000:.0f} kbps '
              f'= {dur/60:.1f} 分钟')
    except Exception:
        print(f'  {f[:60]}: 无法估算（bitrate={so.strip()!r}）')

print()
print('=' * 78)
print('4. 结论')
print('=' * 78)
print('''  判断重复的方法：
    - 如果孤儿文件时长 + 已入库时长 ≈ 不重叠，说明是独立内容 -> 值得抢救
    - 如果有重叠，上传后会出现重复片段（但内容不丢，只是冗余）

  由于这是竖屏主播，且"跳过上传规则"要求横屏，
  这些竖屏内容**本来就会正常上传**（会占空间）。
''')
