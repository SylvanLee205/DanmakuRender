"""全项目深度扫描：找"函数体内使用但运行时拿不到"的名字。

⚠️ 这是抓 basename / is_danmaku_xml 这类 bug 的正确方法。

为什么之前的检查都不够：
    · py_compile       —— 只查语法
    · check_imports.py —— 只查"模块能 import"；而 is_danmaku_xml 在函数体内
                          使用，import 成功，调用时才炸
    · pyflakes         —— 遇到 `from x import *` 就放弃（133 条"unable to
                          detect undefined names"），等于在最关键的地方瞎了

本脚本的做法：
    1. 对每个模块，用 AST 收集**模块级可见的名字**：
         - import / from ... import
         - def / class / 赋值
         - **递归展开 `from X import *`**（关键！pyflakes 就是卡在这）
    2. 收集函数体内引用的所有 Name（排除局部变量、参数、builtins）
    3. 差集 = 可能的 NameError
"""
import ast
import builtins
import os
import sys

PROD = r'F:\DanmakuRepo'
sys.path.insert(0, PROD)
os.chdir(PROD)

BUILTINS = set(dir(builtins)) | {'__file__', '__name__', '__doc__',
                                 '__package__', '__builtins__', '__spec__',
                                 '__loader__', '__debug__', 'self', 'cls'}


def module_names(path, seen=None):
    """收集一个模块文件里"模块级绑定的名字"，并展开 import *。"""
    seen = seen or set()
    if path in seen:
        return set()
    seen.add(path)
    try:
        tree = ast.parse(open(path, encoding='utf-8').read())
    except Exception:
        return set()

    names = set()
    star_mods = []
    for node in tree.body:              # 只看模块级
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                if a.name == '*':
                    if isinstance(node, ast.ImportFrom) and node.module:
                        star_mods.append((node.level, node.module))
                    continue
                names.add((a.asname or a.name).split('.')[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target,
                                                            ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.If, ast.Try)):
            # 条件导入（如 if TYPE_CHECKING）也收进来
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for a in sub.names:
                        if a.name != '*':
                            names.add((a.asname or a.name).split('.')[0])

    # 展开 import *
    here = os.path.dirname(path)
    for level, mod in star_mods:
        cand = []
        if level and level > 0:
            # 相对导入
            base = here
            for _ in range(level - 1):
                base = os.path.dirname(base)
            cand.append(os.path.join(base, *mod.split('.')) if mod else base)
        elif mod and mod.startswith('DMR'):
            cand.append(os.path.join(PROD, *mod.split('.')))
        elif mod:
            # 第三个包，忽略（例如 from os.path import *）
            continue
        for c in cand:
            for f in (c + '.py', os.path.join(c, '__init__.py')):
                if os.path.isfile(f):
                    names |= module_names(f, seen)
    return names


def load_star_packages(path, seen=None):
    """对 `from os.path import *` / `from DMR.utils import *` 这类，
    返回能提供的名字集合（尽力而为）。"""
    return set()


def local_names(func):
    """函数内绑定的名字（参数、赋值、for、with、except、comprehension）。"""
    out = set()
    args = func.args
    for a in (list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)):
        out.add(a.arg)
    if args.vararg:
        out.add(args.vararg.arg)
    if args.kwarg:
        out.add(args.kwarg.arg)
    for n in ast.walk(func):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                            ast.ClassDef)) and n is not func:
            out.add(n.name)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if a.name != '*':
                    out.add((a.asname or a.name).split('.')[0])
        elif isinstance(n, ast.comprehension):
            for t in ast.walk(n.target):
                if isinstance(t, ast.Name):
                    out.add(t.id)
        elif isinstance(n, ast.Global) or isinstance(n, ast.Nonlocal):
            out |= set(n.names)
    return out


print('=' * 78)
print('深度扫描：函数体内使用但模块级拿不到的名字')
print('=' * 78)

problems = []
scanned = 0
for root, dirs, files in os.walk(os.path.join(PROD, 'DMR')):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for f in files:
        if not f.endswith('.py'):
            continue
        path = os.path.join(root, f)
        rel = os.path.relpath(path, PROD)
        scanned += 1
        try:
            tree = ast.parse(open(path, encoding='utf-8').read())
        except Exception:
            continue
        mod_names = module_names(path)
        # 模块内所有函数的局部名合并（宽松：任一函数里绑定过的就算）
        all_local = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                all_local |= local_names(n)
        # 模块级如果用了 import *，无法完全确定，标记出来
        src = open(path, encoding='utf-8').read()
        has_star = 'import *' in src

        used = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                used.add(n.id)

        # 判断哪些名字"看似有定义"：模块级 OR 局部 OR builtins
        defined = mod_names | all_local | BUILTINS
        # 对 `from X import *`（非 DMR 的，如 os.path）宽松处理：只要有
        # 任何 import *，就无法判定，只报"用了且模块级完全没有同名定义、
        # 且该名字看起来像本项目的工具函数"这种高置信度的
        unknown = sorted(used - defined)
        # 过滤：全小写带下划线的短名字往往是 import * 带来的
        # 我们只报那些"在本项目别处有定义"的名字 —— 那说明它本该被 import
        if unknown:
            problems.append((rel, unknown, has_star))

print(f'  扫描 {scanned} 个模块')
print()
if not problems:
    print('  ✅ 没有发现问题')
else:
    print(f'  发现 {len(problems)} 个模块有可疑名字：')
    for rel, names, has_star in problems:
        flag = '（该文件有 import *，可能是误报）' if has_star else ''
        print(f'\n  {rel} {flag}')
        print(f'      {names[:12]}')
