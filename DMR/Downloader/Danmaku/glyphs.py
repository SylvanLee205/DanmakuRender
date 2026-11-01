# -*- coding: utf-8 -*-
"""字形安全检测：把「渲染会崩」的字符从弹幕里剔掉。

背景（2026-11-02 实盘事故）
--------------------------
蓝羊羊不懒 2026-11-01 23:58 那场渲染 failed，日志长这样：

    [Parsed_subtitles_0] fontselect: failed to find any fallback with
        glyph 0x3103 for font: (Source Han Sans SC, 700, 0)
    Assertion ((dst_linesize) >= 0 ? ...) >= bytewidth failed at
        libavutil/imgutils.c:351

根因是弹幕里出现了注音符号「ㄓ」（U+3103，粉丝打出来的谐音昵称）。
Source Han Sans SC 不含 Bopomofo 字形，而这台机器上**一个覆盖它的字体都没装**
（微软正黑体 msjh 不在），于是：

    libass 找不到字形 → 输出异常帧 → ffmpeg 断言失败 → 整条渲染挂掉

**但清洗掉 U+3103 之后照样崩** —— 第二类真凶是彩色 emoji 字体：

    Glyph 0x1F1E8 not found, selecting one more font for (Source Han Sans SC, 700, 0)
    fontselect: (Source Han Sans SC, 700, 0) -> SegoeUIEmoji, 0, SegoeUIEmoji
    Assertion ((dst_linesize) >= 0 ? ...) >= bytewidth failed at imgutils.c:351

U+1F1E8 是国旗区域指示符（🇨🇳 的前半段）。Segoe UI Emoji 是 **COLR/CBDT
彩色字体**，libass 对彩色字形的位图 stride 处理有缺陷，一样触发同一个断言。
🐈 🎂 🌈 这些常见 emoji 也在 SegoeUIEmoji 里，同样会崩。

三个坑记一下：

1. **硬件/软件编码都会失败** —— 根因在 libass 的字幕帧，不在编码器。
   DMR 那套「hevc_qsv 失败就降级 libx265」对这类故障无效（实测降级后
   同样断言失败，任务最终还是 failed）。别指望编码器降级能救。
2. **PIL 救不了场** —— ``ImageFont.getbbox()`` 对缺字形返回的是 .notdef
   方框，尺寸和正常字符一样，区分不出来。只有 fontTools 查 cmap 可靠。
3. **"能渲染"不等于"能安全渲染"** —— 必须有字形，且那个字形不能只存在于
   彩色字体里。所以这里维护两个集合：``covered``（有字形）与
   ``unsafe``（只有彩色字体有字形，libass 会崩）。

做法：首条弹幕时扫一遍系统字体，建这两张表，之后每条弹幕过一遍，
把表外字符、以及 unsafe 字符删掉。扫描结果按字体目录指纹缓存，
装新字体会自动重建。

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
_unsafe = None            # set[int]：只有彩色字体有字形，libass 会崩
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


def _is_color_font(font) -> bool:
    """是否彩色字体（COLR/CBDT/sbix 任一）。

    libass 对这类字体的位图 stride 处理有缺陷，会触发 ffmpeg 的
    imgutils.c 断言。Segoe UI Emoji 就是典型。
    """
    try:
        tags = set(font.keys())
    except Exception:
        return False
    return bool(tags & {'COLR', 'CBDT', 'sbix', 'CBDT ', 'COLR '})


def _family_name(font) -> str:
    """字体族名（nameID 1 / 16），匹配不上返回空串。"""
    try:
        nt = font['name']
        for nid in (16, 1):
            v = nt.getDebugName(nid)
            if v:
                return v
    except Exception:
        pass
    return ''


def _scan_fonts(primary_name='Source Han Sans SC'):
    """扫系统字体，返回 (covered, unsafe)。

    :param covered: 有字形的码位（不管来自哪种字体）
    :param unsafe: **会回退到彩色字体**的码位 —— libass 的 fontselect
        在主字体里找不到字形时才回退，而它对彩色字形的位图 stride 处理
        有缺陷，一样触发 ffmpeg 的 imgutils.c 断言。

    判据为什么是 ``color - primary``：
    * 用 ``color``（彩色字体覆盖的一切）太宽 —— 彩色字体的 cmap 通常也含
      完整 ASCII 区，会把英文数字全删掉。
    * 用 ``color - plain``（"只有彩色字体有字形"）太窄 —— U+1F1E8 /
      U+1F408 在 SegoeUISymbol 等单色字体的 cmap 里也有声明，会被判为
      安全；但 libass 按自己的优先级选，实际选了 seguiemj.ttf，照样崩。
    * 正解：**主字体有字形就不会回退**。所以只有"主字体没有、彩色字体有"
      的码位才真正危险。
    """
    from fontTools.ttLib import TTCollection, TTFont

    plain = set()            # 普通（单色）字体覆盖
    color = set()            # 彩色字体覆盖
    primary = set()          # 主字体覆盖（渲染时根本不会回退的）
    primary_found = False
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
                        cmap = set(f.getBestCmap().keys())
                    except Exception:
                        continue
                    is_primary = bool(primary_name) and \
                        _family_name(f) == primary_name
                    if is_primary:
                        primary_found = True
                        primary |= cmap
                    if _is_color_font(f):
                        color |= cmap
                    else:
                        plain |= cmap
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
    covered = plain | color | primary
    if not primary_found:
        # 主字体都没认出来（改名/换字体了）：不敢判 unsafe，
        # 退化成"只过滤无字形字符"，至少不会误删英文数字。
        logger.warning('没找到主字体 %r 的字体文件，本次只过滤无字形字符'
                       '（彩色字体保护未启用）', primary_name)
        return covered, set()
    return covered, color - primary


def _load_cache(sig):
    path = _cache_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        if data.get('sig') != sig:
            return None
        cov = set(data.get('cps') or [])
        unsafe = set(data.get('unsafe') or [])
        return cov, unsafe
    except Exception:
        return None


def _save_cache(sig, covered, unsafe):
    path = _cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump({'sig': sig, 'cps': sorted(covered),
                       'unsafe': sorted(unsafe)}, fh)
        os.replace(tmp, path)     # 原子替换，避免半页缓存
    except Exception as e:
        logger.debug('字形覆盖缓存写入失败（不影响功能）: %s', e)


def primary_font_name() -> str:
    """DMR 实际使用的正文字体（决定"哪些字符不会触发回退"）。

    读 ``configs/global.yml`` 的 ``download_args.live.font``；
    读不到就退回默认 'Source Han Sans SC'（DanmakuRender 的出厂值）。
    """
    default = 'Source Han Sans SC'
    try:
        import yaml
        cfg = os.path.join(os.path.dirname(_cache_path()), '..', 'configs',
                           'global.yml')
        cfg = os.path.normpath(cfg)
        if os.path.isfile(cfg):
            data = yaml.safe_load(open(cfg, encoding='utf-8')) or {}
            live = (data.get('download_args') or {}).get('live') or {}
            name = live.get('font')
            if name:
                return str(name)
    except Exception:
        pass
    return default


def get_coverage():
    """返回 (covered, unsafe)；拿不到就返回 None（调用方应放行不过滤）。"""
    global _coverage, _unsafe, _checked_at
    with _lock:
        # 已建好且不超过 1 小时，直接用（弹幕量很大，不能每次都查）
        if _coverage is not None and time.time() - _checked_at < 3600:
            return _coverage, _unsafe
        try:
            sig = _font_signature()
            cached = _load_cache(sig)
            if cached is not None:
                _coverage, _unsafe = cached
                _checked_at = time.time()
                return _coverage, _unsafe
            covered, unsafe = _scan_fonts(primary_font_name())
            if not covered:
                return None         # 一个都没解析出来，宁可不过滤
            _save_cache(sig, covered, unsafe)
            _coverage, _unsafe = covered, unsafe
            _checked_at = time.time()
            logger.info('字形覆盖表已建立：%d 个码位可渲染，其中 %d 个'
                        '只能由彩色字体渲染（已列入黑名单）',
                        len(covered), len(unsafe))
            return _coverage, _unsafe
        except Exception as e:
            logger.warning('字形安全检测失败，本次不过滤弹幕字符: %s', e)
            return None


def is_safe(cp: int, covered=None, unsafe=None) -> bool:
    """这个码位能不能安全渲染（有字形，且不只依赖彩色字体）。"""
    if covered is None or unsafe is None:
        got = get_coverage()
        if got is None:
            return True            # 检测不可用，宁可放行
        covered, unsafe = got
    if cp not in covered:
        return False
    return cp not in unsafe


def sanitize(text, replacement=''):
    """删掉渲染会崩的字符：无字形的，以及只能靠彩色字体渲染的。

    :param text: 原始弹幕/用户名
    :param replacement: 替换成什么，默认直接删除
    :return: 清洗后的文本；检测不可用时原样返回
    """
    if not text:
        return text
    # 纯 ASCII 快速路径：绝大多数弹幕走这条，零开销
    if text.isascii():
        return text
    got = get_coverage()
    if not got:
        return text
    covered, unsafe = got
    if not covered:
        return text
    out = []
    dropped = []
    for ch in text:
        cp = ord(ch)
        # 控制/空白/格式字符不过滤（宽度为零或无字形概念，
        # 且 \r\n\t 是 ass 结构需要的）
        if cp < 0x20 or ch.isspace() or cp in (0xFEFF,):
            out.append(ch)
            continue
        if cp in covered and cp not in unsafe:
            out.append(ch)
        else:
            out.append(replacement)
            dropped.append(cp)
    if dropped:
        # 区分两种原因，排障时省一半时间
        no_glyph = [c for c in dropped if c not in covered]
        color_only = [c for c in dropped if c in covered]
        logger.debug('弹幕字符清洗：剔除 %d 个字符'
                     '（无字形 %d 个如 U+%04X；彩色字体专用 %d 个如 U+%04X）',
                     len(dropped), len(no_glyph),
                     no_glyph[0] if no_glyph else 0,
                     len(color_only), color_only[0] if color_only else 0)
    return ''.join(out)


def reset_cache():
    """手动失效（测试/排查用）。"""
    global _coverage, _unsafe, _checked_at
    with _lock:
        _coverage, _unsafe, _checked_at = None, None, 0.0
        try:
            os.remove(_cache_path())
        except OSError:
            pass
