# -*- coding: utf-8 -*-
"""字形清洗回归测试。

2026-11-02 实盘事故：蓝羊羊不懒一场渲染 failed，ffmpeg 报
``fontselect: failed to find any fallback with glyph 0x3103`` +
``Assertion ((dst_linesize) >= 0 ? ...) >= bytewidth failed at
libavutil/imgutils.c:351``。

根因是弹幕里出现注音符号 U+3103，而系统一个覆盖它的字体都没装。
硬件编码、软件编码都因此失败（根因在 libass 字幕帧，不在编码器）。

这些测试不依赖真实系统字体 —— 全部 mock 覆盖表，保证在任何机器上
（包括 CI）都能跑且结论一致。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from DMR.Downloader.Danmaku import glyphs


class _FakeCoverage:
    """只覆盖少量字符的假覆盖表，用来精确验证过滤逻辑。"""

    # 汉字 + 拉丁 + 假 emoji + 假日文（刻意不含任何 Bopomofo/无主块字符）
    COVERED = {0x84DD, 0x7F8A, 0x751F, 0x65E5, 0x5FEB, 0x4E50, 0x6D4B, 0x8BD5,
               0x41, 0x61, 0x3A, 0x2E, 0x1F408, 0x304B}

    # 事故字符（2026-11-02 ffmpeg 报的 0x3103）。用 chr() 显式构造，
    # 免得测试文件自身经过编辑器/编码转换后码位漂移 —— 那种情况下
    # "删掉了某个字符"的断言会假阳性通过。
    BOPOMOFO = chr(0x3103)


class TestSanitize(unittest.TestCase):
    def setUp(self):
        glyphs.reset_cache()
        self._orig = glyphs.get_coverage
        glyphs.get_coverage = lambda: _FakeCoverage.COVERED

    def tearDown(self):
        glyphs.get_coverage = self._orig
        glyphs.reset_cache()

    # ---- 必须删掉的 ----
    def test_drops_bopomofo_u3103(self):
        """事故字符：注音符号 U+3103（ffmpeg 报的 0x3103）。"""
        self.assertEqual(glyphs.sanitize(_FakeCoverage.BOPOMOFO * 2 + ': 生日快乐'), ': 生日快乐')

    def test_drops_unassigned_codepoints(self):
        """.ass 里实测还出现过的另外三种无字形字符。"""
        for cp in (0x2065, 0xFE0B, 0xFFF4):
            with self.subTest(cp=hex(cp)):
                text = '蓝' + chr(cp) + '羊'
                self.assertEqual(glyphs.sanitize(text), '蓝羊')

    def test_drops_mixed(self):
        self.assertEqual(glyphs.sanitize('蓝' + _FakeCoverage.BOPOMOFO + '羊'), '蓝羊')

    def test_replacement_char(self):
        """指定替换符时应替换而不是删除。"""
        self.assertEqual(glyphs.sanitize('蓝' + _FakeCoverage.BOPOMOFO + '羊', replacement='?'), '蓝?羊')

    # ---- 必须保留的 ----
    def test_keeps_ascii_fast_path(self):
        self.assertEqual(glyphs.sanitize('hello world 123'), 'hello world 123')

    def test_keeps_covered_cjk(self):
        self.assertEqual(glyphs.sanitize('蓝羊羊生日快乐测试'), '蓝羊羊生日快乐测试')

    def test_keeps_covered_emoji_and_kana(self):
        self.assertEqual(glyphs.sanitize('🐈か'), '🐈か')

    def test_keeps_whitespace_and_control(self):
        """空白/控制字符不能被当"缺字形"处理掉（ass 结构需要）。"""
        text = '蓝\n羊\t羊 羊\r'
        self.assertEqual(glyphs.sanitize(text), text)

    def test_keeps_bom_and_zero_width(self):
        text = '蓝' + chr(0xFEFF) + '羊'
        self.assertEqual(glyphs.sanitize(text), text)

    def test_empty_and_none(self):
        self.assertEqual(glyphs.sanitize(''), '')
        self.assertIsNone(glyphs.sanitize(None))

    # ---- 降级行为 ----
    def test_no_coverage_means_passthrough(self):
        """检测不可用时必须原样放行，不能把弹幕全删了。"""
        glyphs.get_coverage = lambda: None
        self.assertEqual(glyphs.sanitize(_FakeCoverage.BOPOMOFO * 2 + ': 生日快乐'), _FakeCoverage.BOPOMOFO * 2 + ': 生日快乐')

    def test_empty_coverage_means_passthrough(self):
        glyphs.get_coverage = lambda: set()
        self.assertEqual(glyphs.sanitize(_FakeCoverage.BOPOMOFO * 2), _FakeCoverage.BOPOMOFO * 2)


class TestCoverageCache(unittest.TestCase):
    """缓存读写与失效。"""

    def setUp(self):
        self._orig = glyphs.get_coverage
        glyphs.reset_cache()

    def tearDown(self):
        glyphs.get_coverage = self._orig
        glyphs.reset_cache()

    def test_signature_is_stable(self):
        sig1 = glyphs._font_signature()
        sig2 = glyphs._font_signature()
        self.assertEqual(sig1, sig2)

    def test_cache_roundtrip(self):
        sig = 'testsig'
        covered = {0x41, 0x84DD}
        glyphs._save_cache(sig, covered)
        loaded = glyphs._load_cache(sig)
        self.assertEqual(loaded, covered)

    def test_cache_rejects_wrong_signature(self):
        glyphs._save_cache('sig-a', {0x41})
        self.assertIsNone(glyphs._load_cache('sig-b'))

    def test_scan_fonts_returns_nonempty_on_this_machine(self):
        """本机有字体时应能建表（CI 无字体时跳过，不算失败）。"""
        covered = glyphs._scan_fonts()
        if not covered:
            self.skipTest('本机没有可解析的字体')
        self.assertIn(0x84DD, covered, '汉字「蓝」必须可渲染')

    def test_reset_cache_removes_file(self):
        glyphs._save_cache('sig-x', {0x41})
        self.assertTrue(os.path.isfile(glyphs._cache_path()))
        glyphs.reset_cache()
        self.assertFalse(os.path.isfile(glyphs._cache_path()))


if __name__ == '__main__':
    unittest.main()
