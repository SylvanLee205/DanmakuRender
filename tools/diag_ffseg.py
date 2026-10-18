"""精准复现 DMR 的 ffmpeg 下载命令，定位卡住的原因。

怀疑点：`-avoid_negative_ts` 与 `-f segment` 组合。
"""
import os
import subprocess
import sys

sys.path.insert(0, r'F:\DanmakuRender_AutoUp')
os.chdir(r'F:\DanmakuRender_AutoUp')
import logging
logging.basicConfig(level=logging.CRITICAL)

from DMR.Config import Config
from DMR.LiveAPI import LiveAPI

cfg = Config(r'F:\DanmakuRender_AutoUp\configs\global.yml')
da = cfg.replay_config['_引擎测试']['download_args']
adv = da.get('advanced_video_args') or {}
stream_args = adv.get('ffmpeg_stream_args') or []
out_args = adv.get('ffmpeg_output_args') or []

api = LiveAPI('douyin', '765184155745')
hdr = api.GetStreamHeader()
header_str = ''.join('%s: %s\r\n' % x for x in (hdr or {}).items())

OUTDIR = os.path.join('.temp', '_ffseg')
os.makedirs(OUTDIR, exist_ok=True)


def build(out_args_override, use_segment=True, name='x'):
    url = api.GetStreamURL()
    a = ['ffmpeg', '-y', '-headers', header_str, *stream_args,
         '-i', str(url), '-c', 'copy']
    if use_segment:
        a += ['-f', 'segment', '-segment_time', '20', '-reset_timestamps', '1']
    a += list(out_args_override)
    a += [os.path.join(OUTDIR, name + '-Part%03d.ts')]
    return a


CASES = [
    ('A. DMR 现状（含 -avoid_negative_ts + -c copy）',
     ['-c', 'copy', '-avoid_negative_ts', 'make_zero']),
    ('B. 只 -c copy（去掉 avoid_negative_ts）', ['-c', 'copy']),
    ('C. 空输出参数（完全默认）', []),
    ('D. 只 -avoid_negative_ts（含 -f segment）',
     ['-avoid_negative_ts', 'make_zero']),
]

print('=' * 78)
print('复现 DMR 的 ffmpeg 下载命令（每例限时 35 秒，segment=20s）')
print('=' * 78)

for i, (label, oa) in enumerate(CASES):
    for f in os.listdir(OUTDIR):
        try:
            os.remove(os.path.join(OUTDIR, f))
        except OSError:
            pass
    cmd = build(oa, name=f'case{i}')
    print()
    print(f'  {label}')
    print(f'    输出参数: {oa}')
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=35)
        parts = sorted(f for f in os.listdir(OUTDIR) if f.startswith(f'case{i}'))
        total = sum(os.path.getsize(os.path.join(OUTDIR, p)) for p in parts)
        print(f'    exit={r.returncode}  分段 {len(parts)} 个  共 {total/1024:.0f} KB')
        err = [l.strip() for l in (r.stderr or '').split('\n')
               if l.strip() and ('rror' in l or 'Invalid' in l or 'not found' in l
                                 or 'Unrecognized' in l or 'failed' in l)]
        if err:
            print(f'    ❌ 错误 {len(err)} 条:')
            for l in err[:4]:
                print(f'        {l[:140]}')
        else:
            print(f'    ✅ 无错误')
    except subprocess.TimeoutExpired as e:
        parts = sorted(f for f in os.listdir(OUTDIR) if f.startswith(f'case{i}'))
        total = sum(os.path.getsize(os.path.join(OUTDIR, p)) for p in parts)
        print(f'    ⏱ 35 秒超时（正在拉流）。分段 {len(parts)} 个 共 {total/1024:.0f} KB')
        if e.stderr:
            tail = e.stderr if isinstance(e.stderr, str) else e.stderr.decode('utf-8', 'replace')
            lines = [l.strip() for l in tail.split('\n') if l.strip()]
            for l in lines[-3:]:
                print(f'        {l[:130]}')

# 清理
for f in os.listdir(OUTDIR):
    try:
        os.remove(os.path.join(OUTDIR, f))
    except OSError:
        pass
os.rmdir(OUTDIR)
