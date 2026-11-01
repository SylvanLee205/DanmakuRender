"""测试对 TS 分段录制真正有用的参数组合。"""
import os
import shutil
import subprocess

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）


TMP = _PROJECT_ROOT + r'\.temp\_tsopt_test'
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
FF, FP = 'ffmpeg', 'ffprobe'

mp4 = os.path.join(TMP, 'src.mp4')
subprocess.run([FF, '-v', 'error', '-y',
                '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=22:duration=20',
                '-f', 'lavfi', '-i', 'sine=frequency=440:duration=20',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-g', '22',
                '-c:a', 'aac', '-b:a', '96k', mp4],
               capture_output=True, timeout=300)
flv = os.path.join(TMP, 'src.flv')
subprocess.run([FF, '-v', 'error', '-y', '-i', mp4, '-c', 'copy',
                '-f', 'flv', flv], capture_output=True, timeout=300)

# 复刻 DMR 的分段写法：-f segment -segment_time N -reset_timestamps 1 <output_args> name
CASES = [
    ('① 当前 DMR 默认（mp4 的 -movflags）',
     ['-movflags', 'faststart+frag_keyframe+empty_moov']),
    ('② 无额外参数', []),
    ('③ avoid_negative_ts make_zero', ['-avoid_negative_ts', 'make_zero']),
    ('④ mpegts_flags +resend_headers', ['-mpegts_flags', '+resend_headers']),
    ('⑤ ③+④ 组合（推荐）',
     ['-avoid_negative_ts', 'make_zero', '-mpegts_flags', '+resend_headers']),
]

print('=' * 78)
print('TS 分段录制参数对比（模拟 DMR 的 -f segment 写法）')
print('=' * 78)
for i, (label, extra) in enumerate(CASES):
    pat = os.path.join(TMP, f'case{i}-Part%03d.ts')
    cmd = [FF, '-v', 'warning', '-y', '-i', flv, '-c', 'copy',
           '-f', 'segment', '-segment_time', '8', '-reset_timestamps', '1',
           *extra, pat]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=300)
    parts = sorted(p for p in os.listdir(TMP) if p.startswith(f'case{i}-'))
    errs = [l.strip() for l in (r.stderr or '').split('\n') if l.strip()]
    total = sum(os.path.getsize(os.path.join(TMP, p)) for p in parts)
    # 每段都能解吗
    bad = 0
    for p in parts:
        rr = subprocess.run([FF, '-v', 'error', '-i', os.path.join(TMP, p),
                             '-f', 'null', '-'],
                            capture_output=True, timeout=120)
        if rr.returncode != 0:
            bad += 1
    print(f'  {label}')
    print(f'     exit={r.returncode}  分段 {len(parts)} 个  共 {total/1024:.0f} KB  '
          f'解码失败段 {bad}')
    if errs:
        print(f'     警告/错误 {len(errs)} 条，示例: {errs[0][:95]}')

print()
print('=' * 78)
print('mpegts muxer 的 avoid_negative_ts 默认值')
print('=' * 78)
r = subprocess.run([FF, '-hide_banner', '-h', 'muxer=mpegts'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=60)
for line in (r.stdout or '').split('\n'):
    if 'avoid_negative_ts' in line or 'resend_headers' in line or 'pcr_period' in line:
        print(f'  {line.strip()[:110]}')

shutil.rmtree(TMP, ignore_errors=True)
