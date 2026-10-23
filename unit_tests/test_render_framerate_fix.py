"""源帧率不可用导致硬件编码器拒绝启动 —— 回归测试（2026-10-19）。

背景（实测）：
    抖音某些 TS 分段的 ``r_frame_rate`` 是 ``0/0``（只有 ``avg_frame_rate``），
    ffmpeg 因此算不出输出帧率，QSV 直接拒绝初始化编码器::

        [hevc_qsv] Current frame rate is unsupported
        [hevc_qsv] some encoding parameters are not supported by the QSV runtime
        [vost#0:0/hevc_qsv] Error while opening encoder ...
        Conversion failed!          (return code -22)

    这跟"GPU 编码会话被占用"是两回事，重试多少次都没有用。原来的逻辑会
    白等 2×60 秒再降级到 libx265（实测吃满 6 个核，单分段渲染慢一倍以上）。

修法：
    识别出这类错误后，立刻用 ``avg_frame_rate`` 补一个 ``-r`` 重新走硬件编码。
    实测同一个文件：不加 ``-r`` 必失败，加 ``-r 22`` 正常出片。

这里用假的 ``render_helper`` 锁住行为，不真的调 ffmpeg。
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest import mock

from DMR.Render.dmrender import DmRender


class _Video:
    """render_one 需要的最小 VideoInfo 替身（必须可 deepcopy）。"""

    def __init__(self, path, duration):
        self.path = path
        self.duration = duration
        self.file_id = 'src-1'
        self.dm_file_id = None
        self.dtype = 'src_video'
        self.size = 1
        self.ctime = None
        self.src_video_id = None


class _FakeRender(DmRender):
    """把真正的 ffmpeg 调用换成可编程的假实现。"""

    FRAMERATE_ERROR = (
        '[hevc_qsv @ 000001cd95440040] Low power mode is unsupported\n'
        '[hevc_qsv @ 000001cd95440040] Current frame rate is unsupported\n'
        '[hevc_qsv @ 000001cd95440040] some encoding parameters are not '
        'supported by the QSV runtime. Please double check the input parameters.\n'
        '[vost#0:0/hevc_qsv @ 000001cd82b12080] Error while opening encoder\n'
        'Conversion failed!')

    CONTENTION_ERROR = (
        '[hevc_qsv @ 0x1] Error encoding frame: Invalid FrameType:0\n'
        'return code -1094995529')

    def __init__(self, *args, **kwargs):
        self.fail_text = self.FRAMERATE_ERROR
        # 必须在 super().__init__ 之前置位，构造里会调 _check_encoder_args
        super().__init__(*args, **kwargs)
        self.calls = []

    def render_helper(self, video, danmaku, output, vencoder=None,
                      vencoder_args=None, **kwargs):
        args = list(vencoder_args) if vencoder_args is not None \
            else list(self.vencoder_args)
        self.calls.append({'vencoder': vencoder or self.vencoder, 'args': args})
        if '-r' in args:
            with open(output, 'wb') as f:
                f.write(b'\0' * 4096)
            return True, 'video:1kB'
        return False, self.fail_text


def _make_render(cls=_FakeRender, **overrides):
    params = dict(
        hwaccel_args=[], vencoder='hevc_qsv',
        vencoder_args=['-global_quality:v', '30'],
        aencoder='libopus', aencoder_args=['-b:a', '96k'],
        output_resize='', fallback_vencoder='libx265',
        fallback_vencoder_args=['-crf', '28'],
        hw_retry=2, hw_retry_delay=0, gop_multiplier=None,
    )
    params.update(overrides)
    return cls(**params)


class TestFramerateFallback(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix='dmr_fps_')
        self.src = os.path.join(self.tmp, 'seg.ts')
        with open(self.src, 'wb') as f:
            f.write(b'\0' * 1024)
        self.dm = os.path.join(self.tmp, 'seg.ass')
        with open(self.dm, 'w', encoding='utf-8') as f:
            f.write('[Script Info]\n')
        self.out = os.path.join(self.tmp, 'out.mp4')

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _render(self, render, fps: float = 22.0):
        video = _Video(self.src, 60)
        video.dm_file_id = self.dm          # 生产上把弹幕挂在 VideoInfo 上，不是 kwarg
        # 后置校验会读产物时长，避免误判为"不可读产物"
        with mock.patch('DMR.Render.dmrender.FFprobe.get_fps', return_value=fps), \
                mock.patch('DMR.Render.dmrender.FFprobe.get_duration',
                           return_value=60.0), \
                mock.patch.object(DmRender, '_danmaku_last_timestamp',
                                  staticmethod(lambda _p: 60.0)):
            return render.render_one(video, self.out)

    def test_adds_output_framerate_and_stays_on_hardware(self) -> None:
        render = _make_render()
        status, _ = self._render(render)

        self.assertTrue(status, '补 -r 之后应当渲染成功')
        self.assertEqual(len(render.calls), 2, '应当只多一次重试，不是 2 次 60 秒重试')
        self.assertNotIn('-r', render.calls[0]['args'])
        self.assertIn('-r', render.calls[1]['args'])
        idx = render.calls[1]['args'].index('-r')
        self.assertEqual(render.calls[1]['args'][idx + 1], '22')
        # 仍然用硬件编码器，没有降级
        self.assertEqual(render.calls[1]['vencoder'], 'hevc_qsv')

    def test_keeps_user_encoder_args(self) -> None:
        render = _make_render()
        self._render(render)
        self.assertIn('-global_quality:v', render.calls[1]['args'])

    def test_contention_error_still_retries_and_falls_back(self) -> None:
        # GPU 争抢类错误不能走 -r 分支：重试后仍失败 → 降级软件编码
        render = _make_render()
        render.fail_text = _FakeRender.CONTENTION_ERROR
        self._render(render)

        self.assertTrue(all('-r' not in c['args'] for c in render.calls),
                        '争抢类错误不该补 -r')
        self.assertEqual(render.calls[-1]['vencoder'], 'libx265',
                         '硬件两次重试都失败后应降级到软件编码')

    def test_software_fallback_when_fps_unknown(self) -> None:
        # 探测不到帧率时不能瞎补 -r，必须老实降级
        render = _make_render()
        self._render(render, fps=0.0)
        self.assertTrue(all('-r' not in c['args'] for c in render.calls))
        self.assertEqual(render.calls[-1]['vencoder'], 'libx265')


class TestFramerateErrorDetector(unittest.TestCase):

    def test_detects_qsv_framerate_error(self) -> None:
        self.assertTrue(DmRender._is_framerate_error(
            _FakeRender.FRAMERATE_ERROR))

    def test_ignores_contention_error(self) -> None:
        self.assertFalse(DmRender._is_framerate_error(
            _FakeRender.CONTENTION_ERROR))

    def test_handles_empty(self) -> None:
        self.assertFalse(DmRender._is_framerate_error(None))
        self.assertFalse(DmRender._is_framerate_error(''))


def _capture_probe_args(render):
    """跑真实的 render_helper 组装参数，只把最后的 ffmpeg 调用换成假实现。"""
    captured = {}

    def fake_call(args):
        captured['args'] = list(args)
        return True, 'ok'

    with mock.patch.object(render.raw_ffmpeg, 'call_ffmpeg',
                           side_effect=fake_call), \
            mock.patch('DMR.Render.dmrender.FFprobe.get_fps',
                       return_value=22.0):
        render.render_helper('seg.ts', 'seg.ass', 'out.mp4')
    return captured['args']


class TestProbeArgs(unittest.TestCase):
    """探测参数必须是有限值。

    实测（2026-10-19）：``-analyzeduration 2147483647`` 会让 ffmpeg 探测到
    文件末尾；TS 没有逐包时长，扫完就丢掉按时间戳量出来的 22fps，改用 SPS
    里声明的 ``time_scale/num_units_in_tick = 2000/1``（该流同时写着
    ``fixed_frame_rate_flag=0``，即变帧率，所以 2000 是没意义的垃圾值），
    编码器拿到 2000fps 就被 QSV 拒绝。同样内容装进 flv/mkv 不受影响。
    """

    def test_analyzeduration_is_bounded(self) -> None:
        args = _capture_probe_args(_make_render(cls=DmRender))
        value = int(args[args.index('-analyzeduration') + 1])
        self.assertLess(value, 2147483647,
                        'analyzeduration 不能再是 INT_MAX，否则 TS 会退回假帧率')
        self.assertLessEqual(value, 300_000_000)

    def test_probesize_is_bounded(self) -> None:
        args = _capture_probe_args(_make_render(cls=DmRender))
        value = int(args[args.index('-probesize') + 1])
        self.assertLess(value, 2147483647)
        self.assertGreaterEqual(value, 50_000_000,
                                '别缩得太狠，损坏的 TS 头部还要靠它')


if __name__ == '__main__':
    unittest.main()
