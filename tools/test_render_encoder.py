"""在渲染失败点附近（33:45）做短片段测试，找出能成功的编码方案。

失败日志：
    [hevc_qsv] Invalid FrameType:0.
    Error submitting video frame to the encoder
    Task finished with error code: -1094995529

源文件本身解码无错（539 条都是 DTS 警告，0 条致命错误）。
所以问题在编码器，不在素材。测试几种组合：
  A. hevc_qsv + 默认（复现失败）
  B. hevc_qsv + -fps_mode cfr（时间戳归一化）
  C. hevc_qsv + -err_detect ignore_err + cfr
  D. libx265 软编码（最稳，最慢）
"""
import os
import subprocess
import time

SRC = r'F:\DanmakuRepo\直播回放\断尾人类\断尾的人类不会喵-2026年10月18日19点56分.mkv'
DM = r'F:\DanmakuRepo\直播回放\断尾人类\断尾的人类不会喵-2026年10月18日19点56分.ass'
OUTDIR = r'F:\DanmakuRepo\.temp'
os.makedirs(OUTDIR, exist_ok=True)

# 失败点在 33:45 左右（2025 秒）。取 1980 起 90 秒覆盖它。
START = '1980'
DUR = '90'

BASE_IN = ['-fflags', '+discardcorrupt+genpts',
           '-analyzeduration', '60000000', '-probesize', '100000000']

CASES = [
    ('A. hevc_qsv 默认（复现失败）', ['-c:v', 'hevc_qsv', '-g', '88',
                                 '-preset', 'medium', '-global_quality:v', '30']),
    ('B. hevc_qsv + fps_mode cfr', ['-c:v', 'hevc_qsv', '-g', '88',
                                    '-preset', 'medium', '-global_quality:v', '30',
                                    '-fps_mode', 'cfr']),
    ('C. hevc_qsv + cfr + ignore_err', ['-err_detect', 'ignore_err',
                                       '-c:v', 'hevc_qsv', '-g', '88',
                                       '-preset', 'medium', '-global_quality:v', '30',
                                       '-fps_mode', 'cfr']),
    ('D. libx265 软编码（最稳）', ['-c:v', 'libx265', '-g', '88',
                              '-preset', 'veryfast', '-crf', '30']),
]

print('=' * 74)
print(f'短片段编码测试（源 {os.path.basename(SRC)}，从 {START}s 起 {DUR}s）')
print('=' * 74)

results = []
for name, vargs in CASES:
    out = os.path.join(OUTDIR, f'_test_{abs(hash(name)) % 10000}.mp4')
    if os.path.exists(out):
        os.remove(out)
    cmd = ['ffmpeg', '-y', *BASE_IN, '-ss', START, '-t', DUR, '-i', SRC,
           *vargs, '-c:a', 'aac', '-b:a', '96k', out]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=900)
        el = time.time() - t0
        sz = os.path.getsize(out) if os.path.exists(out) else 0
        ok = (r.returncode == 0 and sz > 100 * 1024)
        # 取最后一条错误
        lines = [l.strip() for l in (r.stderr or '').split('\n') if l.strip()]
        errline = ''
        for l in reversed(lines):
            if any(k in l for k in ('rror', 'Invalid', 'failed', 'Failed')):
                errline = l[:110]
                break
        results.append((name, ok, el, sz, r.returncode, errline))
        print()
        print(f'  {name}')
        print(f'    {"✅ 成功" if ok else "❌ 失败"}  exit={r.returncode}  '
              f'耗时 {el:.1f}s  产物 {sz/1024**2:.1f} MB')
        if errline:
            print(f'    最后错误: {errline}')
    except subprocess.TimeoutExpired:
        results.append((name, False, 900, 0, -1, '超时'))
        print(f'  {name}: ⏱ 超时')
    finally:
        # 清理测试产物
        try:
            if os.path.exists(out):
                os.remove(out)
        except Exception:
            pass

print()
print('=' * 74)
print('结论')
print('=' * 74)
ok_cases = [r for r in results if r[1]]
if ok_cases:
    print(f'  ✅ 可行的方案（{len(ok_cases)} 个）:')
    for n, _, el, sz, _, _ in ok_cases:
        print(f'     {n}   （90 秒耗时 {el:.1f}s）')
    print()
    print('  推荐：优先用 C（QSV + cfr + ignore_err），失败再退回 D（libx265）')
else:
    print('  ❌ 全部失败 —— 需要先重封装修正时间戳再渲染')
