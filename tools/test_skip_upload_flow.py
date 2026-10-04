"""集成测试：清理与上传解耦 + 跳过上传规则。

核心验证点（魔改后的行为）：
    1. 弹幕版一渲染完，**原视频立即被清理**，不等上传结果
    2. 命中跳过规则时：不提交任何上传任务，但**原视频照样被清理**，弹幕版留存
    3. 不命中跳过规则时：提交上传任务，原视频同样立即被清理（解耦）

用真实的 LiveEvents 对象，只把 _pipeSend 换成收集器，不会真的删任何文件。
"""
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.WARNING, format='    [%(levelname)s] %(message)s')

from DMR.Task.liveevents import LiveEvents
from DMR.utils import VideoInfo, StreamerInfo

SKIP_RULE = {
    'enabled': True,
    'skip_landscape': True,
    'skip_require_landscape': True,
    'skip_bitrate_kbps': 2500,
    'skip_fps': 40,
    'skip_min_matches': 1,
}


def make_config():
    return {
        'common_event_args': {'auto_render': True, 'auto_upload': True,
                              'auto_clean': True, 'auto_transcode': False},
        'download_args': {'dltype': 'live', 'url': 'https://live.douyin.com/1'},
        'render_args': {'dmrender': {'skip_upload_rule': dict(SKIP_RULE)}},
        'upload_args': {
            'dm_video': [{'target': 'rclone', 'engine': 'subprocess',
                          'realtime': False, 'min_length': 0, 'retry': 0,
                          'command': ['cmd', '/c', 'echo', 'upload', '{PATH}']}],
        },
        'clean_args': {
            # 用 custom + echo 代替 delete，避免测试真的删文件
            'src_video': [{'method': 'custom', 'delay': 0, 'wait': True, 'w_srcpre': True,
                           'command': ['cmd', '/c', 'echo', 'DELETE-SRC', '{PATH}']}],
            'dm_video': [{'method': 'custom', 'delay': 0, 'wait': True,
                          'command': ['cmd', '/c', 'echo', 'KEEP-DM', '{PATH}']}],
        },
    }


def make_video(tmpdir, name, resolution, bitrate_kbps, fps, duration=3600, dtype='dm_video'):
    path = os.path.join(tmpdir, name)
    open(path, 'wb').write(b'\x00' * 1024)
    size = int(bitrate_kbps * 1000 / 8 * duration)
    v = VideoInfo(path=path, size=size, duration=duration, resolution=resolution,
                  streamer=StreamerInfo(name='测试主播'), taskname='测试主播',
                  dtype=dtype, group_id='g1', segment_id=1)
    v.fps = fps
    v.bitrate = bitrate_kbps
    return v


def run_case(title, resolution, bitrate, fps, expect_skip):
    tmpdir = tempfile.mkdtemp(prefix='dmr_dec_')
    task = LiveEvents('测试主播', make_config())

    sent = []
    task._pipeSend = lambda *a, **kw: sent.append((a, kw))

    src = make_video(tmpdir, 'src.mkv', resolution, bitrate, fps, dtype='src_video')
    dm = make_video(tmpdir, 'dm.mp4', resolution, bitrate, fps, dtype='dm_video')

    gid = 'g1'
    task.state_dict[gid] = [{
        'src_video': {'status': 'ready', 'file': src, 'wait': []},
        'src_video_pre': {'status': None, 'file': None, 'wait': []},
        # 模拟「弹幕版刚渲染完」：ready，且 wait 已空
        'dm_video': {'status': 'ready', 'file': dm, 'wait': []},
    }]
    task.ended_dict[gid] = 0

    # 完全复刻 onRenderEnd 的核心顺序：先提交上传，再跑清理
    up_msgs = task._check_for_upload(gid) or []
    clean_msgs = task._check_for_clean(gid) or []

    uploads = [m for m in up_msgs if m.get('target') == 'uploader']
    cleans = [m for m in clean_msgs if m.get('target') == 'cleaner']

    def clean_files(m):
        data = m.get('data') or {}
        return data.get('files') or []

    src_deleted = any('src.mkv' in str(f.path) for m in cleans for f in clean_files(m))
    dm_kept = any('dm.mp4' in str(f.path) for m in cleans for f in clean_files(m))

    st = task.state_dict[gid][0]
    passed = True
    if expect_skip and len(uploads) != 0:
        passed = False
    if not expect_skip and len(uploads) == 0:
        passed = False
    if not src_deleted:
        passed = False                      # 无论跳不跳过，原视频都必须被清理

    print(f'  {title}')
    print(f'    {resolution[0]}x{resolution[1]} {bitrate}kbps {fps}fps')
    print(f'    -> 提交上传 {len(uploads)} 份 ({"跳过" if expect_skip else "应上传 1 份"})')
    print(f'    -> 原视频被清理: {src_deleted}   弹幕版被送清理: {dm_kept}')
    print(f'    -> src_video 终态={st["src_video"]["status"]}  dm_video 终态={st["dm_video"]["status"]}')
    print(f'    -> {"通过 ✓" if passed else "失败 ✗"}')
    return passed


def main():
    print('=' * 74)
    print('清理与上传解耦测试')
    print('=' * 74)

    ok = True
    print('\n--- 命中跳过规则：不上传，但原视频照样删 ---')
    ok &= run_case('横屏 1080p 6000kbps 30fps', (1920, 1080), 6000, 30, True)

    print('\n--- 不命中：要上传，原视频也照样删（这就是"解耦"）---')
    ok &= run_case('横屏 1080p 1500kbps 30fps', (1920, 1080), 1500, 30, False)
    ok &= run_case('竖屏 1080x1920 1000kbps 30fps', (1080, 1920), 1000, 30, False)

    print()
    print('=' * 74)
    print('全部通过 ✓' if ok else '有失败项 ✗')
    print('=' * 74)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
