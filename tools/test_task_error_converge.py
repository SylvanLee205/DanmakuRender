"""回归测试：渲染/上传失败时状态必须收敛（2026-10-05 审查发现的活体泄漏）。

背景（实盘证据）：
  - render/error 和 uploader/error 原来都走 defaultEvent，只打日志、不动状态
  - 后果：wait 里的 request_id 永远留着 → 清理的第二道防线（wait 非空不清理）
    永远挡着 → **源视频永不清理**；dm_video 永久停在 rendering → 第三道防线
    也挡着；分组永远达不到终态 → 内存不释放
  - 实测：18 次渲染错误 → 8 个 .mkv 共 1.76GB 滞留；"视频信息已被释放" 出现 0 次

本测试验证修复后：
  1. render/error 后 wait 被清空、状态变 failed
  2. failed 状态能被 _check_for_clean 清理（源视频会被删）
  3. uploader/error 同理
  4. failed 是终态，_free_state_memory 能释放分组
  5. clean_args 值类型错误时不再假报 cleaned
"""
import os
import sys
import types

sys.path.insert(0, r'F:\DanmakuRender_Mod')

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f'  {detail}' if detail else ''))


# ── 构造一个最小的 LiveEvents 实例（绕开真正的 Config） ──────────────
from DMR.Task.liveevents import LiveEvents
from DMR.utils import PipeMessage, VideoInfo, StreamerInfo


class FakeLogger:
    def __init__(self):
        self.msgs = []

    def _rec(self, lvl, m):
        self.msgs.append(f'{lvl}: {m}')

    def info(self, m, *a, **k):
        self._rec('INFO', m)

    def debug(self, m, *a, **k):
        self._rec('DEBUG', m)

    def warning(self, m, *a, **k):
        self._rec('WARNING', m)

    def error(self, m, *a, **k):
        self._rec('ERROR', m)

    def exception(self, m, *a, **k):
        self._rec('EXC', m)


def make_events(clean_args, auto_clean=True, auto_upload=True):
    obj = LiveEvents.__new__(LiveEvents)
    obj.name = '测试主播'
    obj.logger = FakeLogger()
    obj.state_dict = {}
    obj.ended_dict = {}
    obj.config = {
        'common_event_args': {
            'auto_upload': auto_upload,
            'auto_clean': auto_clean,
            'auto_render': True,
            'auto_transcode': False,
        },
        'clean_args': clean_args,
        'download_args': {'output_dir': './直播回放', 'output_format': 'mkv'},
    }
    # 让 _check_for_clean 能拿到 clean_args（它读 self.config['clean_args']）
    return obj


def make_video_state(group_id, rid, src_status='ready', dm_status='rendering'):
    """注意 src_video 的 group_id 是**文件名里的 group_id**，
    测试里为了让 _check_for_clean(group_id) 能找到，用固定值 'gid'。"""
    src = VideoInfo(path=f'F:/tmp/{group_id}/src.mkv', taskname=group_id,
                    streamer=StreamerInfo(name=group_id))
    dm = VideoInfo(path=f'F:/tmp/{group_id}/dm.mp4', taskname=group_id,
                   streamer=StreamerInfo(name=group_id))
    return {
        'src_video': {'status': src_status, 'wait': [], 'file': src},
        'dm_video': {'status': dm_status, 'wait': [rid], 'file': dm},
    }


def err_msg(rid, msg='渲染出错了'):
    m = PipeMessage(source='render', target='测试主播', event='error',
                    request_id=rid, msg=msg)
    return m


print('=' * 78)
print('1. render/error 必须收敛状态')
print('=' * 78)
ev = make_events({'src_video': [{'method': 'delete', 'delay': 0}]})
rid = 'rid-render-1'
GID = 'gid'
ev.state_dict[GID] = [make_video_state('g1', rid)]
ev.ended_dict[GID] = 0

out = ev.onTaskError(err_msg(rid, '渲染视频时出现错误: ffmpeg 退出码 1'))
st = ev.state_dict[GID][0]
check('wait 被清空', st['dm_video']['wait'] == [], f"wait={st['dm_video']['wait']}")
check('dm_video 状态变为 failed', st['dm_video']['status'] == 'failed',
      f"status={st['dm_video']['status']}")
check('产生了清理任务（源视频会被删）', len(out) > 0, f'{len(out)} 个消息')
check('src_video 被清理', st['src_video']['status'] == 'cleaned',
      f"src_status={st['src_video']['status']}")

print()
print('=' * 78)
print('2. failed 状态必须能被清理（否则源视频永久滞留）')
print('=' * 78)
ev2 = make_events({'src_video': [{'method': 'delete', 'delay': 0}]})
ev2.state_dict['g2'] = [{
    'src_video': {'status': 'failed', 'wait': [], 'file': VideoInfo(
        path='F:/tmp/g2/src.mkv', taskname='g2', streamer=StreamerInfo(name='g2'))},
    'dm_video': {'status': 'failed', 'wait': [], 'file': None},
}]
msgs2 = ev2._check_for_clean('g2')
check('failed 的 src_video 被派发清理', len(msgs2) > 0, f'{len(msgs2)} 个消息')
check('清理后状态变 cleaned',
      ev2.state_dict['g2'][0]['src_video']['status'] == 'cleaned',
      f"status={ev2.state_dict['g2'][0]['src_video']['status']}")

print()
print('=' * 78)
print('3. uploader/error 必须收敛状态')
print('=' * 78)
ev3 = make_events({'src_video': [{'method': 'delete', 'delay': 0}]})
rid3 = 'rid-upload-1'
ev3.state_dict[GID] = [make_video_state('g3', rid3, src_status='ready',
                                        dm_status='uploading')]
ev3.ended_dict[GID] = 0
out3 = ev3.onTaskError(err_msg(rid3, '上传视频时出现错误: rclone 返回码 1'))
st3 = ev3.state_dict[GID][0]
check('wait 被清空', st3['dm_video']['wait'] == [])
check('dm_video 状态变为 failed', st3['dm_video']['status'] == 'failed',
      f"status={st3['dm_video']['status']}")

print()
print('=' * 78)
print('4. failed 是终态，_free_state_memory 必须能释放分组')
print('=' * 78)
ev4 = make_events({'src_video': [{'method': 'delete', 'delay': 0}]})
ev4.state_dict['g4'] = [{
    'src_video': {'status': 'cleaned', 'wait': [], 'file': None},
    'dm_video': {'status': 'failed', 'wait': [], 'file': None},
}]
ev4.ended_dict['g4'] = 0
ev4._free_state_memory()
check('分组已释放', 'g4' not in ev4.state_dict,
      f"state_dict keys={list(ev4.state_dict.keys())}")

print()
print('=' * 78)
print('5. dm_video 没有清理规则时也要能释放（原来永不释放）')
print('=' * 78)
ev5 = make_events({'src_video': [{'method': 'delete', 'delay': 0}]})
ev5.state_dict['g5'] = [{
    'src_video': {'status': 'cleaned', 'wait': [], 'file': None},
    'dm_video': {'status': 'uploaded', 'wait': [], 'file': None},
}]
ev5.ended_dict['g5'] = 0
ev5._free_state_memory()
check('dm_video 停在 uploaded 也能释放', 'g5' not in ev5.state_dict,
      f"state_keys={list(ev5.state_dict.keys())}")

print()
print('=' * 78)
print('6. clean_args 值类型错误时不能假报 cleaned')
print('=' * 78)
ev6 = make_events({'src_video': None})       # YAML 里 `src_video:` 留空的典型写法
ev6.state_dict['g6'] = [{
    'src_video': {'status': 'ready', 'wait': [], 'file': VideoInfo(
        path='F:/tmp/g6/src.mkv', taskname='g6', streamer=StreamerInfo(name='g6'))},
    'dm_video': {'status': 'ready', 'wait': [], 'file': None},
}]
msgs6 = ev6._check_for_clean('g6')
st6 = ev6.state_dict['g6'][0]['src_video']['status']
check('没有派发清理任务', len(msgs6) == 0)
check('状态没有被假报成 cleaned', st6 != 'cleaned', f'status={st6}')
check('打出了明确的 ERROR 日志',
      any('类型不对' in m or 'ERROR' in m for m in ev6.logger.msgs),
      f'日志条数={len(ev6.logger.msgs)}')

print()
print('=' * 78)
print(f'结果: {len(PASS)} 通过 / {len(FAIL)} 失败')
if FAIL:
    for f in FAIL:
        print(f'  失败: {f}')
print('=' * 78)
sys.exit(1 if FAIL else 0)
