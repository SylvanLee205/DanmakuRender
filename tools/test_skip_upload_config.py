"""用真实 global.yml 的规则验证当前生效行为。"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.WARNING)

from DMR.Config import Config
from DMR.utils import VideoInfo, StreamerInfo, evaluate_upload_skip_rule

cfg = Config('configs/global.yml')
rule = cfg.global_config['render_args']['dmrender'].get('skip_upload_rule')
print('当前 global.yml 生效的规则:')
for k, v in (rule or {}).items():
    print(f'    {k}: {v}')
print()

cases = [
    ('横屏 1080p 6000kbps 30fps', (1920, 1080), 6000, 30),
    ('横屏 1080p 6000kbps 60fps', (1920, 1080), 6000, 60),
    ('横屏 1080p 2500kbps 40fps', (1920, 1080), 2500, 40),
    ('横屏 1080p 1500kbps 30fps', (1920, 1080), 1500, 30),
    ('横屏 1080p 2499kbps 39fps', (1920, 1080), 2499, 39),
    ('竖屏 1080x1920 8000kbps 60fps', (1080, 1920), 8000, 60),
    ('竖屏 1080x1920 1000kbps 30fps', (1080, 1920), 1000, 30),
]

print('判定结果:')
for name, res, br, fps in cases:
    size = int(br * 1000 / 8 * 3600)
    v = VideoInfo(path=r'F:\fake\x.mp4', size=size, duration=3600, resolution=res,
                  streamer=StreamerInfo(name='t'), taskname='t')
    v.fps = fps
    v.bitrate = br
    skip, detail = evaluate_upload_skip_rule(v, rule)
    print(f'  {name:<32} -> {"【跳过上传】" if skip else "正常上传  "}  {detail}')
