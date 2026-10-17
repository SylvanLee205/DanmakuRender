"""测试按时间戳配对弹幕。"""
import os
import sys

sys.path.insert(0, r'F:\DanmakuRender_Mod')
from tools.recover_part import find_danmaku, _time_token

D = r'F:\DanmakuRender_AutoUp\直播回放\vvu'
PARTS = [
    '[正在录制]vvu-20261005181052-0ba97a2cc0a511f1.flv.part',
    '[正在录制]vvu-20261005193103-3f5dedcdc0b011f1.flv.part',
]

print('=' * 78)
print('按时间戳配对弹幕的测试')
print('=' * 78)
print(f'目录里的弹幕文件:')
for f in sorted(os.listdir(D)):
    if f.endswith('.ass'):
        print(f'    {f}   (时间戳 {_time_token(f)})')

print()
for part in PARTS:
    p = os.path.join(D, part)
    tok = _time_token(part)
    res = find_danmaku(p, D)
    first = os.path.basename(res[0]) if res else '（无）'
    print(f'  {part}')
    print(f'    .part 时间戳   : {tok}')
    print(f'    配对到的弹幕   : {first}')
    print(f'    全部候选       : {[os.path.basename(x) for x in res]}')
    # 断言：优先配对时间戳相同的
    if res:
        same = tok and tok in os.path.basename(res[0])
        print(f'    时间戳匹配     : {"✓" if same else "（回退到兜底）"}')
    print()
