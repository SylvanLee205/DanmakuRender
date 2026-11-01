"""比对孤儿3 与已入库分段是否为同一内容（抽帧比对）。

方法：
  孤儿3:    00:30:37 ~ 00:38:22 (7.8 分钟)
  已入库:   00:20:38 ~ 00:38:50 (17.7 分钟)  <- 后 8 分钟与孤儿3 时段重叠

  取孤儿3 的第 1/3/5/7 分钟抽帧，和已入库分段里"对应时刻"的帧比。
  已入库分段的第 10 分钟 ≈ 00:30:38，正好对应孤儿3 的起点。

  用 ffmpeg 的 SSIM/PSNR 滤镜做客观比对：
    如果 SSIM 接近 1.0 -> 同一内容（重复）
    SSIM 很低        -> 不同内容（两路流拍到了不同画面？）
"""
import os
import re
import subprocess
import tempfile

D = r'F:\DanmakuRepo\直播回放\哭哭不嘻嘻'
DM = r'F:\DanmakuRepo\直播回放\哭哭不嘻嘻（弹幕版）'

orphan3 = None
for f in os.listdir(D):
    if '20261008003037' in f and f.endswith('.flv'):
        orphan3 = os.path.join(D, f)
        break

target = None
for f in os.listdir(DM):
    if '10月08日00点20分' in f and f.endswith('.mp4'):
        target = os.path.join(DM, f)
        break

print('=' * 78)
print('待比对文件')
print('=' * 78)
print(f'  孤儿3:  {orphan3}')
print(f'  已入库: {target}')
if not (orphan3 and target):
    print('  ❌ 文件缺失，无法比对')
    raise SystemExit(1)

print()
print('=' * 78)
print('1. 抽帧位置计算')
print('=' * 78)
# 孤儿3 起点 = 00:30:37；已入库起点 = 00:20:38（按文件名的"00点20分"）
# 但已入库的实际录制起点无法精确知道，先用"文件名时间"近似
# 更稳妥：直接比对两段视频的**前 N 分钟**（孤儿3 从头，已入库从 10 分钟处）
offsets = [0, 60, 120, 180, 240, 300, 360, 420]
print(f'  孤儿3 取 t = {offsets} 秒')
print(f'  已入库 取 t = {[o + 600 for o in offsets]} 秒  (假设已入库比孤儿3 早 10 分钟)')
print()
print('  注：已入库时长 17.7 分钟 = 1062 秒，所以 +600 后最大 1020 秒，在范围内')

tmpdir = tempfile.mkdtemp(prefix='cmp_frames_')
print()
print('=' * 78)
print('2. 逐个抽帧并用 SSIM 比对')
print('=' * 78)
results = []
for off in offsets:
    a = os.path.join(tmpdir, f'a_{off}.png')
    b = os.path.join(tmpdir, f'b_{off}.png')
    # 抽孤儿3 的帧
    r1 = subprocess.run(['ffmpeg', '-y', '-v', 'error', '-ss', str(off),
                         '-i', orphan3, '-frames:v', '1',
                         '-vf', 'scale=320:-1', a],
                        capture_output=True, text=True, timeout=300)
    # 抽已入库的帧
    r2 = subprocess.run(['ffmpeg', '-y', '-v', 'error', '-ss', str(off + 600),
                         '-i', target, '-frames:v', '1',
                         '-vf', 'scale=320:-1', b],
                        capture_output=True, text=True, timeout=300)
    ok_a, ok_b = os.path.exists(a), os.path.exists(b)
    if not (ok_a and ok_b):
        print(f'  t={off:>4}s  抽帧失败  a={ok_a} b={ok_b}  '
              f'{(r1.stderr or "")[:60]} {(r2.stderr or "")[:60]}')
        continue
    # SSIM 比对
    r3 = subprocess.run(['ffmpeg', '-v', 'info', '-i', a, '-i', b,
                         '-lavfi', 'ssim', '-f', 'null', '-'],
                        capture_output=True, text=True, timeout=300)
    m = re.search(r'SSIM.*?All:([\d.]+)', r3.stderr or '')
    ssim = float(m.group(1)) if m else None
    # 文件大小也作为参考（同画面大小应接近）
    sa, sb = os.path.getsize(a), os.path.getsize(b)
    verdict = ''
    if ssim is not None:
        if ssim > 0.95:
            verdict = '🔴 同一内容（重复）'
        elif ssim > 0.80:
            verdict = '🟠 很可能同一画面（有压缩/缩放差异）'
        else:
            verdict = '🟢 不同内容'
    print(f'  t={off:>4}s  SSIM={ssim if ssim is not None else "?"}  '
          f'({sa}B vs {sb}B)  {verdict}')
    results.append((off, ssim))

print()
print('=' * 78)
print('3. 结论')
print('=' * 78)
valid = [s for _, s in results if s is not None]
if valid:
    avg = sum(valid) / len(valid)
    print(f'  平均 SSIM: {avg:.4f}')
    if avg > 0.95:
        print('  🔴 孤儿3 与已入库分段是**同一内容**（重复录制）')
        print('     -> 抢救它会重复上传，建议跳过或删掉')
    elif avg > 0.80:
        print('  🟠 画面高度相似，大概率是同一内容的不同编码/时间偏移')
        print('     -> 建议先不抢救，避免冗余')
    else:
        print('  🟢 内容明显不同，孤儿3 是独立片段')
        print('     -> 值得抢救')
else:
    print('  ⚠ 无法得出 SSIM 结论')

import shutil
shutil.rmtree(tmpdir, ignore_errors=True)
