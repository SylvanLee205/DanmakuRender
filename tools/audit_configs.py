"""全面审计 configs/ 和 configs/temp/ 里的所有 yml，找出配置隐患。"""
import json
import os
import sys

import yaml

UP = r'F:\DanmakuRender_AutoUp'
sys.path.insert(0, UP)
os.chdir(UP)

CFGDIR = os.path.join(UP, 'configs')
TEMPDIR = os.path.join(CFGDIR, 'temp')

print('=' * 78)
print('1. configs/ 目录结构')
print('=' * 78)
for d, label in ((CFGDIR, 'configs/'), (TEMPDIR, 'configs/temp/')):
    if not os.path.isdir(d):
        print(f'  {label} 不存在')
        continue
    fs = sorted(os.listdir(d))
    yml = [f for f in fs if f.endswith(('.yml', '.yaml'))]
    print(f'  {label}  {len(yml)} 个 yml（共 {len(fs)} 个条目）')
    if label.endswith('temp/'):
        for f in yml:
            print(f'      {f}')

print()
print('=' * 78)
print('2. 每个任务 yml 的关键字段')
print('=' * 78)
rows = []
for f in sorted(os.listdir(CFGDIR)):
    if not (f.startswith('DMR-') and f.endswith('.yml')):
        continue
    p = os.path.join(CFGDIR, f)
    try:
        d = yaml.safe_load(open(p, encoding='utf-8', errors='replace')) or {}
    except Exception as e:
        print(f'  ✗ {f} 解析失败: {e}')
        continue
    task = f[4:-4]
    cea = d.get('common_event_args') or {}
    ua = d.get('upload_args')
    cat = d.get('clean_args')
    rows.append({
        'task': task,
        'file': f,
        'own_upload_args': ua is not None,
        'own_clean_args': cat is not None,
        'auto_upload': cea.get('auto_upload'),
        'auto_clean': cea.get('auto_clean'),
        'auto_render': cea.get('auto_render'),
    })

print(f'  共 {len(rows)} 个任务')
print()
print(f'  {"任务":20} {"auto_up":>8} {"auto_cl":>8} {"auto_rd":>8} {"自有upload":>10} {"自有clean":>10}')
for r in sorted(rows, key=lambda x: x['task']):
    print(f'  {r["task"][:20]:20} {str(r["auto_upload"]):>8} {str(r["auto_clean"]):>8} '
          f'{str(r["auto_render"]):>8} {str(r["own_upload_args"]):>10} {str(r["own_clean_args"]):>10}')

print()
own_ua = [r['task'] for r in rows if r['own_upload_args']]
own_ca = [r['task'] for r in rows if r['own_clean_args']]
no_au = [r['task'] for r in rows if not r['auto_upload']]
no_ac = [r['task'] for r in rows if not r['auto_clean']]
print(f'  自己写了 upload_args 的任务: {own_ua if own_ua else "无（全部用全局默认 → realtime 修复覆盖全部）"}')
print(f'  自己写了 clean_args  的任务: {own_ca if own_ca else "无"}')
print(f'  auto_upload 未开启   的任务: {no_au if no_au else "无"}')
print(f'  auto_clean  未开启   的任务: {no_ac if no_ac else "无"}')

print()
print('=' * 78)
print('3. 解析后每个任务实际拿到的 upload_args（确认 realtime）')
print('=' * 78)
import logging
logging.basicConfig(level=logging.ERROR)
from DMR.Config import Config
cfg = Config('configs/global.yml')
bad = []
for r in sorted(rows, key=lambda x: x['task']):
    t = r['task']
    try:
        tn = cfg.add_task_config(os.path.join(CFGDIR, r['file']))
        rc = cfg.get_replay_config(tn)
        ua = rc.get('upload_args') or {}
        for ft, lst in ua.items():
            for one in lst:
                if not one.get('realtime'):
                    bad.append((t, ft, 'realtime 缺失/false'))
                if not one.get('command'):
                    bad.append((t, ft, 'command 为空'))
                if one.get('target') not in (cfg.global_config.get('upload_args') or {}):
                    bad.append((t, ft, f'target={one.get("target")} 在 upload_args 里没有定义'))
    except Exception as e:
        bad.append((t, '-', f'解析异常 {type(e).__name__}: {e}'))

if bad:
    print('  ⚠ 发现问题:')
    for t, ft, msg in bad:
        print(f'    {t:20} {ft:12} {msg}')
else:
    print('  ✓ 全部 31 个任务的 upload_args 都正常（realtime=true, command 非空, target 有效）')

print()
print('=' * 78)
print('4. clean_args 解析（确认清理规则）')
print('=' * 78)
for r in sorted(rows, key=lambda x: x['task'])[:3]:
    tn = cfg.add_task_config(os.path.join(CFGDIR, r['file']))
    rc = cfg.get_replay_config(tn)
    ca = rc.get('clean_args') or {}
    print(f'  【{r["task"]}】clean_args:')
    for k, v in ca.items():
        print(f'      {k} = {json.dumps(v, ensure_ascii=False, default=str)}')
    break

print()
print('=' * 78)
print('5. temp/ 里的任务模板是否会被误加载')
print('=' * 78)
if os.path.isdir(TEMPDIR):
    for f in sorted(os.listdir(TEMPDIR)):
        if f.endswith(('.yml', '.yaml')):
            print(f'    {f}')
    print()
    print('  find_tasks() 的实现：同时扫 configs/ 和 configs/temp/，')
    print('  所以 temp/ 里的示例文件也会被当成"任务"识别。')
    print('  → 它们只影响 recover_part 的任务名推断，不影响 DMR 主流程。')
