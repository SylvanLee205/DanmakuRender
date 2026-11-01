"""实测：截断的 .ts vs .flv 哪个还能用。

结论将决定"ffmpeg+ts 丢失中断恢复"到底是不是真损失。
"""
import os
import shutil
import subprocess
import sys

TMP = r'F:\DanmakuRepo\.temp\_trunc_test'
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)

# 造一段 20 秒、620x360、有画面变化的测试素材
SRC = os.path.join(TMP, '_src.mp4')
print('=' * 74)
print('截断容错实测：.ts vs .flv')
print('=' * 74)

subprocess.run(['ffmpeg', '-v', 'error', '-y',
                '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=22:duration=20',
                '-f', 'lavfi', '-i', 'sine=frequency=440:duration=20',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-g', '44',
                '-c:a', 'aac', '-b:a', '96k', SRC],
               capture_output=True, timeout=300)
print(f'  测试素材: {os.path.getsize(SRC)/1024:.0f} KB / 20 秒')


def make(kind, out):
    """生成指定容器。"""
    cmd = ['ffmpeg', '-v', 'error', '-y', '-i', SRC, '-c', 'copy']
    if kind == 'ts':
        cmd += ['-f', 'mpegts', out]
    elif kind == 'flv':
        cmd += ['-f', 'flv', out]
    elif kind == 'mkv':
        cmd += ['-f', 'matroska', out]
    subprocess.run(cmd, capture_output=True, timeout=300)
    return out


def truncate(path, ratio=0.5):
    """截断到指定比例，模拟崩溃。"""
    size = os.path.getsize(path)
    keep = int(size * ratio)
    with open(path, 'r+b') as f:
        f.truncate(keep)
    return keep


def probe_and_decode(path, label):
    """能不能探测 + 能不能完整解码。"""
    # ffprobe
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                        'format=format_name,duration',
                        '-show_entries', 'stream=codec_type',
                        '-of', 'json', path],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=120)
    import json
    ok_probe = False
    fmt = dur = '?'
    nstream = 0
    if r.returncode == 0:
        try:
            j = json.loads(r.stdout)
            fmt = (j.get('format') or {}).get('format_name', '?')
            dur = (j.get('format') or {}).get('duration', '?')
            nstream = len(j.get('streams') or [])
            ok_probe = nstream > 0
        except Exception:
            pass
    # 解码到 null
    r2 = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'null', '-'],
                        capture_output=True, text=True, encoding='utf-8',
                        errors='replace', timeout=300)
    ok_decode = (r2.returncode == 0)
    # 数一下能解出多少帧
    r3 = subprocess.run(['ffmpeg', '-v', 'error', '-i', path,
                         '-map', '0:v:0', '-c', 'copy', '-f', 'null', '-'],
                        capture_output=True, text=True, encoding='utf-8',
                        errors='replace', timeout=300)
    errlines = len([l for l in (r2.stderr or '').split('\n') if l.strip()])
    return {
        'label': label, 'probe': ok_probe, 'fmt': fmt,
        'dur': dur, 'streams': nstream,
        'decode': ok_decode, 'errs': errlines,
    }


print()
print('  生成三种容器的完整版，再各截断到 50%：')
rows = []
for kind in ('ts', 'flv', 'mkv'):
    p = os.path.join(TMP, f'full.{kind}')
    try:
        make(kind, p)
    except Exception as e:
        print(f'    {kind}: 生成失败 {e}')
        continue
    orig = os.path.getsize(p)
    truncate(p, 0.5)
    now = os.path.getsize(p)
    res = probe_and_decode(p, kind)
    res['orig'] = orig
    res['now'] = now
    rows.append(res)
    print(f'    {kind:4} 完整 {orig/1024:6.0f} KB -> 截断 {now/1024:6.0f} KB')

print()
print('=' * 74)
print('截断后还能不能用')
print('=' * 74)
print(f'  {"容器":6} {"ffprobe":>9} {"format_name":>14} {"时长":>10} {"流数":>5} {"能解码":>8} {"错误行":>7}')
print('  ' + '-' * 66)
for r in rows:
    print(f'  {r["label"]:6} {"✅" if r["probe"] else "❌":>8} {str(r["fmt"])[:14]:>14} '
          f'{str(r["dur"])[:10]:>10} {r["streams"]:>5} '
          f'{"✅" if r["decode"] else "❌":>7} {r["errs"]:>7}')

print()
print('=' * 74)
print('结论')
print('=' * 74)
for r in rows:
    usable = r['probe'] and r['decode']
    print(f'  {r["label"]:4}: {"✅ 截断后仍可探测+解码（可直接重命名入库）" if usable else "❌ 截断后不可用（需要修复才能用）"}')

# 清理
shutil.rmtree(TMP, ignore_errors=True)
