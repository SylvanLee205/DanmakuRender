# -*- coding: utf-8 -*-
"""字形覆盖检测：把"系统里没有任何字体能渲染"的字符从弹幕里剔掉。

背景（2026-11-02 实盘事故）
--------------------------
蓝羊羊不懒 2026-11-01 23:58 那场渲染失败，日志长这样：

    [Parsed_subtitles_0] fontselect: failed to find any fallback with
        glyph 0x3103 for font: (Source Han Sans SC, 700, 0)
    Assertion ((dst_linesize) >= 0 ? ...) >= bytewidth failed at
        libavutil/imgutils.c:351

根因是弹幕里出现了注音符号「ㄓ」（U+3103，粉丝打出来的谐音昵称）。
Source Han Sans SC 不含 Bopomofo 字形，而这台机器上**一个覆盖它的字体都没装**
（微软正黑体 msjh 不在），于是：

    libass 找不到字形 → 输出异常帧 → ffmpeg 断言失败 → 整条渲染挂掉

两个坑记一下：

1. **硬件/软件编码都会失败** —— 根因在 libass 的字幕帧，不在编码器。
   DMR 那套「hevc_qsv 失败就降级 libx265」对这类故障无效（实测降级后
   同样断言失败，任务最终还是 failed）。所以别指望编码器降级能救。
2. **PIL 救不了场** —— ``ImageFont.getbbox()`` 对缺字形返回的是 .notdef
   方框，尺寸和正常字符一样，区分不出来。只有 fontTools 查 cmap 可靠。

做法：首条弹幕时扫一遍系统字体建"可渲染码位表"，之后每条弹幕过一遍，
把表外字符删掉。扫描结果按字体目录指纹缓存，装新字体会自动重建。

依赖：fontTools（已加入 requirements.txt，纯 Python）。
"""
import hashlib
import json
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

# 参与扫描的字体目录（系统 + 当前用户）
FONT_DIRS = [
    os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'Fonts'),
    os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\Windows\Fonts'),
]
FONT_EXTS = ('.ttf', '.otf', '.ttc', '.otc')

# 缓存放在 .temp/（与 DMR 其他中间状态同目录，已在 .gitignore 里）
_CACHE_NAME = 'glyph_coverage.json'

_lock = threading.Lock()
_coverage = None          # set[int] | None（None=还没建；空 set=禁用过滤）
_checked_at = 0.0


def _cache_path():
    try:
        from DMR.Config import Config
        root = os.path.dirname(os.path.abspath(Config.__file__))
        # DMR/Config/__init__.py -> 项目根
        base = os.path.dirname(os.path.dirname(root))
    except Exception:
        base = os.getcwd()
    return os.path.join(base, '.temp', _CACHE_NAME)


def _font_signature():
    """字体目录指纹：文件路径+大小+mtime 的哈希。装/删字体后自动变。"""
    h = hashlib.sha1()
    for d in FONT_DIRS:
        if not os.path.isdir(d):
            continue
        h.update(d.encode('utf-8', 'replace'))
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            if not n.lower().endswith(FONT_EXTS):
                continue
            p = os.path.join(d, n)
            try:
                st = os.stat(p)
                h.update(('%s|%d|%d' % (n, st.st_size, int(st.st_mtime)))
                         .encode('utf-8', 'replace'))
            except OSError:
                continue
    return h.hexdigest()


def _scan_fonts():
    """扫系统字体，返回可渲染码位集合。单个字体解析失败不影响整体。"""
    from fontTools.ttLib import TTCollection, TTFont

    covered = set()
    for d in FONT_DIRS:
        if not os.path.isdir(d):
            continue
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            if not n.lower().endswith(FONT_EXTS):
                continue
            path = os.path.join(d, n)
            fonts = []
            closables = []
            try:
                if n.lower().endswith(('.ttc', '.otc')):
                    coll = TTCollection(path, lazy=True)
                    closables.append(coll)
                    fonts = list(coll.fonts)
                else:
                    fh = TTFont(path, lazy=True)
                    closables.append(fh)
                    fonts = [fh]
                for f in fonts:
                    try:
                        covered.update(f.getBestCmap().keys())
                    except Exception:
                        continue
            except Exception:
                continue          # 损坏/加密字体，跳过
            finally:
                # fontTools 不会自动关句柄；167 个字体一路扫下来不关，
                # Windows 上会攒一批打开的文件句柄（ResourceWarning）。
                for c in closables:
                    try:
                        c.close()
                    except Exception:
                        pass
    return covered


def _load_cache(sig):
    path = _cache_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        if data.get('sig') != sig:
            return None
        return set(data.get('cps') or [])
    except Exception:
        return None


def _save_cache(sig, covered):
    path = _cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump({'sig': sig, 'cps': sorted(covered)}, fh)
        os.replace(tmp, path)     # 原子替换，避免半页缓存
    except Exception as e:
        logger.debug('字形覆盖缓存写入失败（不影响功能）: %s', e)


def get_coverage():
    """返回可渲染码位集合；拿不到就返回 None（调用方应放行不过滤）。"""
    global _coverage, _checked_at
    with _lock:
        # 已建好且不超过 1 小时，直接用（弹幕量很大，不能每次都查）
        if _coverage is not None and time.time() - _checked_at < 3600:
            return _coverage
        try:
            sig = _font_signature()
            cached = _load_cache(sig)
            if cached is not None:
                _coverage, _checked_at = cached, time.time()
                return _coverage
            covered = _scan_fonts()
            if not covered:
                return None         # 一个都没解析出来，宁可不过滤
            _save_cache(sig, covered)
            _coverage, _checked_at = covered, time.time()
            logger.info('字形覆盖表已建立：%d 个码位可渲染', len(covered))
            return _coverage
        except Exception as e:
            logger.warning('字形覆盖检测失败，本次不过滤弹幕字符: %s', e)
            return None


def sanitize(text, replacement=''):
    """删掉系统无法渲染的字符。

    :param text: 原始弹幕/用户名
    :param replacement: 替换成什么，默认直接删除
    :return: 清洗后的文本；检测不可用时原样返回
    """
    if not text:
        return text
    # 纯 ASCII 快速路径：绝大多数弹幕走这条，零开销
    if text.isascii():
        return text
    covered = get_coverage()
    if not covered:
        return text
    out = []
    dropped = 0
    for ch in text:
        cp = ord(ch)
        # 控制/空白/格式字符不过滤（宽度为零或无字形概念，
        # 且 \r\n\t 是 ass 结构需要的）
        if cp < 0x20 or ch.isspace() or cp in (0xFEFF,):
            out.append(ch)
            continue
        if cp in covered:
            out.append(ch)
        else:
            out.append(replacement)
            dropped += 1
    if dropped:
        try:
            logger.debug('弹幕字符清洗：剔除 %d 个无字形字符（如 U+%04X）',
                         dropped, ord(next(c for c in text
                                           if ord(c) >= 0x20
                                           and not c.isspace()
                                           and ord(c) not in covered)))
        except Exception:
            pass
    return ''.join(out)


def reset_cache():
    """手动失效（测试/排查用）。"""
    global _coverage, _checked_at
    with _lock:
        _coverage, _checked_at = None, 0.0
        try:
            os.remove(_cache_path())
        except OSError:
            pass
