"""重渲染断尾人类 2026-10-18 19:56 那个分段（用 DMR 原始参数）。

背景：20:56 首次渲染在 33:47 处失败（hevc_qsv Invalid FrameType:0 / -1094995529），
留下 270MB 残缺产物（已删）。源文件完整解码 0 致命错误，失败不可复现。
用完全相同的参数重跑一次。
"""
import os
import re
import subprocess
import sys
import time

os.chdir(r'F:\DanmakuRender_AutoUp')

SRC = r'./直播回放/断尾人类\断尾的人类不会喵-2026年10月18日19点56分.mkv'
DM_RAW = r'./直播回放/断尾人类\断尾的人类不会喵-2026年10月18日19点56分.ass'
OUT = r'./直播回放/断尾人类（弹幕版）\断尾的人类不会喵-2026年10月18日19点56分（弹幕版）.mp4'

# 复刻 DMR 的 subtitles 路径转义：反斜杠→正斜杠，冒号转义
vf_path = DM_RAW.replace('\\', '/').replace(':', r'\:')
VF = f"subtitles=filename='{vf_path}'"

args = [
    'ffmpeg', '-y',
    '-fflags', '+discardcorrupt+genpts',
    '-analyzeduration', '2147483647',
    '-probesize', '2147483647',
    '-i', SRC,
    '-vf', VF,
    '-c:v', 'hevc_qsv', '-g', '88', '-preset', 'medium',
    '-global_quality:v', '30', '-tag:v', 'hvc1', '-movflags', '+faststart',
    '-c:a', 'libopus', '-b:a', '96k', '-vbr:a', 'on',
    '-noautoscale',
    OUT,
]

print('=' * 74)
print('重渲染 断尾人类-2026年10月18日19点56分')
print('=' * 74)
for p in (SRC, DM_RAW):
    print(f'  存在: {os.path.exists(p)}  {p}')
if os.path.exists(OUT):
    print(f'  输出已存在，先删除: {os.path.getsize(OUT)/1024**2:.1f} MB')
    os.remove(OUT)
print()
print('  命令:')
print('    ' + ' '.join(args))
print()
print('  开始渲染（约 5 分钟）...')

t0 = time.time()
# 把 ffmpeg 的进度输出写到 .temp 供观察
logp = os.path.join('.temp', '_rerender_duanwei.log')
with open(logp, 'wb') as lf:
    r = subprocess.run(args, stdout=lf, stderr=subprocess.STDOUT, timeout=3600)
el = time.time() - t0

print(f'  完成: exit={r.returncode}  耗时 {el/60:.1f} 分钟')

# 读尾部日志
tail = ''
try:
    with open(logp, 'rb') as f:
        data = f.read()
    tail = data.decode('utf-8', errors='replace')
except Exception:
    pass
lines = [l.strip() for l in tail.split('\n') if l.strip()]
print()
print('  ffmpeg 输出尾部（最后 8 行）:')
for l in lines[-8:]:
    print(f'    {l[:130]}')

# 校验产物
print()
print('=' * 74)
print('产物校验')
print('=' * 74)
if not os.path.exists(OUT):
    print('  ❌ 没有产物')
    sys.exit(1)

sz = os.path.getsize(OUT)
print(f'  大小: {sz/1024**2:.1f} MB')


def dur(p):
    rr = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                         'format=duration', '-of',
                         'default=nw=1:nk=1', p],
                        capture_output=True, text=True, encoding='utf-8',
                        errors='replace', timeout=300)
    try:
        return float((rr.stdout or '0').strip() or 0)
    except ValueError:
        return 0.0


sd = dur(SRC.replace('/', os.sep))
od = dur(OUT.replace('/', os.sep))
print(f'  源时长:   {sd:.0f} 秒')
print(f'  产物时长: {od:.0f} 秒')
if sd > 0:
    ratio = od / sd
    print(f'  比例:     {ratio*100:.1f}%')
    if ratio >= 0.9:
        print('  ✅ 时长正常（>=90%），渲染成功')
    else:
        print('  ❌ 仍然残缺')
        sys.exit(1)
