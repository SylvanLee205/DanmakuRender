"""修正 rerender 造成的嵌套目录，并按规则清理源文件。

问题：
    tools/rerender_after_xml_fix.py 里我这样拼路径：
        out_dir = os.path.join(os.path.dirname(vf), f'{task}（弹幕版）')
    vf 是 '直播回放/vvu/xxx.mkv'，dirname 是 '直播回放/vvu'，
    所以变成 '直播回放/vvu/vvu（弹幕版）' —— 多套了一层任务名。

正确：'直播回放/vvu（弹幕版）'

处理：
    1. 把嵌套目录里的 mp4 移到正确的（弹幕版）目录
    2. 删除空的嵌套目录
    3. 清理已成功渲染上传的源文件 + .ass
       （损坏的那个 21点26分 也一并清理 —— 已确认内容损坏，
         保留只会占 462 MB 且无法使用）
"""
import os
import shutil

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）


UP = _PROJECT_ROOT
REPLAY = os.path.join(UP, '直播回放')

print('=' * 78)
print('1. 找出嵌套目录')
print('=' * 78)
nested = []
for d in sorted(os.listdir(REPLAY)):
    sub = os.path.join(REPLAY, d)
    if not os.path.isdir(sub) or d.endswith('（弹幕版）'):
        continue
    wrong = os.path.join(sub, f'{d}（弹幕版）')
    if os.path.isdir(wrong):
        files = [f for f in os.listdir(wrong) if f.endswith('.mp4')]
        nested.append((d, sub, wrong, files))
        print(f'  ⚠️ {d}\\{d}（弹幕版）\\  ({len(files)} 个 mp4)')

if not nested:
    print('  ✅ 没有嵌套目录')
else:
    print()
    print('=' * 78)
    print('2. 修正：移到正确位置')
    print('=' * 78)
    for task, sub, wrong, files in nested:
        right = os.path.join(REPLAY, f'{task}（弹幕版）')
        os.makedirs(right, exist_ok=True)
        for f in files:
            src = os.path.join(wrong, f)
            dst = os.path.join(right, f)
            if os.path.exists(dst):
                print(f'  跳过（目标已存在）: {f}')
                continue
            shutil.move(src, dst)
            print(f'  ✅ {f}')
            print(f'      {os.path.getsize(dst)/1024/1024:.1f} MB -> {right}')
        # 删空的嵌套目录
        left = os.listdir(wrong)
        if not left:
            os.rmdir(wrong)
            print(f'  已删除空目录: {wrong}')
        else:
            print(f'  ⚠ 目录非空，保留: {wrong} -> {left}')

print()
print('=' * 78)
print('3. 清理源文件（已成功渲染上传）')
print('=' * 78)
# (源文件, .ass, 是否可清理)
TARGETS = [
    (os.path.join(REPLAY, 'vvu', 'vvu-2026年10月15日19点30分.mkv'),
     '已渲染上传 354.3 MB', True),
    (os.path.join(REPLAY, '小鱼大王', '小鱼大王-2026年10月15日21点21分.mkv'),
     '已渲染上传 163.7 MB', True),
    (os.path.join(REPLAY, 'vvu', 'vvu-2026年10月15日21点26分.mkv'),
     '源损坏但已渲染出 32.7 MB 产物并上传', True),
]

freed = 0
for src, why, ok in TARGETS:
    if not os.path.exists(src):
        print(f'  已不存在: {os.path.basename(src)}')
        continue
    stem = os.path.splitext(src)[0]
    dm = stem + '.ass'
    n = os.path.basename(src)
    tdir = os.path.basename(os.path.dirname(src))
    out = os.path.join(REPLAY, f'{tdir}（弹幕版）',
                       stem_b := os.path.basename(stem) + '（弹幕版）.mp4')
    if not ok:
        print(f'  ⏭ 保留: {n}')
        continue
    if not os.path.exists(out):
        print(f'  ⚠ 没有渲染产物，**不删**: {n}')
        continue
    sz = os.path.getsize(src)
    try:
        os.remove(src)
        freed += sz
        print(f'  ✅ 已删源文件 {sz/1024/1024:.1f} MB  {n}')
    except Exception as e:
        print(f'  ❌ 删除失败 {n}: {e}')
        continue
    if os.path.exists(dm):
        try:
            os.remove(dm)
            print(f'      （连带删除弹幕文件 {os.path.basename(dm)}）')
        except Exception as e:
            print(f'      ⚠ 弹幕删除失败: {e}')

print()
print(f'  释放 {freed/1024/1024:.1f} MB')

print()
print('=' * 78)
print('4. 最终目录检查')
print('=' * 78)
for task in ('vvu', '小鱼大王'):
    for suffix in ('', '（弹幕版）'):
        d = os.path.join(REPLAY, task + suffix)
        if not os.path.isdir(d):
            print(f'  {task}{suffix}: 不存在')
            continue
        files = sorted(os.listdir(d))
        print(f'  {task}{suffix}/  ({len(files)} 项)')
        for f in files[:6]:
            p = os.path.join(d, f)
            print(f'      {os.path.getsize(p)/1024/1024:>8.1f} MB  {f}')
        if len(files) > 6:
            print(f'      ... 还有 {len(files)-6} 项')
