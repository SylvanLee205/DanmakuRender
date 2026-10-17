"""验证 dm_filter.dm_type 改动是否按预期生效。"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.ERROR)

from DMR.Config import Config

cfg = Config('configs/global.yml')
live = cfg.global_config['download_args']['live']
dm_type = live['dm_filter']['dm_type']

print(f'  dm_filter.dm_type = {dm_type!r}')
print()
print('  实际效果（复刻 danmaku.py:130-133 的判断）:')
for name, dtype in [('纯文字弹幕', 'danmaku'), ('礼物', 'gift'), ('进场', 'entry'), ('超级弹幕', 'superchat')]:
    passed = (dm_type == 'all') or (dtype in dm_type)
    print(f'    {name:<8} -> {"收" if passed else "过滤"}')

print()
print(f'  礼物模板会生效: {bool(live["dm_template"].get("gift"))}')
print(f'  进场模板为空（不显示进场）: {live["dm_template"].get("entry") is None}')
