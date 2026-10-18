"""扫描 liveevents.py 里所有「定义了但从未被 self.xxx 引用」的方法。

补足 feature_audit.py D 段的白名单盲区（白名单只覆盖 21 个关键方法）。
"""
import ast
import os
import sys

TARGETS = [
    r'F:\DanmakuRender_AutoUp\DMR\Task\liveevents.py',
    r'F:\DanmakuRender_AutoUp\DMR\Task\replaytask.py',
    r'F:\DanmakuRender_AutoUp\DMR\Render\dmrender.py',
    r'F:\DanmakuRender_AutoUp\DMR\Cleaner\__init__.py',
    r'F:\DanmakuRender_AutoUp\DMR\Render\__init__.py',
    r'F:\DanmakuRender_AutoUp\DMR\Uploader\__init__.py',
]

#: 这些是 dunder / 框架回调 / 属性访问式引用，不算孤儿
IGNORE_PREFIX = ('__', '_eval_')
#: 框架/库会回调的名字（不需要显式 self. 调用）
FRAMEWORK_CALLBACKS = {
    'fileno', 'close', 'write', 'flush', 'emit', 'format', 'filter',
    'run', 'join', 'start', 'stop', 'submit', 'start_helper', 'start_once',
    'newtask', 'ready', 'exit', 'defaultEvent',
}


def scan(path):
    src = open(path, encoding='utf-8', errors='replace').read()
    tree = ast.parse(src)
    rel = os.path.basename(path)

    defined = []      # (name, lineno, class)
    self_refs = set()  # self.xxx 出现过的（不论调用还是属性访问）
    bare_calls = set()

    class V(ast.NodeVisitor):
        def __init__(self):
            self.cls = None

        def visit_ClassDef(self, n):
            old = self.cls
            self.cls = n.name
            self.generic_visit(n)
            self.cls = old

        def visit_FunctionDef(self, n):
            # ⚠️ 只记**类体直接层级**的方法。方法内部的嵌套闭包
            # (如 _notify_live 里的 _do，被 Thread(target=_do) 使用)
            # 不是方法，当成孤儿会误报。
            # 判据：父节点是 ClassDef 才算方法。
            self._def_parent = getattr(self, '_parents', [])
            if self.cls and getattr(self, '_depth_in_class', 0) == 0:
                defined.append((n.name, n.lineno, self.cls))
            self._depth_in_class = getattr(self, '_depth_in_class', 0) + 1
            self.generic_visit(n)
            self._depth_in_class -= 1

        def visit_Attribute(self, n):
            # self.xxx 无论调用还是当值传递都算"被引用"
            if isinstance(n.value, ast.Name) and n.value.id == 'self':
                self_refs.add(n.attr)
            self.generic_visit(n)

        def visit_Call(self, n):
            if isinstance(n.func, ast.Name):
                bare_calls.add(n.func.id)
            self.generic_visit(n)

    V().visit(tree)

    # 装饰器里出现的名字也算被引用
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for d in node.decorator_list:
                for sub in ast.walk(d):
                    if isinstance(sub, ast.Attribute):
                        self_refs.add(sub.attr)
                    elif isinstance(sub, ast.Name):
                        self_refs.add(sub.id)

    orphans = []
    for name, lineno, cls in defined:
        if name.startswith(IGNORE_PREFIX):
            continue
        if name in FRAMEWORK_CALLBACKS:
            continue
        if name in self_refs or name in bare_calls:
            continue
        orphans.append((rel, cls, name, lineno))
    return defined, orphans


print('=' * 78)
print('全量孤儿方法扫描（补 feature_audit 白名单的盲区）')
print('=' * 78)

total_def = 0
all_orphans = []
for p in TARGETS:
    if not os.path.exists(p):
        continue
    try:
        d, o = scan(p)
    except SyntaxError as e:
        print(f'  ⚠️ {os.path.basename(p)} 语法解析失败: {e}')
        continue
    total_def += len(d)
    all_orphans += o
    print(f'  {os.path.basename(p):28} 方法 {len(d):3} 个，孤儿 {len(o)} 个')

print()
print(f'  合计：方法 {total_def} 个，孤儿 {len(all_orphans)} 个')
print()
if all_orphans:
    print('  🔴 定义了但从未被引用的方法：')
    for rel, cls, name, lineno in all_orphans:
        print(f'    {rel}:{lineno:4}  {cls}.{name}')
else:
    print('  ✅ 没有孤儿方法')
