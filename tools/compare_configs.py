"""对比原版与魔改版的关键配置是否一致。"""
import yaml

PAIRS = [
    ('原版  F:/123Pan_DanmakuRender', r'F:\123Pan_DanmakuRender\configs\global.yml'),
    ('魔改版 F:/DanmakuRender-魔改版', r'F:\DanmakuRender-魔改版\configs\global.yml'),
]

KEYS = [
    ('download_args', 'live', 'engine'),
    ('download_args', 'live', 'segment'),
    ('download_args', 'live', 'output_format'),
    ('download_args', 'live', 'danmaku'),
    ('download_args', 'live', 'video'),
    ('download_args', 'live', 'dm_format'),
    ('render_args', 'dmrender', 'vencoder'),
    ('render_args', 'dmrender', 'aencoder'),
    ('render_args', 'dmrender', 'gop_multiplier'),
    ('upload_args', None, None),
]

data = {}
for name, path in PAIRS:
    data[name] = yaml.safe_load(open(path, encoding='utf-8'))

print('=== 逐项对比 ===')
for path in KEYS:
    row = []
    for name, _ in PAIRS:
        node = data[name]
        for k in path:
            if k is None:
                break
            node = node.get(k) if isinstance(node, dict) else None
            if node is None:
                break
        row.append(node)
    mark = '一致' if row[0] == row[1] else '**不同**'
    print(f'  {".".join(str(k) for k in path if k):<45} {mark}')
    for (name, _), v in zip(PAIRS, row):
        print(f'      {name[:6]}: {v}')

print()
print('=== dm_filter.dm_type ===')
for name, _ in PAIRS:
    v = data[name]['download_args']['live']['dm_filter']['dm_type']
    print(f'  {name}: {v}')

print()
print('=== upload_args 目标 ===')
for name, _ in PAIRS:
    print(f'  {name}: {sorted(data[name]["upload_args"].keys())}')
