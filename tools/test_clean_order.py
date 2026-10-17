"""回归测试：模拟完整的「分段录制 → 渲染 → 清理」事件顺序。

这是对 2026-10-05 事故的回归防护。事故经过：
    录制分段完成 → onLiveSegment 立刻触发清理 → 原视频被删
    但此时渲染还在读这个文件 → 渲染失败，且原文件已不可恢复

本测试严格按真实顺序调用事件处理函数，断言：
    ★ 在 dm_video 还是 'rendering' 时，原视频**绝不能**被提交清理
    ★ 渲染完成后，原视频**必须**被提交清理
"""
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.WARNING, format='    [%(levelname)s] %(message)s')

from DMR.Task.liveevents import LiveEvents
from DMR.utils import PipeMessage, VideoInfo, StreamerInfo

SKIP_RULE = {
    'enabled': False,
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
            'src_video': [{'method': 'custom', 'delay': 0, 'wait': True, 'w_srcpre': True,
                           'command': ['cmd', '/c', 'echo', 'DELETE-SRC', '{PATH}']}],
        },
    }


def make_video(tmpdir, name, dtype='src_video'):
    path = os.path.join(tmpdir, name)
    open(path, 'wb').write(b'\x00' * 1024)
    v = VideoInfo(path=path, size=1024, duration=3600, resolution=(1080, 1920),
                  streamer=StreamerInfo(name='测试主播'), taskname='测试主播',
                  dtype=dtype, group_id='g1', segment_id=1)
    v.fps = 30
    v.bitrate = 1000
    return v


def sent_files(sent, target='cleaner'):
    """从收集到的消息里，取出发给 cleaner 的文件名。"""
    out = []
    for args, kw in sent:
        msg = args[0] if args else kw.get('msg')
        if getattr(msg, 'target', None) != target:
            continue
        data = getattr(msg, 'data', None) or {}
        for f in (data.get('files') or []):
            out.append(os.path.basename(str(getattr(f, 'path', f))))
    return out


def main():
    print('=' * 74)
    print('回归测试：录制 → 渲染 → 清理 的事件顺序')
    print('=' * 74)

    tmpdir = tempfile.mkdtemp(prefix='dmr_order_')
    task = LiveEvents('测试主播', make_config())
    sent = []
    task._pipeSend = lambda *a, **kw: sent.append((a, kw))

    src = make_video(tmpdir, 'src.mkv', 'src_video')
    gid = 'g1'

    ok = True

    # ---------- 第 1 步：分段录制完成 ----------
    print('\n[1] onLiveSegment —— 分段录制完成，随即开始渲染')
    seg_msg = PipeMessage(source='replay/测试主播', target='测试主播', event='livesegment',
                          msg='录制完成', dtype='VideoInfo', data=src)
    msgs = task.onLiveSegment(seg_msg) or []
    for m in msgs:
        task._pipeSend(m)

    dm_status = task.state_dict[gid][0]['dm_video']['status']
    src_status = task.state_dict[gid][0]['src_video']['status']
    files_at_render = sent_files(sent, 'cleaner')
    print(f'    dm_video 状态 = {dm_status}    src_video 状态 = {src_status}')
    print(f'    此时提交给 cleaner 的文件 = {files_at_render}')

    if 'src.mkv' in files_at_render:
        print('    ✗✗ 严重错误：渲染还没完成就把原视频提交清理了！')
        ok = False
    else:
        print('    ✓ 正确：渲染期间原视频没有被清理')

    # ---------- 第 2 步：渲染完成 ----------
    print('\n[2] onRenderEnd —— 弹幕版渲染完成')
    render_req = None
    for m in msgs:
        if getattr(m, 'target', None) == 'render':
            render_req = m.request_id
    dm = make_video(tmpdir, 'dm.mp4', 'dm_video')
    end_msg = PipeMessage(source='render', target='测试主播', event='renderend',
                          request_id=render_req, msg='弹幕版渲染完成',
                          data={'output': dm})
    # onRenderEnd 用 video.group_id 索引，需要从 data 取
    end_msg2 = PipeMessage(source='render', target='测试主播', event='end',
                           request_id=render_req, msg='渲染完成',
                           data={'output': dm})
    try:
        msgs2 = task.onRenderEnd(end_msg2) or []
    except Exception as e:
        print(f'    onRenderEnd 异常: {type(e).__name__}: {e}')
        msgs2 = []
    for m in msgs2:
        task._pipeSend(m)

    files_after_render = sent_files(sent, 'cleaner')
    new_files = [f for f in files_after_render if f not in files_at_render]
    print(f'    渲染后新提交给 cleaner 的文件 = {new_files}')
    if 'src.mkv' in new_files:
        print('    ✓ 正确：渲染完成后原视频被提交清理')
    else:
        print('    ✗ 错误：渲染完成后原视频**没有**被清理（会一直堆积）')
        ok = False

    print()
    print('=' * 74)
    print('全部通过 ✓' if ok else '有失败项 ✗')
    print('=' * 74)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
