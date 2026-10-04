"""验证「高质量大文件跳过上传」规则。

覆盖：
  1. 三个条件各种组合下，命中几个、是否跳过
  2. 数据缺失时不会误跳过（fail-open）
  3. 规则关闭时不生效
  4. skip_min_matches 取 1/2/3 的差异

用法：python tools\test_skip_upload.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.WARNING)

from DMR.utils import VideoInfo, StreamerInfo, evaluate_upload_skip_rule

RULE = {
    'enabled': True,
    'skip_landscape': True,
    'skip_bitrate_kbps': 2500,
    'skip_fps': 40,
    'skip_min_matches': 2,
}

# 横屏必选模式（当前 global.yml 用的就是这个）
RULE_LANDSCAPE_ONLY = {
    'enabled': True,
    'skip_landscape': True,
    'skip_require_landscape': True,
    'skip_bitrate_kbps': 2500,
    'skip_fps': 40,
    'skip_min_matches': 1,
}


def make_video(resolution, bitrate_kbps, fps, duration=3600, size=None):
    """构造一个带指定特征的 VideoInfo。bitrate 用 size/duration 表达。"""
    if size is None and bitrate_kbps and duration:
        size = int(bitrate_kbps * 1000 / 8 * duration)      # kbit -> bytes
    v = VideoInfo(path=r'F:\fake\test.mp4', size=size, duration=duration,
                  resolution=resolution,
                  streamer=StreamerInfo(name='test'), taskname='test')
    v.fps = fps                 # 直接给，避免真的去 ffprobe
    v.bitrate = bitrate_kbps    # kbps
    return v


def case(name, video, rule=RULE, expect=None):
    should, detail = evaluate_upload_skip_rule(video, rule)
    mark = ''
    if expect is not None:
        mark = '  ✓' if should == expect else '  ✗ 不符合预期(期望 %s)' % expect
    print(f'  {name:<42} 跳过={str(should):<5} {detail}{mark}')
    return should == expect if expect is not None else True


def main():
    print('规则: 横屏/码率>=2500kbps/帧率>=40fps，命中 2 个就跳过\n')
    ok = True

    print('=== 1. 三条件组合（对应 8 种情况）===')
    H, V = (1920, 1080), (1080, 1920)
    hi_b, lo_b = 6000, 1000
    hi_f, lo_f = 60, 30
    ok &= case('横屏 + 高码率 + 高帧率  (3命中)', make_video(H, hi_b, hi_f), expect=True)
    ok &= case('横屏 + 高码率 + 低帧率  (2命中)', make_video(H, hi_b, lo_f), expect=True)
    ok &= case('横屏 + 低码率 + 高帧率  (2命中)', make_video(H, lo_b, hi_f), expect=True)
    ok &= case('横屏 + 低码率 + 低帧率  (1命中)', make_video(H, lo_b, lo_f), expect=False)
    ok &= case('竖屏 + 高码率 + 高帧率  (2命中)', make_video(V, hi_b, hi_f), expect=True)
    ok &= case('竖屏 + 高码率 + 低帧率  (1命中)', make_video(V, hi_b, lo_f), expect=False)
    ok &= case('竖屏 + 低码率 + 高帧率  (1命中)', make_video(V, lo_b, hi_f), expect=False)
    ok &= case('竖屏 + 低码率 + 低帧率  (0命中)', make_video(V, lo_b, lo_f), expect=False)

    print('\n=== 2. 边界值（正好等于阈值应该算命中）===')
    ok &= case('码率正好 2500kbps', make_video(V, 2500, lo_f), expect=False)
    ok &= case('码率 2499kbps', make_video(V, 2499, lo_f), expect=False)
    ok &= case('横屏 + 码率正好 2500', make_video(H, 2500, lo_f), expect=True)
    ok &= case('帧率正好 40fps', make_video(V, lo_b, 40), expect=False)
    ok &= case('横屏 + 帧率正好 40', make_video(H, lo_b, 40), expect=True)
    ok &= case('正方形 1000x1000（不算横屏）', make_video((1000, 1000), hi_b, hi_f), expect=True)

    print('\n=== 3. skip_min_matches 的差异（横屏+高码率+低帧率 = 2命中）===')
    v = make_video(H, hi_b, lo_f)
    for n, expect in ((1, True), (2, True), (3, False)):
        r = dict(RULE, skip_min_matches=n)
        ok &= case(f'skip_min_matches={n}', v, rule=r, expect=expect)

    print('\n=== 4. 数据缺失时不能误跳过（fail-open）===')
    # 只保留横屏，码率和帧率都拿不到 -> 只能命中 1 项，不该跳过
    v_missing = VideoInfo(path=r'F:\DanmakuRender_AutoUp\直播回放\不存在的文件.mp4',
                          streamer=StreamerInfo(name='t'), taskname='t')
    v_missing.resolution = None
    v_missing.size = None
    v_missing.duration = None
    v_missing.fps = None
    v_missing.bitrate = None
    ok &= case('全部数据缺失', v_missing, expect=False)

    print('\n=== 5. 开关关闭 ===')
    ok &= case('enabled=False', make_video(H, hi_b, hi_f),
               rule=dict(RULE, enabled=False), expect=False)
    ok &= case('规则为空 {}', make_video(H, hi_b, hi_f), rule={}, expect=False)

    print('\n=== 6. 只启用其中两个条件 ===')
    r2 = {'enabled': True, 'skip_landscape': True, 'skip_bitrate_kbps': 2500,
          'skip_fps': None, 'skip_min_matches': 2}
    ok &= case('只判横屏+码率: 竖屏高码率（1命中）', make_video(V, hi_b, hi_f), rule=r2, expect=False)
    ok &= case('只判横屏+码率: 横屏高码率（2命中）', make_video(H, hi_b, lo_f), rule=r2, expect=True)

    print('\n=== 7. 横屏必选模式（当前 global.yml 的配置）===')
    print('  规则: 横屏必选 + (码率>=2500 或 帧率>=40)，即 skip_min_matches=1')
    ok &= case('横屏 + 高码率 + 低帧率', make_video(H, hi_b, lo_f), rule=RULE_LANDSCAPE_ONLY, expect=True)
    ok &= case('横屏 + 低码率 + 高帧率', make_video(H, lo_b, hi_f), rule=RULE_LANDSCAPE_ONLY, expect=True)
    ok &= case('横屏 + 高码率 + 高帧率', make_video(H, hi_b, hi_f), rule=RULE_LANDSCAPE_ONLY, expect=True)
    ok &= case('横屏 + 低码率 + 低帧率（横屏但都不够）', make_video(H, lo_b, lo_f), rule=RULE_LANDSCAPE_ONLY, expect=False)
    ok &= case('竖屏 + 高码率 + 高帧率 -> 不该跳过', make_video(V, hi_b, hi_f), rule=RULE_LANDSCAPE_ONLY, expect=False)
    ok &= case('竖屏 + 高码率 + 低帧率 -> 不该跳过', make_video(V, hi_b, lo_f), rule=RULE_LANDSCAPE_ONLY, expect=False)
    ok &= case('正方形 + 高码率 + 高帧率 -> 不算横屏', make_video((1000, 1000), hi_b, hi_f), rule=RULE_LANDSCAPE_ONLY, expect=False)

    print('\n=== 8. 横屏必选 + 分辨率探测失败（fail-open）===')
    v_nodim = VideoInfo(path=r'F:\DanmakuRender_AutoUp\直播回放\不存在.mp4',
                        size=int(hi_b * 1000 / 8 * 3600), duration=3600,
                        streamer=StreamerInfo(name='t'), taskname='t')
    v_nodim.resolution = None
    v_nodim.fps = hi_f
    v_nodim.bitrate = hi_b
    ok &= case('分辨率拿不到（不给路径可探测）', v_nodim, rule=RULE_LANDSCAPE_ONLY, expect=False)

    print()
    print('=' * 70)
    print('全部通过 ✓' if ok else '有失败项 ✗')
    print('=' * 70)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
