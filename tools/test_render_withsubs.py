"""带上 subtitles 滤镜重测，复现真实渲染条件。"""
import os
import subprocess
import time

SRC = r'F:\DanmakuRender_AutoUp\直播回放\断尾人类\断尾的人类不会喵-2026年10月18日19点56分.mkv'
DM = r'F:\DanmakuRender_AutoUp\直播回放\断尾人类\断尾的人类不会喵-2026年10月18日19点56分.ass'
OUTDIR = r'F:\DanmakuRender_AutoUp\.temp'
os.makedirs(OUTDIR, exist_ok=True)

# DMR 的路径转义方式：把 : 转成 \: ，反斜杠转正斜杠
def esc(p):
    return p.replace('\\', '/').replace(':', r'\:')

VF = f"subtitles=filename='{esc(DM)}'"

BASE_IN = ['-fflags', '+discardcorrupt+genpts',
           '-analyzeduration', '60000000', '-probesize', '100000000']

# 用输入 seek（和 DMR 不同：DMR 是全量解码）。两种都测。
CASES = [
    ('A. qsv + subtitles，输入seek 1980s+90s',
     ['-ss', '1980', '-t', '90'], ['-c:v', 'hevc_qsv', '-g', '88',
                                   '-preset', 'medium', '-global_quality:v', '30']),
    ('B. qsv + subtitles + cfr，输入seek',
     ['-ss', '1980', '-t', '90'], ['-c:v', 'hevc_qsv', '-g', '88',
                                   '-preset', 'medium', '-global_quality:v', '30',
                                   '-fps_mode', 'cfr']),
    ('C. qsv + subtitles，输出seek（-ss 在 -i 之后，行为更接近全量）',
     ['-ss', '1980', '-t', '90'], ['-c:v', 'hevc_qsv', '-g', '88',
                                   '-preset', 'medium', '-global_quality:v', '30']),
]

print('=' * 74)
print('带 subtitles 滤镜测试')
print('=' * 74)
print(f'  vf: {VF}')
print(f'  弹幕存在: {os.path.exists(DM)}  {os.path.getsize(DM)/1024:.0f} KB')
print()

results = []
for i, (name, seek, vargs) in enumerate(CASES):
    out = os.path.join(OUTDIR, f'_t{i}.mp4')
    if os.path.exists(out):
        os.remove(out)
    # C 用输出 seek（-ss 放 -i 后面）
    if name.startswith('C.'):
        cmd = ['ffmpeg', '-y', *BASE_IN, '-i', SRC, *seek,
               '-vf', VF, *vargs, '-c:a', 'aac', '-b:a', '96k', out]
    else:
        cmd = ['ffmpeg', '-y', *BASE_IN, *seek, '-i', SRC,
               '-vf', VF, *vargs, '-c:a', 'aac', '-b:a', '96k', out]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=900)
        el = time.time() - t0
        sz = os.path.getsize(out) if os.path.exists(out) else 0
        ok = (r.returncode == 0 and sz > 100 * 1024)
        lines = [l.strip() for l in (r.stderr or '').split('\n') if l.strip()]
        err = ''
        for l in reversed(lines):
            if any(k in l for k in ('rror', 'Invalid', 'failed', 'Failed', 'FrameType')):
                err = l[:120]
                break
        results.append((name, ok, el, sz, r.returncode, err))
        print(f'  {name}')
        print(f'    {"✅ 成功" if ok else "❌ 失败"}  exit={r.returncode}  '
              f'{el:.1f}s  {sz/1024**2:.1f} MB')
        if err:
            print(f'    错误: {err}')
        print()
    except subprocess.TimeoutExpired:
        results.append((name, False, 900, 0, -1, '超时'))
        print(f'  {name}: ⏱ 超时\n')
    finally:
        try:
            if os.path.exists(out):
                os.remove(out)
        except Exception:
            pass

print('=' * 74)
bad = [r for r in results if not r[1]]
print(f'  失败 {len(bad)} / {len(results)}')
for n, _, _, _, _, e in bad:
    print(f'    ❌ {n}: {e}')
