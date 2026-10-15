"""查清"直播已结束"为什么打两次（一次 INFO 一次 PROGRESS）。"""
import os
import re

for label, path in (('prod', r'F:\DanmakuRender_AutoUp\DMR\Task\liveevents.py'),
                    ('dev', r'F:\DanmakuRender_Mod\DMR\Task\liveevents.py')):
    src = open(path, encoding='utf-8').read()
    print('=' * 78)
    print(f'{label}: {path}')
    print('=' * 78)

    # 找所有打日志的地方
    print('\n  ── 所有 logger 调用（含行号）──')
    for i, l in enumerate(src.split('\n'), 1):
        if re.search(r'self\.logger\.(log|info|debug|warning|error)\(', l):
            print(f'    L{i}: {l.strip()[:110]}')

    # 找 "直播已结束" 相关
    print('\n  ── 含"直播已结束"或 liveend 的位置 ──')
    for i, l in enumerate(src.split('\n'), 1):
        if '直播已结束' in l or 'liveend' in l.lower():
            print(f'    L{i}: {l.strip()[:110]}')

    # event_dict 里 liveend 映射到哪个方法
    print('\n  ── event_dict 中 liveend / liveerror 的映射 ──')
    m = re.search(r'event_dict.*?\n\s*\}', src, re.S)
    if m:
        for l in m.group(0).split('\n'):
            if 'live' in l.lower() or 'livestart' in l.lower():
                print(f'    {l.strip()[:110]}')
    print()
