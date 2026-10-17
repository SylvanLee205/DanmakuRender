"""找出渲染失败后永久滞留的源文件（对应的弹幕版不存在 = 渲染没成功）。

⚠️ 这是只读分析，只列出不改动。删除前必须人工确认。
"""
import glob
import os
import re

REPLAY = r'F:\DanmakuRender_AutoUp\直播回放'


def date_of(name):
    m = re.search(r'(\d{4})年(\d{2})月(\d{2})日', name)
    return f'{m.group(1)}-{m.group(2)}-{m.group(3)}' if m else None


print('=' * 78)
print('渲染失败后滞留的源文件（源在、弹幕版不在）')
print('=' * 78)

total_n, total_b = 0, 0
rows = []
for d in sorted(os.listdir(REPLAY)):
    src_dir = os.path.join(REPLAY, d)
    if not os.path.isdir(src_dir) or d.endswith('（弹幕版）'):
        continue
    dm_dir = os.path.join(REPLAY, d + '（弹幕版）')
    dm_files = set(os.listdir(dm_dir)) if os.path.isdir(dm_dir) else set()

    for f in sorted(os.listdir(src_dir)):
        if not f.endswith(('.mkv', '.mp4', '.flv')):
            continue
        # 对应的弹幕版应该叫什么
        stem = os.path.splitext(f)[0]
        expect = [x for x in dm_files if x.startswith(stem + '（弹幕版）')]
        if expect:
            continue                    # 渲染成功了，正常
        p = os.path.join(src_dir, f)
        sz = os.path.getsize(p)
        if sz < 1024:
            continue                    # 空文件另算
        # 只关心"上传流水线启用后"的（更早的是历史存档，本来就留存）
        dt = date_of(f)
        rows.append((d, f, sz, dt, p))

for d, f, sz, dt, p in sorted(rows, key=lambda x: -x[2]):
    print(f'  {sz/1024/1024:>9.1f} MB  {dt}  [{d}]  {f}')
    total_n += 1
    total_b += sz

print()
print('=' * 78)
print(f'合计 {total_n} 个文件, {total_b/1024/1024/1024:.2f} GB')
print('=' * 78)
print()
print('判定依据：同名源文件存在，但 （弹幕版） 目录里没有对应的 （弹幕版）.mp4')
print('含义：渲染失败（或渲染从未完成）→ 源文件按设计本该被清理却滞留')
print()
print('⚠️ 删除前提醒：这些是**录播原始内容**。如果还想重试渲染，先别删。')
print('   渲染失败原因多数是 libopus 参数问题（已修），重新渲染大概率能成功。')
