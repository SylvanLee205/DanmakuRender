"""修复 .temp/failed_renders.json 中保存的渲染参数。

背景：
    ffmpeg 的 `-global_quality` 不带流说明符时会同时作用于音频编码器，
    于是 libopus 收到「质量模式」而它只支持「码率模式」，报错：
        Quality-based encoding not supported, please specify a bitrate and VBR setting.
        Error while opening encoder - maybe incorrect parameters such as bit_rate, rate, width or height.
    渲染必然失败，而任务 yml 里 auto_clean 会把源视频删掉，导致录播永久丢失。

    失败任务的参数是**创建时快照**保存在 failed_renders.json 里的，
    所以即使已经把 global.yml 改成 `-global_quality:v`，网页上点“重试”仍会用旧参数再次失败。
    这个脚本把已保存的 `-global_quality` 补上 `:v`。

用法：
    python tools/fix_failed_renders_args.py --dry-run   # 只看会改什么
    python tools/fix_failed_renders_args.py             # 实际修改（自动备份 .bak）
"""
import argparse
import json
import shutil
import sys
from os.path import exists


def fix_args(args: dict) -> list:
    """返回被修改的字段说明列表。"""
    changed = []

    def walk_container(container, key, path):
        value = container.get(key)
        if not isinstance(value, list):
            return
        new_value = []
        for item in value:
            if isinstance(item, str) and item in ('-global_quality', '-global_quality:a'):
                new_value.append('-global_quality:v')
                changed.append(f'{path}.{key}: {item} -> -global_quality:v')
            else:
                new_value.append(item)
        container[key] = new_value

    if isinstance(args, dict):
        walk_container(args, 'vencoder_args', 'args')
        advanced = args.get('advanced_render_args')
        if isinstance(advanced, dict):
            walk_container(advanced, 'vencoder_args', 'args.advanced_render_args')

    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', default='.temp/failed_renders.json')
    parser.add_argument('--dry-run', action='store_true')
    opt = parser.parse_args()

    if not exists(opt.file):
        print(f'找不到 {opt.file}，无需修复。')
        return 1

    with open(opt.file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    total = 0
    for uuid, task in data.items():
        changed = fix_args(task.get('args') or {})
        if changed:
            total += 1
            name = (task.get('video') or {}).get('taskname') if isinstance(task.get('video'), dict) else None
            print(f'[{uuid[:8]}] {name or task.get("source")}')
            for c in changed:
                print(f'    {c}')

    if not total:
        print(f'{len(data)} 个失败任务都不需要修复（已经是 -global_quality:v）。')
        return 0

    print(f'\n共 {total} 个任务需要修复。')
    if opt.dry_run:
        print('（dry-run，未写入文件）')
        return 0

    backup = opt.file + '.bak'
    shutil.copy2(opt.file, backup)
    print(f'已备份到 {backup}')

    with open(opt.file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f'已写回 {opt.file}。重启程序后在网页上重试这些任务即可。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
