"""弹幕版永不清理 —— 硬约束回归测试（2026-10-19）。

用户原话："弹幕版文件永远不清理，这是重中之重。"
所以这条规则写在**代码**里，不只是 clean_args 配置：
  · `liveevents._check_for_clean` 不再把 dm_video 自身放进清理任务
  · `Cleaner._clean_subprocess` 就算收到 dm_video 路径也拒绝删除
  · `Cleaner._rearm_pending` 把历史待删清单里的 dm_video 条目剔除
  · 状态释放按 vtype 判断，与配置无关

这里锁住最关键的一道：Cleaner 真的会拒绝删。
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import unittest

from DMR.Cleaner import Cleaner, is_dm_video_path


class _FakeFile:
    """替代 FileInfo：_clean_subprocess 只用到 .path 和 .get('dm_file_id')。"""

    def __init__(self, path):
        self.path = path

    def get(self, key, default=None):
        return default


def _bare_cleaner():
    """不跑 __init__（会起线程/读清单），只装最小的依赖。"""
    obj = object.__new__(Cleaner)
    obj.logger = logging.getLogger('test.cleaner')
    obj._pipeSend = lambda *a, **k: None
    obj._journal_remove = lambda *a, **k: None
    return obj


class TestDmVideoPath(unittest.TestCase):

    def test_recognises_render_output_dir(self) -> None:
        self.assertTrue(is_dm_video_path(
            r'./直播回放/灰蒙蒙（弹幕版）\灰蒙蒙is-2026年10月19日14点56分（弹幕版）.mp4'))
        self.assertTrue(is_dm_video_path(
            '/f/DanmakuRender_AutoUp/直播回放/vvu（弹幕版）/vvu-x.mp4'))

    def test_ignores_source_files(self) -> None:
        self.assertFalse(is_dm_video_path(
            r'./直播回放/灰蒙蒙\灰蒙蒙is-2026年10月19日14点56分.ts'))
        self.assertFalse(is_dm_video_path(
            r'./直播回放/灰蒙蒙\灰蒙蒙is-2026年10月19日14点56分.ass'))
        self.assertFalse(is_dm_video_path(None))
        self.assertFalse(is_dm_video_path(''))


class TestCleanerRefusesDmVideo(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix='dmr_keep_dm_')
        self.dm_dir = os.path.join(self.tmp, '灰蒙蒙（弹幕版）')
        os.makedirs(self.dm_dir)
        self.dm_file = os.path.join(self.dm_dir, '灰蒙蒙-2026年10月19日14点56分（弹幕版）.mp4')
        with open(self.dm_file, 'wb') as f:
            f.write(b'\0' * 2048)

        self.src_dir = os.path.join(self.tmp, '灰蒙蒙')
        os.makedirs(self.src_dir)
        self.src_file = os.path.join(self.src_dir, '灰蒙蒙-2026年10月19日14点56分.ts')
        with open(self.src_file, 'wb') as f:
            f.write(b'\0' * 2048)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, files):
        cleaner = _bare_cleaner()
        cleaner._clean_subprocess({
            'method': 'delete',
            'args': {},
            'files': [_FakeFile(p) for p in files],
            'source': 'replay/灰蒙蒙',
            'request_id': 'test',
        })

    def test_dm_video_survives_delete(self) -> None:
        self._run([self.dm_file])
        self.assertTrue(os.path.exists(self.dm_file),
                        '弹幕版被删了！这是不可恢复的数据丢失')

    def test_source_still_deleted_normally(self) -> None:
        # 保护只针对弹幕版，源文件该删还是要删
        self._run([self.src_file])
        self.assertFalse(os.path.exists(self.src_file))

    def test_mixed_batch_only_removes_source(self) -> None:
        self._run([self.src_file, self.dm_file])
        self.assertFalse(os.path.exists(self.src_file))
        self.assertTrue(os.path.exists(self.dm_file))


if __name__ == '__main__':
    unittest.main()
