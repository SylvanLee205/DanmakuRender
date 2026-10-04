"""集成测试：跳过上传规则 → 状态机 → 清理流程 是否正确联动。

重点验证需求里最容易出错的一环：
    「跳过上传之后，原视频也要被删掉，弹幕版留存」

用真实的 LiveEvents 对象，只把 _pipeSend 换成收集器，不会真的删任何文件。
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.INFO, format='    [%(levelname)s] %(message)s')

from DMR.Task.liveevents import LiveEvents
from DMR.utils import VideoInfo, StreamerInfo

SKIP_RULE = {
    'enabled': True,
    'skip_landscape': True,
    'skip_bitrate_kbps': 2500,
    'skip_fps': 40,
    'skip_min_matches': 2,
}


def make_config(tmpdir):
    """构造一个开启上传+清理的任务配置，清理动作走 custom 的 echo，不会真删文件。"""
    return {
        'common_event_args': {'auto_render': True, 'auto_upload': True,
                              'auto_clean': True, 'auto_transcode': False},
        'download_args': {'dltype': 'live', 'url': 'https://live.douyin.com/1'},
        'render_args': {'dmrender': {'skip_upload_rule': dict(SKIP_RULE)}},
        'upload_args': {
            'dm_video+bilibili+rclone': [
                {'target': 'bilibili', 'engine': 'biliuprs', 'account': 'bilibili',
                 'realtime': False, 'min_length': 0, 'retry': 0},
                {'target': 'rclone', 'engine': 'subprocess',
                 'realtime': False, 'min_length': 0, 'retry': 0,
                 'command': ['cmd', '/c', 'echo', 'upload', '{PATH}']},
            ],
        },
        'clean_args': {
            # 用 custom + echo 代替 delete，避免测试真的删文件
            'src_video': [{'method': 'custom', 'delay': 0, 'wait': True, 'w_srcpre': True,
                           'command': ['cmd', '/c', 'echo', 'delete-src', '{PATH}']}],
            'dm_video': [{'method': 'custom', 'delay': 0, 'wait': True,
                          'command': ['cmd', '/c', 'echo', 'keep-dm', '{PATH}']}],
        },
    }


def make_video(tmpdir, name, resolution, bitrate_kbps, fps, duration=3600):
    path = os.path.join(tmpdir, name)
    with open(path, 'wb') as f:
        f.write(b'\x00' * 1024)
    size = int(bitrate_kbps * 1000 / 8 * duration)
    v = VideoInfo(path=path, size=size, duration=duration, resolution=resolution,
                  streamer=StreamerInfo(name='测试主播'), taskname='测试主播',
                  dtype='dm_video', group_id='g1', segment_id=1)
    v.fps = fps
    v.bitrate = bitrate_kbps
    return v


def run_case(title, resolution, bitrate, fps, expect_skip):
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix='dmr_skip_')
    cfg = make_config(tmpdir)
    task = LiveEvents('测试主播', cfg)

    sent = []
    task._pipeSend = lambda *a, **kw: sent.append((a, kw))

    src = make_video(tmpdir, 'src.mkv', resolution, bitrate, fps)
    src.dtype = 'src_video'
    dm = make_video(tmpdir, 'dm.mp4', resolution, bitrate, fps)
    dm.dtype = 'dm_video'

    gid = 'g1'
    task.state_dict[gid] = [{
        'src_video': {'status': 'ready', 'file': src, 'wait': []},
        'src_video_pre': {'status': None, 'file': None, 'wait': []},
        'dm_video': {'status': 'ready', 'file': dm, 'wait': []},
    }]
    task.ended_dict[gid] = 0

    msgs = task._check_for_upload(gid) or []
    uploads = [m for m in msgs if m.get('target') == 'uploader']

    st = task.state_dict[gid][0]
    dm_status = st['dm_video']['status']
    src_status = st['src_video']['status']

    # 再走一次清理（模拟 onUploadEnd / onLiveSegment 的补调用）
    clean_msgs = task._check_for_clean(gid) or []
    clean_targets = [m.get('target') for m in clean_msgs]

    skipped = dm_status == 'upload_skipped'
    passed = (skipped == expect_skip) and (len(uploads) == (0 if expect_skip else 2))
    if expect_skip:
        passed = passed and ('cleaner' in clean_targets)

    print(f'  {title}')
    print(f'    码率={bitrate}kbps 帧率={fps} 分辨率={resolution[0]}x{resolution[1]}')
    print(f'    -> dm_video 状态: {dm_status}   提交的上传任务数: {len(uploads)}')
    print(f'    -> 触发的清理任务: {clean_targets}')
    print(f'    -> {"通过 ✓" if passed else "失败 ✗"}')
    return passed


def main():
    print('=' * 74)
    print('跳过上传 + 清理联动测试（auto_upload=True, auto_clean=True）')
    print('=' * 74)

    ok = True
    print('\n--- 应该跳过上传的情况（横屏+高码率）---')
    ok &= run_case('横屏 1080p 6000kbps 30fps  -> 3项中命中横屏+码率', (1920, 1080), 6000, 30, True)

    print('\n--- 不该跳过的情况 ---')
    ok &= run_case('竖屏 1000kbps 30fps -> 0命中', (1080, 1920), 1000, 30, False)
    ok &= run_case('竖屏 6000kbps 30fps -> 只命中码率', (1080, 1920), 6000, 30, False)

    print('\n--- 反直觉但符合规则：竖屏高码率高帧率也跳过 ---')
    ok &= run_case('竖屏 6000kbps 60fps -> 命中码率+帧率', (1080, 1920), 6000, 60, True)

    print()
    print('=' * 74)
    print('全部通过 ✓' if ok else '有失败项 ✗')
    print('=' * 74)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
