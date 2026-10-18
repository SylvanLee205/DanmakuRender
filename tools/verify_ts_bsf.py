"""验证用户提供的那套 FLV→TS 说法，重点是两处：

1) `-c copy` 存 TS 时，ffmpeg 是否会**自动**做 AVCC→AnnexB（h264_mp4toannexb）？
   如果自动做了，就不需要手写 -bsf:v。
   判据：把 TS 文件**掐掉开头**（去掉头部 SPS/PPS），剩下的还能不能解码。
        能解码 = 中间每个 I 帧都自带 SPS/PPS = AnnexB 已生效。

2) `-avoid_negative_ts make_zero` 对负/回退时间戳有没有实际效果？
"""
import json
import os
import shutil
import subprocess

TMP = r'F:\DanmakuRender_AutoUp\.temp\_tsbsf_test'
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
FF = 'ffmpeg'
FP = 'ffprobe'

print('=' * 78)
print('验证 1：ffmpeg 存 TS 时是否自动做 AnnexB（无需手写 bsf）')
print('=' * 78)

# 造一个 H.264 AVCC 源的 FLV（libx264 默认写 AVCC）
mp4 = os.path.join(TMP, 'src.mp4')
subprocess.run([FF, '-v', 'error', '-y',
                '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=22:duration=30',
                '-f', 'lavfi', '-i', 'sine=frequency=440:duration=30',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-g', '22',
                '-c:a', 'aac', '-b:a', '96k', mp4],
               capture_output=True, timeout=300)
flv = os.path.join(TMP, 'src.flv')
subprocess.run([FF, '-v', 'error', '-y', '-i', mp4, '-c', 'copy',
                '-f', 'flv', flv], capture_output=True, timeout=300)
print(f'  造 FLV: {os.path.getsize(flv)/1024:.0f} KB')

# 两种转封装：不写 bsf / 显式写 bsf
variants = [
    ('no-bsf',  []),
    ('with-bsf', ['-bsf:v', 'h264_mp4toannexb']),
]
ts_files = {}
for label, bsf in variants:
    out = os.path.join(TMP, f'{label}.ts')
    cmd = [FF, '-v', 'error', '-y', '-i', flv, '-c', 'copy', *bsf,
           '-f', 'mpegts', out]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=300)
    ok = r.returncode == 0 and os.path.exists(out)
    print(f'  {label:10} exit={r.returncode}  {os.path.getsize(out)/1024 if ok else 0:.0f} KB'
          + (f'  stderr={r.stderr[:80]}' if not ok else ''))
    if ok:
        ts_files[label] = out


def decode_errs(path, label):
    r = subprocess.run([FF, '-v', 'error', '-i', path, '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=600)
    lines = [l.strip() for l in (r.stderr or '').split('\n') if l.strip()]
    return r.returncode, len(lines), lines[:3]


def chop_head(path, ratio=0.45):
    """掐掉文件开头（模拟"没有头部 SPS/PPS"），保留后半段。"""
    size = os.path.getsize(path)
    off = int(size * ratio)
    out = path.replace('.ts', '_chopped.ts')
    with open(path, 'rb') as f:
        f.seek(off)
        data = f.read()
    with open(out, 'wb') as f:
        f.write(data)
    return out


print()
print('  ── 关键判据：掐掉开头 45%，剩下的还能解码吗 ──')
for label, p in ts_files.items():
    chopped = chop_head(p)
    rc, nerr, samples = decode_errs(chopped, label)
    # 统计能解出多少帧
    r2 = subprocess.run([FF, '-v', 'error', '-i', chopped, '-map', '0:v:0',
                         '-f', 'null', '-'],
                        capture_output=True, text=True, encoding='utf-8',
                        errors='replace', timeout=600)
    print(f'  {label:10} 掐头后 exit={r2.returncode}  错误行={nerr}')
    for s in samples[:2]:
        print(f'      {s[:100]}')
    if r2.returncode == 0:
        print(f'      ✅ 能解码 → 中间 I 帧自带 SPS/PPS → AnnexB 已生效')
    else:
        print(f'      ❌ 不能解码 → 缺 SPS/PPS')

print()
print('=' * 78)
print('验证 2：-avoid_negative_ts make_zero 的作用')
print('=' * 78)
# 造一个时间戳不从 0 开始、且带负数偏移的源
neg = os.path.join(TMP, 'shifted.mp4')
subprocess.run([FF, '-v', 'error', '-y', '-i', mp4,
                '-output_ts_offset', '-3', '-c', 'copy', neg],
               capture_output=True, timeout=300)
print(f'  造「时间戳偏移 -3 秒」的源: {os.path.getsize(neg)/1024:.0f} KB')

for label, extra in [
    ('默认（auto）', []),
    ('make_zero', ['-avoid_negative_ts', 'make_zero']),
]:
    out = os.path.join(TMP, f'neg_{label}.ts')
    r = subprocess.run([FF, '-v', 'error', '-y', '-i', neg, '-c', 'copy',
                        *extra, '-f', 'mpegts', out],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=300)
    if r.returncode != 0 or not os.path.exists(out):
        print(f'  {label:14} ❌ exit={r.returncode}  {r.stderr[:100]}')
        continue
    # 读第一帧的 PTS
    r2 = subprocess.run([FP, '-v', 'error', '-select_streams', 'v:0',
                         '-show_entries', 'packet=pts_time,dts_time',
                         '-of', 'json', '-read_intervals', '%+#1', out],
                        capture_output=True, text=True, encoding='utf-8',
                        errors='replace', timeout=120)
    first = '?'
    try:
        j = json.loads(r2.stdout or '{}')
        pk = (j.get('packets') or [{}])[0]
        first = f"pts={pk.get('pts_time')} dts={pk.get('dts_time')}"
    except Exception:
        pass
    rc3, nerr, _ = decode_errs(out, label)
    print(f'  {label:14} 首帧 {first}   解码错误 {nerr} 条')

shutil.rmtree(TMP, ignore_errors=True)
print()
print('完成。')
