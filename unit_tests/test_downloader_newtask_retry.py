# -*- coding: utf-8 -*-
"""下载任务创建失败后的自动重试（2026-10-23）。

实盘事故：抖音接口 5 秒读超时发生在 ``StreamDownloadTask`` 构造
（``LiveAPI(url)`` → 解析房间号）的那一瞬间，``newtask`` 抛异常 →
消息被 ``_pipeRecvMonitor`` 的 except 吞掉 → 这个主播本次开播就不会被录制，
而且没有任何自动重试，只能重启程序或改动配置才会重新派发。

这里锁定修复后的行为：
- newtask 失败会被重新排回队列（带 _dl_retry 计数）
- 重试有上限（NEWTASK_MAX_RETRY），不会无限刷
- 非 newtask 事件不重试（没有重发语义）
"""
from __future__ import annotations

import queue
import unittest

from unit_tests.support import DMRTestCase


class _FakeTimer:
    """把 threading.Timer 换成同步执行，避免测试真的等 30 秒。"""

    def __init__(self, delay, func, args=()):
        self.delay = delay
        self.func = func
        self.args = args
        self.daemon = False
        self.started = False

    def start(self):
        self.started = True
        self.func(*self.args)

    def cancel(self):
        pass


class TestNewtaskRetry(DMRTestCase):

    def _make_downloader(self):
        from DMR.Downloader import Downloader
        send_q: queue.Queue = queue.Queue()
        recv_q: queue.Queue = queue.Queue()
        return Downloader(pipe=(send_q, recv_q))

    def _msg(self, taskname='某主播'):
        from DMR.utils import PipeMessage
        return PipeMessage(source='engine', target='downloader',
                           event='newtask', data={'taskname': taskname})

    def test_failed_newtask_is_requeued_with_counter(self):
        import DMR.Downloader as dlmod
        original = dlmod.threading.Timer
        dlmod.threading.Timer = _FakeTimer
        try:
            d = self._make_downloader()
            d.stoped = False          # 正常运行中的 Downloader 才是 False
            msg = self._msg()
            d._schedule_newtask_retry(msg)

            self.assertEqual(msg.data['_dl_retry'], 1)
            self.assertFalse(d.recv_queue.empty(),
                             '失败的任务应被重新排回队列，否则这个主播就录不到了')
            again = d.recv_queue.get_nowait()
            self.assertEqual(again.event, 'newtask')
            self.assertEqual(again.data['taskname'], '某主播')
        finally:
            dlmod.threading.Timer = original

    def test_retry_is_bounded(self):
        import DMR.Downloader as dlmod
        original = dlmod.threading.Timer
        dlmod.threading.Timer = _FakeTimer
        try:
            d = self._make_downloader()
            msg = self._msg()
            for _ in range(d.NEWTASK_MAX_RETRY):
                d._schedule_newtask_retry(msg)
            # 达到上限后不再排回队列（否则配置有问题时会无限刷屏）
            self.assertEqual(msg.data['_dl_retry'], d.NEWTASK_MAX_RETRY)
            self.assertTrue(d.recv_queue.empty())
        finally:
            dlmod.threading.Timer = original

    def test_backoff_grows(self):
        delays = []
        import DMR.Downloader as dlmod

        class _Recorder(_FakeTimer):
            def __init__(self, delay, func, args=()):
                super().__init__(delay, func, args)
                delays.append(delay)

        original = dlmod.threading.Timer
        dlmod.threading.Timer = _Recorder
        try:
            d = self._make_downloader()
            msg = self._msg()
            d._schedule_newtask_retry(msg)
            d._schedule_newtask_retry(msg)
        finally:
            dlmod.threading.Timer = original
        self.assertEqual(delays, [d.NEWTASK_RETRY_DELAY,
                                  d.NEWTASK_RETRY_DELAY * 2],
                         '重试间隔应递增，别一上来就反复撞')

    def test_other_events_are_not_retried(self):
        from DMR.utils import PipeMessage
        d = self._make_downloader()
        msg = PipeMessage(source='engine', target='downloader',
                          event='stoptask', data='某主播')
        d._schedule_newtask_retry(msg)
        self.assertTrue(d.recv_queue.empty(),
                        'stoptask 之类的事件没有重发语义，不应重试')


if __name__ == '__main__':
    unittest.main()
