"""全面检查：所有我改过的模块里，用到的名字是否都有导入。

这个 bug（Cleaner 用了 basename 但没导入）导致了 6 小时的清理静默失败，
所以值得做一个**自动化检查**，以后不再犯。
"""
import ast
import os
import sys

ROOT = r'F:\DanmakuRepo'

# 我这些天改过的文件
FILES = [
    'main.py',
    'DMR/Cleaner/__init__.py',
    'DMR/Render/__init__.py',
    'DMR/Render/dmrender.py',
    'DMR/Uploader/__init__.py',
    'DMR/Uploader/subprocess_uploader.py',
    'DMR/Task/liveevents.py',
    'DMR/Downloader/stream_downloader.py',
    'DMR/notify.py',
    'tools/gen_restart_notify.py',
    'tools/audit_cloud.py',
    'tools/cd2_watchdog.py',
    'tools/cd2_queue_health.py',
]

# 常见的内置/标准库名字，出现这些不算问题
BUILTINS = set(dir(__builtins__)) | {
    'self', 'cls', 'args', 'kwargs', 'True', 'False', 'None',
}

print('=' * 78)
print('静态检查：用到的名字是否有导入（AST 分析）')
print('=' * 78)

problems = []
for rel in FILES:
    p = os.path.join(ROOT, rel.replace('/', os.sep))
    if not os.path.exists(p):
        print(f'  ⏭ {rel}（不存在）')
        continue
    try:
        src = open(p, encoding='utf-8').read()
        tree = ast.parse(src)
    except SyntaxError as e:
        problems.append((rel, f'语法错误: {e}'))
        print(f'  ❌ {rel}  语法错误: {e}')
        continue

    # 收集：导入的名字
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported.add((a.asname or a.name).split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == '*':
                    imported.add('*')
                else:
                    imported.add(a.asname or a.name)

    # 收集：定义的名字（函数/类/赋值）
    defined = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, (ast.comprehension,)):
            pass
        elif isinstance(node, ast.alias):
            defined.add(node.asname or node.name.split('.')[0])

    # 收集：函数调用 / 属性访问的根名字
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)

    has_star = '*' in imported
    # 模块级的全局名字（含 import 进来的）
    known = imported | defined | BUILTINS
    if has_star:
        # 有 import * 时无法静态判定，只能保守跳过
        print(f'  ⚠ {rel}  有 import *，跳过静态检查（运行时才知道）')
        continue

    unknown = sorted(n for n in used
                     if n not in known and not n.startswith('_'))
    if unknown:
        problems.append((rel, f'可能未定义: {unknown}'))
        print(f'  ❌ {rel}')
        for n in unknown:
            print(f'       可能未定义: {n}')
    else:
        print(f'  ✅ {rel}')

print()
print('=' * 78)
print('结论')
print('=' * 78)
if problems:
    print(f'  发现 {len(problems)} 个文件有问题')
else:
    print('  ✅ 所有文件都没有未定义名字的问题')

print()
print('  ⚠️ 注意：有 `import *` 的文件无法静态检查（Cleaner 正好是这种），')
print('     所以额外做一次**运行时导入测试**：')
print()
# 运行时导入测试（真正能抓到 NameError 的方式是调用，但导入能抓到模块级问题）
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import importlib
for mod in ('DMR.Cleaner', 'DMR.Render', 'DMR.Uploader',
            'DMR.Task.liveevents', 'DMR.Downloader.stream_downloader',
            'DMR.notify'):
    try:
        m = importlib.import_module(mod)
        # 检查模块里有没有用到 basename 且它可用
        src = open(os.path.join(ROOT, mod.replace('.', os.sep) + '.py'),
                   encoding='utf-8').read() if os.path.exists(
            os.path.join(ROOT, mod.replace('.', os.sep) + '.py')) else ''
        has_bn = 'basename(' in src
        bn_ok = hasattr(m, 'basename')
        flag = '✅' if (not has_bn or bn_ok) else '❌ basename 用了但没导入！'
        print(f'  {flag} {mod}' + (f'  (用到 basename，可用={bn_ok})' if has_bn else ''))
    except Exception as e:
        print(f'  ❌ {mod}: {type(e).__name__}: {e}')
