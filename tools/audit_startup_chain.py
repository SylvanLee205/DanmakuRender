"""复查：启动链路 + 配置键核对。

启动链路（用户明确要求过"确保所有的启动脚本都指向他包括开机自启动的脚本"）：
    1. F:\\DanmakuRepo\\Start_Render.bat
    2. 启动文件夹的快捷方式
    3. 计划任务
    4. bat 内容是否指向正确目录 + 编码是否安全
"""
import os
import re
import subprocess
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）

PROD = _PROJECT_ROOT


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. Start_Render.bat')
print('=' * 78)
bat = os.path.join(PROD, 'Start_Render.bat')
if not os.path.exists(bat):
    print('  ❌ 不存在')
else:
    raw = open(bat, 'rb').read()
    non_ascii = [b for b in raw if b > 127]
    print(f'  大小: {len(raw)} 字节')
    print(f'  非 ASCII 字节: {len(non_ascii)} 个  '
          f'{"✅ 纯 ASCII（安全）" if not non_ascii else "⚠️ 含非 ASCII（可能触发 cmd 编码问题）"}')
    _crlf = b'\r\n' in raw
    print(f'  CRLF 行尾: {"✅" if _crlf else "⚠️"}')
    print('  内容:')
    for i, l in enumerate(raw.decode('ascii', errors='replace').split('\n'), 1):
        if l.strip():
            print(f'    {i:2}| {l.rstrip()[:95]}')
    # 关键检查
    txt = raw.decode('ascii', errors='replace')
    checks = [
        ('指向 DanmakuRepo', 'DanmakuRepo' in txt),
        ('用 .venv 的 python', '.venv' in txt),
        ('调用 main.py', 'main.py' in txt),
        ('有 --quiet', '--quiet' in txt),
        ('有循环守护(:loop / goto)', ('goto' in txt.lower() or ':loop' in txt.lower())),
    ]
    print('  关键检查:')
    for name, ok in checks:
        print(f'    {"✅" if ok else "❌"} {name}')

print()
print('=' * 78)
print('2. 启动文件夹快捷方式')
print('=' * 78)
startup = os.path.join(os.environ['APPDATA'],
                       r'Microsoft\Windows\Start Menu\Programs\Startup')
out = ps(f'Get-ChildItem "{startup}" | ForEach-Object {{ $_.Name }}')
for l in (out or '').split('\n'):
    if l.strip():
        print(f'  {l.strip()}')
lnk = os.path.join(startup, 'Start_Render.bat - 快捷方式.lnk')
if os.path.exists(lnk):
    t = ps(f'(New-Object -ComObject WScript.Shell).CreateShortcut("{lnk}").TargetPath')
    a = ps(f'(New-Object -ComObject WScript.Shell).CreateShortcut("{lnk}").Arguments')
    w = ps(f'(New-Object -ComObject WScript.Shell).CreateShortcut("{lnk}").WorkingDirectory')
    print(f'    目标: {t}')
    print(f'    参数: {a}')
    print(f'    工作目录: {w}')
    print(f'    {"✅ 指向正确" if "DanmakuRepo" in t else "❌ 指向错误！"}')

print()
print('=' * 78)
print('3. 计划任务')
print('=' * 78)
out = ps("Get-ScheduledTask | Where-Object { $_.TaskName -like '*Danmaku*' -or "
         "$_.TaskName -like '*DMR*' -or $_.TaskName -like '*Cloud*' } | "
         "ForEach-Object { $_.TaskName + ' | ' + $_.State }")
for l in (out or '').split('\n'):
    if l.strip():
        print(f'  {l.strip()}')
# 检查关键任务的执行内容
for tn in ('DMR_配置快照', 'DMR_云端上传审计'):
    o = ps(f"(Get-ScheduledTask -TaskName '{tn}' -ErrorAction SilentlyContinue)"
           f".Actions | ForEach-Object {{ $_.Execute + ' ' + $_.Arguments }}")
    if o.strip():
        print(f'  [{tn}]')
        print(f'      {o.strip()[:150]}')

print()
print('=' * 78)
print('4. 配置键核对：代码读取 vs 实际配置')
print('=' * 78)
import yaml

gc = yaml.safe_load(open(os.path.join(PROD, 'configs', 'global.yml'),
                         encoding='utf-8')) or {}
gcd = yaml.safe_load(open(os.path.join(PROD, 'DMR', 'Config', 'default.yml'),
                          encoding='utf-8')) or {}

# 只找**全局**配置的读取：在 DMR/__init__.py engine.py 等引擎级文件里
GLOBAL_FILES = ['DMR/__init__.py', 'DMR/engine.py', 'DMR/Config/__init__.py']
keys = set()
for rel in GLOBAL_FILES:
    p = os.path.join(PROD, rel)
    if not os.path.exists(p):
        continue
    t = open(p, encoding='utf-8', errors='replace').read()
    for m in re.finditer(r"get_config\(['\"](\w+)['\"]", t):
        keys.add(m.group(1))
    for m in re.finditer(r"global_config\[['\"](\w+)['\"]\]", t):
        keys.add(m.group(1))
    for m in re.finditer(r"global_config\.get\(['\"](\w+)['\"]", t):
        keys.add(m.group(1))
print(f'  引擎级读取的全局键 ({len(keys)}): {sorted(keys)}')
print()
for k in sorted(keys):
    in_cfg = k in gc
    in_def = k in gcd
    src = 'global.yml' if in_cfg else ('default.yml（自动补齐）' if in_def else '❌ 都没有')
    print(f'    {"✅" if (in_cfg or in_def) else "❌"} {k:26} 来源: {src}')

print()
print('=' * 78)
print('5. 任务配置完整性')
print('=' * 78)
cfgs = [f for f in os.listdir(os.path.join(PROD, 'configs'))
        if f.endswith('.yml') and not f.startswith('global')]
print(f'  任务配置 {len(cfgs)} 个')
bad = []
for f in cfgs:
    p = os.path.join(PROD, 'configs', f)
    try:
        d = yaml.safe_load(open(p, encoding='utf-8'))
        if not d:
            bad.append((f, '空文件'))
            continue
        url = (d.get('url') or [])
        if isinstance(url, str):
            url = [url]
        if not any('douyin' in str(u) or 'live.' in str(u) for u in url):
            bad.append((f, f'无有效 url: {url}'))
    except Exception as e:
        bad.append((f, f'YAML 错误: {str(e)[:50]}'))
if bad:
    print(f'  ⚠️ 有问题的任务配置 {len(bad)} 个:')
    for f, w in bad:
        print(f'      {f}: {w}')
else:
    print('  ✅ 全部任务配置都能正常解析且有 url')
