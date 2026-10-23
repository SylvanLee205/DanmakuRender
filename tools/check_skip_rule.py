"""检查指定视频是否命中「跳过上传」规则。

规则（global.yml render_args.dmrender.skip_upload_rule）：
    skip_landscape:        true      跳过横屏
    skip_require_landscape:true      判定依据：必须确认是横屏才跳过
    skip_bitrate_kbps:     2500      码率阈值
    skip_fps:              40        帧率阈值
    skip_min_matches:      1         命中几条才跳过
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, r'F:\DanmakuRender_AutoUp')
os.chdir(r'F:\DanmakuRender_AutoUp')

import yaml

TARGETS = [
    r'直播回放\小鱼大王（弹幕版）\小鱼大王-2026年10月17日22点35分（弹幕版）.mp4',
    r'直播回放\小鱼大王（弹幕版）\小鱼大王-2026年10月17日23点35分（弹幕版）.mp4',
    r'直播回放\小鱼大王（弹幕版）\小鱼大王-2026年10月18日00点08分（弹幕版）.mp4',
]

cfg = yaml.safe_load(open('configs/global.yml', encoding='utf-8'))
rule = ((cfg.get('render_args') or {}).get('dmrender') or {}).get('skip_upload_rule') or {}
print('=' * 78)
print('跳过上传规则')
print('=' * 78)
for k, v in rule.items():
    print(f'  {k} = {v}')

FFPROBE = 'ffprobe'


def probe(path):
    r = subprocess.run([FFPROBE, '-v', 'error', '-print_format', 'json',
                        '-show_streams', '-show_format', path],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=120)
    if r.returncode != 0:
        return None, (r.stderr or '')[:200]
    try:
        return json.loads(r.stdout), None
    except Exception as e:
        return None, str(e)


print()
print('=' * 78)
print('逐个检查')
print('=' * 78)
for rel in TARGETS:
    p = os.path.abspath(rel)
    name = os.path.basename(p)
    print()
    print(f'  ── {name} ──')
    if not os.path.exists(p):
        print('     ❌ 文件不存在')
        continue
    size_mb = os.path.getsize(p) / 1024 ** 2
    j, err = probe(p)
    if err:
        print(f'     ⚠️ ffprobe 失败: {err}')
        continue
    v = next((s for s in j.get('streams', []) if s.get('codec_type') == 'video'), None)
    if not v:
        print('     ⚠️ 没有视频流')
        continue
    w, h = v.get('width'), v.get('height')
    rate = v.get('r_frame_rate') or v.get('avg_frame_rate') or '0/0'
    try:
        num, _, den = rate.partition('/')
        fps = float(num) / float(den or 1)
    except Exception:
        fps = 0.0
    dur = float((j.get('format') or {}).get('duration') or 0)
    bitrate_kbps = (os.path.getsize(p) * 8 / 1024) / dur if dur > 0 else 0

    print(f'     分辨率: {w}x{h}')
    print(f'     帧率:   {fps:.2f} fps')
    print(f'     时长:   {dur/60:.1f} 分钟')
    print(f'     体积:   {size_mb:.1f} MB')
    print(f'     码率:   {bitrate_kbps:.0f} kbps')

    # 逐条判定
    matched = []
    print('     命中判定:')
    is_landscape = bool(w and h and w > h)
    if rule.get('skip_landscape'):
        if is_landscape:
            matched.append('skip_landscape')
            print(f'        ✅ 横屏（{w}>{h}）→ 命中 skip_landscape')
        else:
            print(f'        ✗  竖屏（{w}<={h}）→ 不命中 skip_landscape')
    if rule.get('skip_bitrate_kbps'):
        th = rule['skip_bitrate_kbps']
        if bitrate_kbps >= th:
            matched.append('skip_bitrate')
            print(f'        ✅ 码率 {bitrate_kbps:.0f} >= {th} → 命中 skip_bitrate')
        else:
            print(f'        ✗  码率 {bitrate_kbps:.0f} < {th} → 不命中')
    if rule.get('skip_fps'):
        th = rule['skip_fps']
        if fps >= th:
            matched.append('skip_fps')
            print(f'        ✅ 帧率 {fps:.1f} >= {th} → 命中 skip_fps')
        else:
            print(f'        ✗  帧率 {fps:.1f} < {th} → 不命中')

    need = int(rule.get('skip_min_matches') or 1)
    print()
    if len(matched) >= need:
        print(f'     🟢 结论：命中 {len(matched)} 条（阈值 {need}）→ **应该跳过上传，没上传是正常的**')
    else:
        print(f'     🔴 结论：只命中 {len(matched)} 条（阈值 {need}）→ **不该跳过，应该补传**')
