"""隔离测试：03点39分.ts 在 字幕滤镜 / noautoscale / 编码器 各组合下是否可用。

每组跑 120 秒，看能否成功。目的是回答：为什么用户自己的 UniversalEncoder
能编码成功（无弹幕），而 DMR 的弹幕渲染总是崩。
"""
import os
import subprocess
import sys

os.chdir(r'F:\DanmakuRender_AutoUp')

SRC = r'直播回放\哭哭不嘻嘻\哭哭不嘻嘻-2026年10月19日03点39分.ts'
ASS = os.path.abspath(r'直播回放\哭哭不嘻嘻\哭哭不嘻嘻-2026年10月19日03点39分.ass')
ASS_FF = ASS.replace('\\', '/').replace(':/', '\\:')

print('=' * 80)
print('隔离测试（每组 120 秒）')
print('=' * 80)
print(f'  源: {SRC}')
print(f'  弹幕: {ASS}')
print()

QSV = ['-c:v', 'hevc_qsv', '-preset', 'medium', '-global_quality:v', '30']
X265 = ['-c:v', 'libx265', '-preset', 'veryfast', '-crf', '28']

CASES = [
    ('A QSV + 字幕 + noautoscale', ['-t', '120', '-i', SRC, '-vf', f"subtitles='{ASS_FF}'",
                                   '-noautoscale'] + QSV + ['-an']),
    ('B QSV + 字幕（无 noautoscale）', ['-t', '120', '-i', SRC, '-vf', f"subtitles='{ASS_FF}'"] + QSV + ['-an']),
    ('C QSV 无字幕 + noautoscale', ['-t', '120', '-i', SRC, '-noautoscale'] + QSV + ['-an']),
    ('D QSV 无字幕（无 noautoscale）', ['-t', '120', '-i', SRC] + QSV + ['-an']),
    ('E x265 + 字幕 + noautoscale', ['-t', '120', '-i', SRC, '-vf', f"subtitles='{ASS_FF}'",
                                     '-noautoscale'] + X265 + ['-an']),
    ('F x265 无字幕', ['-t', '120', '-i', SRC] + X265 + ['-an']),
    ('G 纯解码前120秒（不编码）', ['-t', '120', '-i', SRC, '-f', 'null', '-']),
]

for name, args in CASES:
    out = os.path.join('.temp', '_iso.mp4')
    if os.path.exists(out):
        os.remove(out)
    cmd = ['ffmpeg', '-v', 'error', '-y'] + args
    if args[-1] != '-':
        cmd.append(out)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=900)
        rc = r.returncode
        err = [l for l in (r.stderr or '').split('\n') if l.strip()]
        sz = os.path.getsize(out) / 1024**2 if os.path.exists(out) else 0
        tag = '✅' if rc == 0 else '❌'
        print(f'  {name:34} exit={rc:<12} {sz:7.1f} MB  {tag}')
        if rc != 0:
            for l in err[:2]:
                print(f'       {l[:120]}')
    except subprocess.TimeoutExpired:
        print(f'  {name:34} ⏱ 超时')
    finally:
        if os.path.exists(out):
            os.remove(out)

print()
print('=' * 80)
print('结论要点')
print('=' * 80)
print('  · 若 C/D 成功而 A/B 失败 -> 字幕滤镜是元凶')
print('  · 若 E 失败而 F 成功     -> 字幕滤镜让 x265 崩')
print('  · 若全失败且 G 也失败    -> 源文件本身有问题')
