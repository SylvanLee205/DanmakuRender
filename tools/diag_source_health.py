"""完整解码源文件，统计错误类型，判断是否真的损坏。"""
import collections
import os
import subprocess

SRC = r'F:\DanmakuRepo\直播回放\断尾人类\断尾的人类不会喵-2026年10月18日19点56分.mkv'

print('=' * 74)
print('完整解码源文件（ffmpeg -v error -i <src> -f null -）')
print('=' * 74)
print(f'  文件: {os.path.basename(SRC)}')
print(f'  大小: {os.path.getsize(SRC)/1024**2:.1f} MB')

r = subprocess.run(['ffmpeg', '-v', 'error', '-i', SRC, '-f', 'null', '-'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=1800)
lines = [l.strip() for l in (r.stderr or '').split('\n') if l.strip()]
print(f'  ffmpeg exit: {r.returncode}')
print(f'  stderr 行数: {len(lines)}')

if not lines:
    print()
    print('  ✅ 完整解码零错误 —— 源文件完全健康')
    raise SystemExit(0)

# 分类
cnt = collections.Counter()
samples = {}
for l in lines:
    # 去掉行首的 [xxx @ 0x...] 之类
    key = l
    if '] ' in l:
        key = l.split('] ', 1)[1]
    key = key[:120]
    # 合并同类（去掉具体数字）
    import re
    key = re.sub(r'\d+', 'N', key)
    cnt[key] += 1
    samples.setdefault(key, l)

print()
print('  错误类型分布（数字已归一化）:')
for k, n in cnt.most_common(12):
    print(f'    {n:5} x  {k}')
    print(f'           示例: {samples[k][:130]}')

# 判断严重性
total = len(lines)
fatal = sum(n for k, n in cnt.items()
            if any(w in k for w in ('Invalid', 'corrupt', 'error while',
                                    'Error', 'decode', 'missing')))
print()
print(f'  致命类错误: {fatal} / {total}')
if fatal == 0:
    print('  → 只有警告类（如 DTS 不单调），ffmpeg 能自动修正，文件可用')
else:
    print('  → 存在真正的解码错误，文件部分损坏')
