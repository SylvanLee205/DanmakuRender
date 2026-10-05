"""重新渲染之前因 libopus bug 失败的源文件（bug 已修，应该能成功）。"""
import os
import subprocess
import sys
import time

UP = r'F:\DanmakuRender_AutoUp'
sys.path.insert(0, UP)
os.chdir(UP)

TARGETS = [
    r'F:\DanmakuRender_AutoUp\直播回放\苏苏没烦恼\苏苏没烦恼-2026年10月04日00点24分.mkv',
    r'F:\DanmakuRender_AutoUp\直播回放\哭哭不嘻嘻\哭哭不嘻嘻-2026年10月04日00点24分.mkv',
]

import logging
logging.basicConfig(level=logging.WARNING, format='    [%(levelname)s] %(message)s')

from DMR.Config import Config
from DMR.Render.dmrender import DmRender
from DMR.utils import VideoInfo, StreamerInfo

cfg = Config('configs/global.yml')
render_args = cfg.global_config['render_args']['dmrender']
out_fmt = render_args.get('format', 'mp4')
renderer = DmRender(**render_args)

print('=' * 78)
print('重新渲染之前 libopus 失败的源文件')
print('=' * 78)

ok, fail = 0, 0
for vf in TARGETS:
    task = os.path.basename(os.path.dirname(vf))
    dm = os.path.splitext(vf)[0] + '.ass'
    print(f'\n--- [{task}] {os.path.basename(vf)}')
    if not os.path.exists(vf):
        print(f'    源文件不存在: {vf}')
        continue
    print(f'    源: {os.path.getsize(vf)/1024/1024:.1f} MB')
    if not os.path.exists(dm):
        print(f'    弹幕不存在: {dm} → 跳过')
        continue
    print(f'    弹幕: {os.path.getsize(dm)} 字节')

    out_dir = os.path.join(os.path.dirname(vf) + '（弹幕版）')
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, os.path.splitext(os.path.basename(vf))[0]
                       + f'（弹幕版）.{out_fmt}')
    print(f'    输出: {out}')
    t0 = time.time()
    vi = VideoInfo(path=vf, dm_file_id=dm,
                   streamer=StreamerInfo(name=task), taskname=task)
    try:
        status, info = renderer.render_one(video=vi, output=out)
    except Exception as e:
        print(f'    ❌ 渲染异常: {type(e).__name__}: {e}')
        fail += 1
        continue
    el = time.time() - t0
    if status:
        sz = os.path.getsize(out)
        print(f'    ✅ 成功，{el:.0f} 秒，{sz/1024/1024:.1f} MB')
        ok += 1
    else:
        print(f'    ❌ 失败（{el:.0f} 秒）: {str(info)[:400]}')
        fail += 1

print()
print('=' * 78)
print(f'重新渲染: {ok} 成功 / {fail} 失败')
print('=' * 78)
