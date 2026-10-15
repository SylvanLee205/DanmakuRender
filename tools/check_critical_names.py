"""启动自检：确保核心渲染/上传路径需要的名字都能拿到。

⚠️ 为什么需要（2026-10-15 事故）：
    合并上游时 DMR/utils/__init__.py 少了 `from .xml2ass import *`，
    导致 dmrender.py 的 `from DMR.utils import *` 拿不到 is_danmaku_xml。
    这个错误**只在真正渲染时才暴露**，而且会让每一个分段都渲染失败
    （3 个分段 2.3 GB 白白滞留，直到用户发现终端在报错）。

    tools/check_imports.py 之前没抓到，因为它只检查"模块能 import"，
    而 is_danmaku_xml 是在函数内部使用、只有调用时才解析。

这个自检列出"关键函数依赖的名字"，逐个确认可获取。
"""
import importlib
import os
import sys

PROD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROD)
os.chdir(PROD)

# (模块, [该模块用到的、来自 import * 的名字])
# 这些名字都在函数体内使用，import 期不会报错，只有调用时才炸
CHECK = [
    ('DMR.Render.dmrender',
     ['is_danmaku_xml', 'xml_to_ass', 'DEFAULT_ASS_SUFFIX',
      'FFprobe', 'VideoInfo', 'StreamerInfo', 'safe_filename',
      'replace_keywords']),
    ('DMR.Cleaner', ['basename', 'FileInfo', 'exists', 'isdir']),
    # 注意：DMR.Uploader 里没有 SubprocessUploader —— 上传引擎是**惰性加载**的
    #（通过 _UPLOADER_ENGINES 注册表按需 import），这是正确设计，不是缺陷。
    # 所以这里只检查确实该在顶层可见的名字。
    ('DMR.Uploader', ['VideoInfo', 'Uploader']),
    ('DMR.Downloader.stream_downloader',
     ['basename', 'VideoInfo', 'StreamerInfo', 'replace_keywords',
      'rename_safe', 'FFprobe']),
    ('DMR.Task.liveevents', ['PROGRESS', 'PipeMessage', 'VideoInfo',
                             'ArtifactState', 'ArtifactKind']),
]

print('=' * 78)
print('启动自检：关键名字可用性')
print('=' * 78)

bad_total = 0
for mod, names in CHECK:
    try:
        m = importlib.import_module(mod)
    except Exception as e:
        print(f'  ❌ {mod}: 无法导入 — {type(e).__name__}: {e}')
        bad_total += 1
        continue
    miss = [n for n in names if not hasattr(m, n)]
    if miss:
        print(f'  ❌ {mod}')
        print(f'      缺失: {miss}')
        bad_total += len(miss)
    else:
        print(f'  ✅ {mod}  ({len(names)} 个名字)')

print()
print('=' * 78)
if bad_total:
    print(f'  🔴 发现 {bad_total} 个问题！渲染/上传可能失败。')
    print('     常见原因：某个 __init__.py 少了 `from .xxx import *`')
    sys.exit(1)
else:
    print('  ✅ 全部可用 —— 渲染/上传路径没有"用了但拿不到"的名字')
    sys.exit(0)
