"""模拟启动：加载完整配置并检查所有任务的解析结果。"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append('./tools')

logging.basicConfig(level=logging.WARNING)

from DMR.Config import Config

cfg = Config('configs/global.yml')
print('配置对象创建成功')

tasks = cfg.get_replaytasks()
print(f'已加载任务数: {len(tasks)}')

print('\n前 8 个任务:')
for t in tasks[:8]:
    rc = cfg.get_replay_config(t)
    ce = rc['common_event_args']
    up = list((rc.get('upload_args') or {}).keys())
    print(f'  - {t}: render={ce.get("auto_render")} upload={ce.get("auto_upload")} '
          f'clean={ce.get("auto_clean")} upload_args={up}')

# 统计各任务的清理规则来源
kinds = {}
for t in tasks:
    rc = cfg.get_replay_config(t)
    ca = rc.get('clean_args') or {}
    for file_types, rules in ca.items():
        for r in (rules if isinstance(rules, list) else [rules]):
            key = (file_types, r.get('method'))
            kinds[key] = kinds.get(key, 0) + 1
print('\n清理规则分布 (文件类型, 方法) -> 任务数:')
for k, v in sorted(kinds.items(), key=lambda x: -x[1]):
    print(f'  {k}: {v}')

# 检查有没有任务打开了 auto_upload（当前都没开）
uploading = [t for t in tasks if cfg.get_replay_config(t)['common_event_args'].get('auto_upload')]
print(f'\n当前开启 auto_upload 的任务: {uploading if uploading else "无"}')
rendering = [t for t in tasks if cfg.get_replay_config(t)['common_event_args'].get('auto_render')]
print(f'当前开启 auto_render 的任务数: {len(rendering)}')
print('\n启动路径验证通过')
