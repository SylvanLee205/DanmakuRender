"""通过 DMR 的渲染管线重渲染断尾人类那个分段。

目的有两个：
  1. 补上缺失的弹幕版
  2. 验证新加的「硬件编码失败 → 软件编码降级」是否真的生效
     （用户的批量渲染脚本正占用 QSV，所以硬件那步预计会失败）
"""
import logging
import os
import sys
import time

sys.path.insert(0, r'F:\DanmakuRender_AutoUp')
os.chdir(r'F:\DanmakuRender_AutoUp')
logging.basicConfig(
    level=logging.INFO,
    format='  [%(levelname)s] %(name)s: %(message)s')

from DMR.Config import Config
from DMR.Render.dmrender import DmRender
from DMR.utils import VideoInfo, StreamerInfo

SRC = r'./直播回放/断尾人类\断尾的人类不会喵-2026年10月18日22点52分.mkv'
DM = r'./直播回放/断尾人类\断尾的人类不会喵-2026年10月18日22点52分.ass'
OUT = r'./直播回放/断尾人类（弹幕版）\断尾的人类不会喵-2026年10月18日22点52分（弹幕版）.mp4'

if os.path.exists(OUT):
    print(f'  删除已有输出: {os.path.getsize(OUT)/1024**2:.1f} MB')
    os.remove(OUT)

cfg = Config(r'F:\DanmakuRender_AutoUp\configs\global.yml')
r = DmRender(**cfg.global_config['render_args']['dmrender'])

print('=' * 74)
print('通过 DMR 渲染管线重渲染（含硬件→软件降级）')
print('=' * 74)
print(f'  主编码器:   {r.vencoder}')
print(f'  降级编码器: {r.fallback_vencoder} {r.fallback_vencoder_args}')

vi = VideoInfo(path=SRC, dm_file_id=DM,
               streamer=StreamerInfo(name='断尾的人类不会喵'),
               taskname='断尾人类', dtype='src_video')

t0 = time.time()
status, info = r.render_one(video=vi, output=OUT)
el = time.time() - t0

print()
print('=' * 74)
print(f'结果: {"✅ 成功" if status else "❌ 失败"}   耗时 {el/60:.1f} 分钟')
print('=' * 74)

if status:
    sz = os.path.getsize(OUT)
    print(f'  产物: {sz/1024**2:.1f} MB')
    # 时长校验
    import subprocess

    def dur(p):
        rr = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                             'format=duration', '-of',
                             'default=nw=1:nk=1', p],
                            capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=300)
        try:
            return float((rr.stdout or '0').strip() or 0)
        except ValueError:
            return 0.0

    sd = dur(SRC.replace('/', os.sep))
    od = dur(OUT.replace('/', os.sep))
    print(f'  源时长 {sd:.0f}s   产物时长 {od:.0f}s   比例 {od/sd*100:.1f}%' if sd else '')
    if sd and od / sd >= 0.9:
        print('  ✅ 时长正常')
    else:
        print('  ❌ 时长仍残缺')
else:
    print(f'  信息: {str(info)[:500]}')
