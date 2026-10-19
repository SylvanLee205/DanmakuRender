"""1) 把降级参数插进 default.yml   2) 测试硬解 + subtitles 是否共存"""
import os
import subprocess
import time

# ── 1) default.yml ──
P = r'F:\DanmakuRender_AutoUp\DMR\Config\default.yml'
src = open(P, encoding='utf-8').read()
if 'hw_retry' in src:
    print('  default.yml: 已存在，跳过')
else:
    lines = src.split('\n')
    block = [
        '    # ── 硬件编码失败时的处理（2026-10-18 魔改版新增）──────────────',
        '    # 硬件编码器（*_qsv/_nvenc/_vaapi/_amf）失败时，先用硬件重试，',
        '    # 全部失败才降级到软件编码器。0 = 不重试，直接降级。',
        '    hw_retry: 2',
        '    # 每次硬件重试前等待秒数（给占用 GPU 的程序让路）',
        '    hw_retry_delay: 60',
        '    # 降级用的软件编码器，置空(~)则不降级（libx265 / libx264）',
        '    fallback_vencoder: libx265',
        '    # 软件编码器参数。实测（60 秒 720x1280 素材）：',
        '    #   QSV gq30 7.0MB/958kbps/12.7s vs veryfast crf28 7.7MB/1053kbps/22.3s',
        "    fallback_vencoder_args: ['-preset', 'veryfast', '-crf', '28', '-tag:v', 'hvc1']",
    ]
    anchor = None
    for i, l in enumerate(lines):
        if l.strip().startswith('output_resize:'):
            anchor = i
            break
    if anchor is None:
        print('  default.yml: 没找到 output_resize 锚点')
    else:
        lines[anchor + 1:anchor + 1] = block
        open(P, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))
        print(f'  default.yml: 已在 output_resize 后插入 {len(block)} 行')

# ── 2) 硬解测试 ──
os.chdir(r'F:\DanmakuRender_AutoUp')
SRC = r'直播回放\断尾人类\断尾的人类不会喵-2026年10月18日19点56分.mkv'
DM = r'直播回放\断尾人类\断尾的人类不会喵-2026年10月18日19点56分.ass'
OUT = r'.temp\_hwdec_test.mp4'

# 复刻 DMR 的转义：反斜杠→正斜杠，冒号→\:
dm_escaped = os.path.abspath(DM).replace('\\', '/').replace(':', '\\:')
VF = "subtitles=filename='%s'" % dm_escaped

print()
print('=' * 74)
print('硬解 + subtitles 滤镜 共存测试（60 秒片段）')
print('=' * 74)
print(f'  vf = {VF}')

cases = [
    ('① 软解（当前 global.yml 的 ~）', []),
    ('② 硬解 auto（default.yml 默认）', ['-hwaccel', 'auto']),
    ('③ 硬解 d3d11va', ['-hwaccel', 'd3d11va']),
    ('④ 硬解 qsv', ['-hwaccel', 'qsv']),
]

results = []
for label, hw in cases:
    if os.path.exists(OUT):
        try:
            os.remove(OUT)
        except OSError:
            pass
    cmd = (['ffmpeg', '-y'] + hw +
           ['-fflags', '+discardcorrupt+genpts',
            '-analyzeduration', '60000000', '-probesize', '100000000',
            '-ss', '600', '-t', '60', '-i', SRC,
            '-vf', VF,
            '-c:v', 'hevc_qsv', '-preset', 'medium', '-global_quality:v', '30',
            '-c:a', 'aac', '-b:a', '96k', OUT])
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=900)
        el = time.time() - t0
        ok = (r.returncode == 0 and os.path.exists(OUT)
              and os.path.getsize(OUT) > 50000)
        sz = os.path.getsize(OUT) / 1024 ** 2 if os.path.exists(OUT) else 0
        print(f'  {label:34} {"✅" if ok else "❌"}  {el:6.1f}s  {sz:5.1f} MB')
        if not ok:
            for l in reversed((r.stderr or '').split('\n')):
                if any(k in l for k in ('rror', 'Invalid', 'No device', 'failed')):
                    print(f'       {l.strip()[:120]}')
                    break
        results.append((label, ok, el, sz))
    except subprocess.TimeoutExpired:
        print(f'  {label:34} ⏱ 超时')
        results.append((label, False, 900, 0))

print()
base = next((r for r in results if r[1] and '①' in r[0]), None)
if base:
    print('  相对软解的速度:')
    for label, ok, el, sz in results:
        if ok and '①' not in label:
            print(f'    {label:34} {el/base[2]:.2f}x  体积 {sz/base[3]*100:.0f}%')
if os.path.exists(OUT):
    os.remove(OUT)
