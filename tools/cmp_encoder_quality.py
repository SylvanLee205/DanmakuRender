"""对比 QSV 硬件编码 与 libx265 各 CRF 的体积/速度，找出等价位。

目标：软编码要"体积和画质"接近当前的
      hevc_qsv -preset medium -global_quality:v 30
"""
import os
import subprocess
import time

SRC = r'F:\DanmakuRepo\直播回放\断尾人类\断尾的人类不会喵-2026年10月18日19点56分.mkv'
OUTDIR = r'F:\DanmakuRepo\.temp'
os.makedirs(OUTDIR, exist_ok=True)

# 取一段 60 秒（避开开头，取 600s 处，画面有变化）
SS, T = '600', '60'

BASE = ['-fflags', '+discardcorrupt+genpts',
        '-analyzeduration', '60000000', '-probesize', '100000000',
        '-ss', SS, '-t', T, '-i', SRC]

CASES = [
    # (标签, 编码参数)
    ('QSV medium gq30（当前配置）',
     ['-c:v', 'hevc_qsv', '-preset', 'medium', '-global_quality:v', '30']),
    ('QSV medium gq32',
     ['-c:v', 'hevc_qsv', '-preset', 'medium', '-global_quality:v', '32']),
    ('libx265 veryfast crf30',
     ['-c:v', 'libx265', '-preset', 'veryfast', '-crf', '30']),
    ('libx265 veryfast crf28',
     ['-c:v', 'libx265', '-preset', 'veryfast', '-crf', '28']),
    ('libx265 veryfast crf32',
     ['-c:v', 'libx265', '-preset', 'veryfast', '-crf', '32']),
    ('libx265 medium crf30',
     ['-c:v', 'libx265', '-preset', 'medium', '-crf', '30']),
]

print('=' * 78)
print(f'编码方案对比（源 {os.path.basename(SRC)}，取 {SS}s 起 {T}s）')
print('=' * 78)
print(f'  {"方案":32} {"体积MB":>9} {"耗时s":>8} {"倍数":>6} {"码率kbps":>10}')
print('-' * 78)

results = []
base_time = None
for i, (label, vargs) in enumerate(CASES):
    out = os.path.join(OUTDIR, f'_cmp{i}.mp4')
    if os.path.exists(out):
        os.remove(out)
    cmd = ['ffmpeg', '-y', *BASE, *vargs, '-c:a', 'aac', '-b:a', '96k', out]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=1800)
        el = time.time() - t0
        if r.returncode != 0 or not os.path.exists(out):
            err = ''
            for l in reversed((r.stderr or '').split('\n')):
                if 'rror' in l or 'Invalid' in l or 'failed' in l:
                    err = l.strip()[:70]
                    break
            print(f'  {label:32} {"失败":>9} {"-":>8} {"-":>6}  {err}')
            results.append((label, None, el, None))
            continue
        sz = os.path.getsize(out) / 1024 ** 2
        kbps = os.path.getsize(out) * 8 / 1024 / float(T)
        if 'QSV medium gq30' in label:
            base_time = el
        mult = (el / base_time) if base_time else 0
        print(f'  {label:32} {sz:9.1f} {el:8.1f} {"-" if not mult else f"{mult:5.1f}x":>6} {kbps:10.0f}')
        results.append((label, sz, el, kbps))
    except subprocess.TimeoutExpired:
        print(f'  {label:32} {"超时":>9}')
        results.append((label, None, 1800, None))
    finally:
        try:
            if os.path.exists(out):
                os.remove(out)
        except Exception:
            pass

print('-' * 78)
print()
# 找体积最接近 QSV gq30 的 libx265 方案
qsv = next((r for r in results if 'QSV medium gq30' in r[0] and r[1]), None)
if qsv:
    qsz, qt = qsv[1], qsv[2]
    print(f'  基准（QSV gq30）: {qsz:.1f} MB, {qt:.1f}s')
    print()
    print('  体积最接近的 libx265 方案:')
    cands = [r for r in results if 'libx265' in r[0] and r[1]]
    cands.sort(key=lambda x: abs(x[1] - qsz))
    for label, sz, el, kbps in cands[:3]:
        diff = (sz - qsz) / qsz * 100
        print(f'    {label:32} {sz:6.1f} MB ({diff:+.1f}%)  {el:5.1f}s ({el/qt:.1f}x 慢)')
else:
    print('  QSV 方案失败（GPU 被占用），无法对比')
