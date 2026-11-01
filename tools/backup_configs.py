"""配置快照 / 校验 / 恢复工具。

⚠️ 为什么需要这个：
    configs/ 是**唯一的真实配置源**，里面装着：
      · global.yml          —— 全局配置，含我们的魔改（rclone 上传、跳过规则、
                               清理规则、渲染参数等 8 个关键自定义段）
      · DMR-*.yml × 33      —— 33 个主播的任务配置
      · temp/ (99 项)       —— 配置模板
    一旦被误删或覆盖，主播配置、上传规则、清理规则全部丢失，无法重建。

    2026-10-15 合并上游时就差点踩坑：dev 的 global.yml 丢了
    upload_args_task_default（上传规则本体）和 clean_args，而且 realtime
    被改成 True（会改变上传行为）。当时靠"部署只同步代码、configs 完全不动"
    才避开，但**并没有任何机制保证以后不踩**。

功能：
    snapshot   生成带时间戳的快照（默认保留最近 N 份）
    verify     校验当前 configs 与最近快照的差异（发现丢失/改动）
    restore    从指定快照恢复

用法：
    python tools\\backup_configs.py snapshot            # 打快照
    python tools\\backup_configs.py snapshot --keep 20  # 保留 20 份
    python tools\\backup_configs.py verify              # 校验
    python tools\\backup_configs.py list                # 列出快照
    python tools\\backup_configs.py restore <快照名>     # 恢复

快照位置：F:\\_DMR配置快照\\<时间戳>\\
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）


ROOT = _PROJECT_ROOT
CONFIGS = os.path.join(ROOT, 'configs')
SNAP_ROOT = r'F:\_DMR配置快照'
MANIFEST = 'manifest.json'

# 这些是关键配置，缺失就报警
CRITICAL_FILES = ['global.yml']
# global.yml 里必须存在的关键段（我们的魔改）
CRITICAL_SECTIONS = [
    ('upload_args', '上传配置（含 rclone 网盘）'),
    ('upload_args_task_default', '上传规则本体（dm_video → rclone）'),
    ('clean_args', '清理配置'),
    ('render_args', '渲染配置'),
    ('download_args', '下载配置'),
    ('skip_upload_rule', '跳过上传规则（魔改）'),
]


def md5(path, blocksize=1 << 20):
    h = hashlib.md5()
    try:
        with open(path, 'rb') as f:
            while True:
                b = f.read(blocksize)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()
    except Exception:
        return None


def walk_configs():
    """列出 configs 下所有文件（相对路径 -> 绝对路径）。"""
    out = {}
    for root, dirs, files in os.walk(CONFIGS):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for f in files:
            # ⚠️ 2026-10-19：跳过备份/\u4e34时文件。
            #    原来把 .bak-* 也收进快照，于是清理掉一个过期 .bak 后，
            #    启动自检就报「相比快照丢失 1 个配置」—— 震惊但无害。
            if '.bak' in f or f.startswith('~') or f.endswith('.tmp'):
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, CONFIGS)
            out[rel] = p
    return out


def cmd_snapshot(args):
    print('=' * 78)
    print('配置快照')
    print('=' * 78)
    files = walk_configs()
    if not files:
        print(f'  ❌ 找不到配置: {CONFIGS}')
        return 1

    stamp = time.strftime('%Y%m%d-%H%M%S')
    dest = os.path.join(SNAP_ROOT, stamp)
    os.makedirs(dest, exist_ok=True)

    manifest = {'created': time.strftime('%Y-%m-%d %H:%M:%S'),
                'source': CONFIGS, 'files': {}}
    n = 0
    for rel, p in sorted(files.items()):
        d = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(p, d)
        manifest['files'][rel] = {
            'size': os.path.getsize(p),
            'md5': md5(p),
        }
        n += 1

    with open(os.path.join(dest, MANIFEST), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f'  ✅ 已备份 {n} 个文件 -> {dest}')

    # 关键段检查
    print()
    print('  关键配置段检查:')
    g = os.path.join(CONFIGS, 'global.yml')
    txt = open(g, encoding='utf-8').read() if os.path.exists(g) else ''
    bad = []
    for key, desc in CRITICAL_SECTIONS:
        ok = key in txt
        if not ok:
            bad.append((key, desc))
        print(f'    {"✅" if ok else "❌"} {key:28} {desc}')
    for f in CRITICAL_FILES:
        ok = os.path.exists(os.path.join(CONFIGS, f))
        print(f'    {"✅" if ok else "❌"} {f}（必需文件）')
        if not ok:
            bad.append((f, '必需文件'))
    if bad:
        print(f'\n  ⚠️ 快照里有 {len(bad)} 项缺失 —— 快照本身可能不完整！')

    # 清理旧快照
    snaps = sorted([d for d in os.listdir(SNAP_ROOT)
                    if os.path.isdir(os.path.join(SNAP_ROOT, d))])
    if len(snaps) > args.keep:
        for old in snaps[:-args.keep]:
            shutil.rmtree(os.path.join(SNAP_ROOT, old), ignore_errors=True)
            print(f'  已清理旧快照: {old}')
    print(f'\n  当前保留 {min(len(snaps), args.keep)} 份快照')
    return 0


def cmd_verify(args):
    print('=' * 78)
    print('配置校验（对比最近快照）')
    print('=' * 78)
    if not os.path.isdir(SNAP_ROOT):
        print('  ⚠️ 没有快照。先运行: snapshot')
        return 1
    snaps = sorted([d for d in os.listdir(SNAP_ROOT)
                    if os.path.isdir(os.path.join(SNAP_ROOT, d))])
    if not snaps:
        print('  ⚠️ 没有快照。先运行: snapshot')
        return 1
    latest = snaps[-1]
    mpath = os.path.join(SNAP_ROOT, latest, MANIFEST)
    if not os.path.exists(mpath):
        print(f'  ⚠️ 快照 {latest} 缺 manifest.json')
        return 1
    manifest = json.load(open(mpath, encoding='utf-8'))

    cur = walk_configs()
    missing, changed, added = [], [], []
    for rel, info in manifest['files'].items():
        if rel not in cur:
            missing.append(rel)
        elif md5(cur[rel]) != info['md5']:
            changed.append(rel)
    for rel in cur:
        if rel not in manifest['files']:
            added.append(rel)

    print(f'  对比快照: {latest}（{manifest["created"]}）')
    print(f'  快照文件数: {len(manifest["files"])}   当前文件数: {len(cur)}')
    print()
    if missing:
        print(f'  🔴 丢失 {len(missing)} 个文件（严重！）:')
        for x in sorted(missing):
            print(f'      {x}')
    if changed:
        print(f'  🟠 被修改 {len(changed)} 个文件:')
        for x in sorted(changed):
            print(f'      {x}')
    if added:
        print(f'  🟢 新增 {len(added)} 个文件（正常）:')
        for x in sorted(added)[:10]:
            print(f'      {x}')
        if len(added) > 10:
            print(f'      ... 还有 {len(added)-10} 个')

    # 关键段检查
    print()
    g = os.path.join(CONFIGS, 'global.yml')
    txt = open(g, encoding='utf-8').read() if os.path.exists(g) else ''
    bad = [k for k, _ in CRITICAL_SECTIONS if k not in txt]
    if bad:
        print(f'  🔴 global.yml 缺失关键段: {bad}')
    else:
        print('  ✅ global.yml 全部关键段都在')

    if missing or bad:
        print(f'\n  ⚠️ 发现问题！恢复命令:')
        print(f'      python tools\\backup_configs.py restore {latest}')
        return 1
    print('\n  ✅ 配置完好')
    return 0


def cmd_list(args):
    if not os.path.isdir(SNAP_ROOT):
        print('  （没有快照）')
        return 0
    snaps = sorted(os.listdir(SNAP_ROOT))
    print(f'  快照目录: {SNAP_ROOT}')
    for s in snaps:
        p = os.path.join(SNAP_ROOT, s)
        if not os.path.isdir(p):
            continue
        n = sum(len(fs) for _, _, fs in os.walk(p))
        sz = sum(os.path.getsize(os.path.join(r, f))
                 for r, _, fs in os.walk(p) for f in fs)
        print(f'    {s}  {n} 文件 / {sz/1024:.0f} KB')
    return 0


def cmd_restore(args):
    src = os.path.join(SNAP_ROOT, args.name)
    if not os.path.isdir(src):
        print(f'  ❌ 快照不存在: {src}')
        return 1
    print('=' * 78)
    print(f'从快照恢复: {args.name}')
    print('=' * 78)
    print(f'  来源: {src}')
    print(f'  目标: {CONFIGS}')

    # 恢复前先给当前状态打快照
    print('\n  先备份当前状态（防止恢复错版本）...')
    cmd_snapshot(argparse.Namespace(keep=30))

    n = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for f in files:
            if f == MANIFEST:
                continue
            sp = os.path.join(root, f)
            rel = os.path.relpath(sp, src)
            dp = os.path.join(CONFIGS, rel)
            os.makedirs(os.path.dirname(dp), exist_ok=True)
            shutil.copy2(sp, dp)
            n += 1
    print(f'\n  ✅ 已恢复 {n} 个文件')
    return 0


def main():
    ap = argparse.ArgumentParser(description='配置快照 / 校验 / 恢复')
    sub = ap.add_subparsers(dest='cmd')

    p1 = sub.add_parser('snapshot', help='生成快照')
    p1.add_argument('--keep', type=int, default=15, help='保留份数（默认 15）')
    p1.set_defaults(func=cmd_snapshot)

    p2 = sub.add_parser('verify', help='校验配置与最近快照')
    p2.set_defaults(func=cmd_verify)

    p3 = sub.add_parser('list', help='列出快照')
    p3.set_defaults(func=cmd_list)

    p4 = sub.add_parser('restore', help='从快照恢复')
    p4.add_argument('name', help='快照名（见 list）')
    p4.set_defaults(func=cmd_restore)

    opt = ap.parse_args()
    if not opt.cmd:
        ap.print_help()
        return 0
    return opt.func(opt)


if __name__ == '__main__':
    sys.exit(main())
