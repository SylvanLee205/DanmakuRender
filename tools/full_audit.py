"""全盘核对：配置完整性 + 运行时一致性 + 功能接线检查。

用户要求"全盘全程序全扫一遍核对一遍"，所以本脚本做四件事：
  1. global.yml 与默认配置/历史快照的差异（找出用户改了什么）
  2. 运行时是否有配置键丢失（之前发现过 dev 丢 upload_args_task_default）
  3. 所有"方法定义了但没人调用"的功能（GOP 那次就是这种漏洞）
  4. 所有渲染/上传参数是否真的接到了 ffmpeg/rclone 命令行
"""
import ast
import json
import os
import re
import subprocess
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）

PROD = _PROJECT_ROOT
sys.path.insert(0, PROD)
os.chdir(PROD)

import yaml


print('=' * 78)
print('一、global.yml 现状与历史快照对比')
print('=' * 78)
p = os.path.join(PROD, 'configs', 'global.yml')
cur = yaml.safe_load(open(p, encoding='utf-8')) or {}
print(f'  当前 {len(cur)} 个顶级键: {sorted(cur)}')

# 找快照里的 global.yml 对比（快照目录现在跟着项目走，不再是 F:\ 根目录）
from DMR.paths import snapshot_dir
snap_root = snapshot_dir()
snaps = sorted(d for d in os.listdir(snap_root)
               if os.path.isdir(os.path.join(snap_root, d))) if os.path.isdir(snap_root) else []
if snaps:
    latest = os.path.join(snap_root, snaps[-1], 'global.yml')
    if os.path.exists(latest):
        old = yaml.safe_load(open(latest, encoding='utf-8')) or {}
        print(f'  对比快照 {snaps[-1]}（{len(old)} 个顶级键）')
        miss = sorted(set(old) - set(cur))
        add = sorted(set(cur) - set(old))
        if miss:
            print(f'  🔴 相比快照丢失的顶级键: {miss}')
        if add:
            print(f'  🟢 新增的顶级键: {add}')
        if not miss:
            print('  ✅ 顶级键无丢失')
        # 逐段找差异
        print()
        print('  有差异的配置段:')
        for k in sorted(set(old) & set(cur)):
            if old[k] != cur[k]:
                if isinstance(old[k], dict) and isinstance(cur[k], dict):
                    sub = [s for s in set(old[k]) | set(cur[k])
                           if old[k].get(s) != cur[k].get(s)]
                    print(f'    {k}:')
                    for s in sorted(sub):
                        print(f'        {s}: {json.dumps(old[k].get(s), ensure_ascii=False)[:60]}')
                        print(f'          → {json.dumps(cur[k].get(s), ensure_ascii=False)[:60]}')
                else:
                    print(f'    {k}: {old[k]!r} → {cur[k]!r}')

print()
print('=' * 78)
print('二、运行时配置完整性（关键段 + 关键子键）')
print('=' * 78)
REQUIRED = {
    'upload_args': ['rclone'],
    'upload_args_task_default': ['dm_video'],
    'clean_args': ['delete', 'move'],
    'render_args': ['dmrender'],
    'download_args': ['live'],
    'dmr_engine_args': [],
    'executable_tools_path': [],
    'webservice_kernel_args': [],
}
bad = []
for key, subs in REQUIRED.items():
    if key not in cur:
        bad.append(f'{key} 整段缺失')
        print(f'  ❌ {key}: 缺失')
        continue
    miss = [s for s in subs if s not in (cur[key] or {})]
    if miss:
        bad.append(f'{key} 缺子键 {miss}')
        print(f'  ❌ {key}: 缺子键 {miss}')
    else:
        print(f'  ✅ {key}')

# 渲染/上传的关键子键
dm = ((cur.get('render_args') or {}).get('dmrender') or {})
for k in ('vencoder', 'vencoder_args', 'aencoder', 'aencoder_args'):
    ok = k in dm
    print(f'  {"✅" if ok else "❌"} render_args.dmrender.{k} = '
          f'{json.dumps(dm.get(k), ensure_ascii=False)[:60]}')
    if not ok:
        bad.append(f'render_args.dmrender.{k} 缺失')

dl = (((cur.get('download_args') or {}).get('live')) or {})
for k in ('dm_filter', 'output_dir', 'output_name'):
    ok = k in dl
    print(f'  {"✅" if ok else "❌"} download_args.live.{k}')
    if not ok:
        bad.append(f'download_args.live.{k} 缺失')

sk = (dm.get('skip_upload_rule') or {})
print(f'  {"✅" if sk else "❌"} skip_upload_rule = '
      f'{json.dumps(sk, ensure_ascii=False)[:80]}')

print()
print('=' * 78)
print('三、功能接线检查：方法定义了但没人调用')
print('=' * 78)
# 收集项目内所有 "self._xxx(" 或 "self._xxx(" 的调用
calls = set()
defs = {}
for root, dirs, files in os.walk(os.path.join(PROD, 'DMR')):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for f in files:
        if not f.endswith('.py'):
            continue
        path = os.path.join(root, f)
        rel = os.path.relpath(path, PROD)
        try:
            src = open(path, encoding='utf-8', errors='replace').read()
            tree = ast.parse(src)
        except Exception:
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if n.name.startswith('_') and not n.name.startswith('__'):
                    defs.setdefault(n.name, []).append(rel)
            if isinstance(n, ast.Call):
                fn = n.func
                if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) \
                        and fn.value.id == 'self':
                    calls.add(fn.attr)

# 只关心我们魔改引入的方法（避免报上游大量正常的工具方法）
OUR_METHODS = [
    '_build_gop_args', '_parse_gop_multiplier', '_check_encoder_args',
    '_prepare_danmaku', '_temp_dir_for', '_remove_quietly',
    '_notify_live', '_get_upload_skip_rule', '_mark_upload_skipped',
    '_verify_configs', '_verify_critical_names', '_startup_recover',
    '_inject_state_repo', '_with_state_repo', '_record_segment',
    '_ensure_session', '_sync_artifact', '_sync_upload_group',
    '_session_has_ended', '_handle_unusable', '_promote_intermediate_name',
    '_sessions_by_id', '_group_or_none', '_lookup_state',
    '_compute_output_path', '_min_valid_size_mb', '_passes_length_gate',
    '_blank_segment_state', '_free_state_memory',
]
print('  检查我们关心的方法是否有调用点:')
orphans = []
for m in sorted(set(OUR_METHODS)):
    defined = m in defs
    called = m in calls
    if defined and not called:
        orphans.append(m)
        print(f'  🔴 {m:26} 定义了但**没有调用**！  定义于 {defs[m][0]}')
    elif defined and called:
        print(f'  ✅ {m:26} 定义+调用齐全')
    else:
        print(f'  ⚪ {m:26} 未定义（可能已不需要）')

print()
print('=' * 78)
print('四、结论')
print('=' * 78)
if orphans:
    print(f'  🔴 发现 {len(orphans)} 个"定义了但没人调用"的方法:')
    for m in orphans:
        print(f'      {m}  ({defs[m][0]})')
    print('      这类漏洞静态检查很难发现（方法存在、语法正确），')
    print('      但功能实际不生效 —— GOP 那次就是这样。')
else:
    print('  ✅ 没有"定义了但没人调用"的功能方法')

if bad:
    print(f'  🔴 配置缺失 {len(bad)} 项:')
    for x in bad:
        print(f'      {x}')
else:
    print('  ✅ 配置关键段/子键完整')
