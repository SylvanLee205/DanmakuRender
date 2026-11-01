"""重新渲染因 is_danmaku_xml 导入缺失而失败的分段。

背景（2026-10-15）：
    合并上游时，DMR/utils/__init__.py 少了 `from .xml2ass import *` 这一行，
    导致 dmrender.py 的 `from DMR.utils import *` 拿不到 is_danmaku_xml，
    每次渲染都抛 NameError。受影响 3 个分段共 2.3 GB：

        1339.4 MB  vvu-2026年10月15日19点30分.mkv
         533.4 MB  小鱼大王-2026年10月15日21点21分.mkv
         462.0 MB  vvu-2026年10月15日21点26分.mkv

    根因已修（补上 xml2ass 导入）。本工具重新走一遍渲染。

安全：
    - 只渲染，不动源文件
    - 输出已存在则跳过
    - 没有配套 .ass 则跳过（渲染不出弹幕版）
    - 逐个报告结果
"""
import logging
import os
import sys

UP = r'F:\DanmakuRepo'
sys.path.insert(0, UP)
os.chdir(UP)

TARGETS = [
    r'F:\DanmakuRepo\直播回放\vvu\vvu-2026年10月15日19点30分.mkv',
    r'F:\DanmakuRepo\直播回放\小鱼大王\小鱼大王-2026年10月15日21点21分.mkv',
    r'F:\DanmakuRepo\直播回放\vvu\vvu-2026年10月15日21点26分.mkv',
]

logging.basicConfig(level=logging.WARNING,
                    format='    [%(levelname)s] %(message)s')

from DMR.Config import Config
from DMR.Render.dmrender import DmRender
from DMR.utils import VideoInfo, StreamerInfo

cfg = Config(os.path.join(UP, 'configs', 'global.yml'))
render_args = cfg.global_config['render_args']['dmrender']
out_fmt = render_args.get('format', 'mp4')
renderer = DmRender(**render_args)

print('=' * 78)
print('重新渲染 is_danmaku_xml 失败的分段')
print('=' * 78)
print(f'  渲染器: vencoder={render_args.get("vencoder")}  '
      f'format={out_fmt}')
print(f'  dmconvert={"✅" if getattr(renderer, "dmconvert", None) is not None else "❌"}  '
      f'gop_multiplier={getattr(renderer, "gop_multiplier", None)}')

ok, fail, skip = 0, 0, 0
results = []
for vf in TARGETS:
    base = os.path.basename(vf)
    task = os.path.basename(os.path.dirname(vf))
    dm = os.path.splitext(vf)[0] + '.ass'
    out_dir = os.path.join(os.path.dirname(vf), f'{task}（弹幕版）')
    out = os.path.join(out_dir,
                       os.path.splitext(base)[0] + f'（弹幕版）.{out_fmt}')

    print()
    print(f'── [{task}] {base}')
    if not os.path.exists(vf):
        print('   ⏭ 源文件不存在，跳过')
        skip += 1
        results.append((task, base, '源文件不存在'))
        continue
    print(f'   源: {os.path.getsize(vf)/1024/1024:.1f} MB')
    if not os.path.exists(dm):
        print(f'   ⏭ 没有配套弹幕文件 {os.path.basename(dm)}，跳过')
        skip += 1
        results.append((task, base, '无弹幕文件'))
        continue
    print(f'   弹幕: {os.path.basename(dm)}  '
          f'({os.path.getsize(dm)/1024:.1f} KB)')
    if os.path.exists(out):
        print(f'   ⏭ 输出已存在，跳过: {os.path.basename(out)}')
        skip += 1
        results.append((task, base, '输出已存在'))
        continue

    os.makedirs(out_dir, exist_ok=True)
    print(f'   渲染中 -> {os.path.basename(out)}')
    vi = VideoInfo(path=vf, dm_file_id=dm,
                   streamer=StreamerInfo(name=task), taskname=task)
    try:
        status, info = renderer.render_one(video=vi, output=out)
    except Exception as e:
        import traceback
        print(f'   ❌ 异常: {type(e).__name__}: {e}')
        traceback.print_exc()
        fail += 1
        results.append((task, base, f'异常 {type(e).__name__}'))
        continue

    if status and os.path.exists(out) and os.path.getsize(out) > 0:
        sz = os.path.getsize(out)
        print(f'   ✅ 成功: {sz/1024/1024:.1f} MB')
        ok += 1
        results.append((task, base, f'✅ {sz/1024/1024:.1f} MB'))
    else:
        print(f'   ❌ 失败: {str(info)[:300]}')
        fail += 1
        results.append((task, base, f'失败 {str(info)[:60]}'))

print()
print('=' * 78)
print(f'结果: 成功 {ok} / 失败 {fail} / 跳过 {skip}')
print('=' * 78)
for t, b, r in results:
    print(f'  [{t}] {b}')
    print(f'      {r}')
