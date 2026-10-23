"""渲染超时与待删清单的回归测试（2026-10-19）。

两条都是"看起来加了保护、实际没生效"的坑，必须用测试锁住：

1. **渲染超时**：``RawFFmpegRender`` 的超时公式依赖 ``src_duration``，
   而它一度**从未被赋值**，导致超时恒为 600 秒 —— 实测 72 次正常渲染里有 2 次
   超过 600 秒（最长 16.1 分钟），libx265 降级要 31 分钟，都会被误杀。
   这里断言：登记源时长后上限随之放大；探测不到时用保守下限。

2. **待删清单**：``_rearm_pending`` 必须写回 ``alive + overdue``，
   且「读-算-写」在锁内完成。只写 ``alive`` 会让"已到期但删除还没执行"的条目
   提前从清单消失 —— 那正是 6.42 GB 泄漏的同一个漏洞。
"""
from __future__ import annotations

import json
import os
import queue
import tempfile
import time
import unittest

from DMR.Cleaner import Cleaner
from DMR.Render.ffmpeg import RawFFmpegRender
from unit_tests.support import DMRTestCase


class _Video:
    def __init__(self, duration):
        self.duration = duration
        self.path = ''


class TestRenderTimeout(unittest.TestCase):
    """超时上限必须随源时长放大。"""

    def setUp(self) -> None:
        self.render = RawFFmpegRender(debug=True)

    def test_default_is_conservative_floor(self) -> None:
        # 未登记源时长时不能是 600 秒（那会杀掉 10 分钟以上的正常渲染）
        self.assertGreaterEqual(self.render._render_timeout(), 3600.0)

    def test_scales_with_source_duration(self) -> None:
        self.render.set_source(_Video(10800))          # 3 小时分段
        self.assertGreaterEqual(self.render._render_timeout(), 10800 * 10)

    def test_ignores_ffprobe_sentinel(self) -> None:
        # FFprobe 失败返回 -1，不能被当成真实时长（否则上限反而变小）
        self.render.set_source(_Video(-1))
        self.assertGreaterEqual(self.render._render_timeout(), 3600.0)

    def test_long_fallback_render_is_not_killed(self) -> None:
        # 实测 libx265 降级处理 3792 秒素材要 1860 秒，必须远低于上限
        self.render.set_source(_Video(3792))
        self.assertGreater(self.render._render_timeout(), 1860 * 2)


class TestPendingCleanJournal(DMRTestCase):
    """待删清单的读改写语义。"""

    def setUp(self) -> None:
        super().setUp()
        self.dir = tempfile.mkdtemp()
        self.journal = os.path.join(self.dir, 'pending_clean.json')
        self._orig_path = Cleaner._journal_path
        Cleaner._journal_path = staticmethod(lambda: self.journal)

        self.missing = os.path.join(self.dir, 'gone.mkv')
        self.overdue = os.path.join(self.dir, 'overdue.mkv')
        self.alive = os.path.join(self.dir, 'alive.mkv')
        for p in (self.overdue, self.alive):
            with open(p, 'wb') as f:
                f.write(b'x' * 16)

    def tearDown(self) -> None:
        Cleaner._journal_path = self._orig_path
        super().tearDown()

    def _write(self, entries) -> None:
        with open(self.journal, 'w', encoding='utf-8') as f:
            json.dump(entries, f)

    def _ids(self):
        with open(self.journal, encoding='utf-8') as f:
            return sorted(e['id'] for e in json.load(f))

    def _cleaner(self, stub_submit: bool) -> Cleaner:
        c = Cleaner((queue.Queue(), queue.Queue()))
        if stub_submit:
            c.clean_executors.submit = lambda *a, **k: None
        return c

    def _entries(self):
        now = time.time()
        return [
            {'id': '1', 'due_ts': now - 100, 'pairs': [[self.missing, None]]},
            {'id': '2', 'due_ts': now - 100, 'pairs': [[self.overdue, None]]},
            {'id': '3', 'due_ts': now + 3600, 'pairs': [[self.alive, None]]},
        ]

    def test_overdue_entry_kept_until_deleted(self) -> None:
        """删除任务已提交但还没执行时，条目必须留在清单里。"""
        c = self._cleaner(stub_submit=True)
        self._write(self._entries())
        c._rearm_pending()
        self.assertEqual(self._ids(), ['2', '3'])

    def test_overdue_entry_removed_after_delete(self) -> None:
        """真正删完之后，条目才从清单移除；失效条目不复活。"""
        c = self._cleaner(stub_submit=False)
        self._write(self._entries())
        c._rearm_pending()
        deadline = time.time() + 5
        while time.time() < deadline and os.path.exists(self.overdue):
            time.sleep(0.05)
        self.assertFalse(os.path.exists(self.overdue))
        time.sleep(0.2)      # 让 _journal_remove 写完
        self.assertEqual(self._ids(), ['3'])

    def test_missing_file_entry_pruned(self) -> None:
        """文件已不存在的条目要剔除，否则每次启动都重扫废条目。"""
        c = self._cleaner(stub_submit=True)
        self._write([{'id': 'x', 'due_ts': time.time() - 1,
                      'pairs': [[self.missing, None]]}])
        c._rearm_pending()
        self.assertEqual(self._ids(), [])


if __name__ == '__main__':
    unittest.main()
