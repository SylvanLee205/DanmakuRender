"""自检：静态导入检查 + 运行时关键名字检查 + 真实清理测试。

为什么需要这个：
    2026-10-07 我在 DMR/Cleaner/__init__.py 里用了 basename() 但忘了导入，
    导致**所有清理静默失败 6 小时**（16:52~22:16，7 个源视频没删）。
    py_compile 查不出来（语法没问题），只有真正执行到那一行才报 NameError。

    所以做三层检查：
      1. 静态（AST）：找"用到的名字没导入"（有 import * 的文件会跳过）
      2. 运行时：import 每个模块，确认关键名字真的可用
      3. 真实清理：造临时文件走一遍 delete 流程，确认文件真被删

用法：
    python tools\\check_imports.py
"""
import ast
import logging
import os
import sys
import tempfile

ROOT = r'F:\DanmakuRender_AutoUp'
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# 关键名字检查表：{模块: [必须可用的名字]}
# 只列我改动中实际用到、且容易忘记导入的函数
REQUIRED = {
    'DMR.Cleaner': ['basename', 'abspath', 'exists', 'dirname', 'os', 'logging'],
    'DMR.Render': ['basename', 'exists', 'join', 'os', 'logging'],
    # 注意：Uploader 用的是 from os.path import ...，所以模块里没有 os 这个名字
    'DMR.Uploader': ['basename', 'exists', 'join', 'time', 'json'],
    'DMR.Downloader.stream_downloader': ['basename', 'join', 'exists',
                                         'splitext', 'os', 'time'],
    'DMR.Task.liveevents': ['PROGRESS', 'logging', 'os', 'time'],
    'DMR.notify': ['send', '_join', '_NL', 'disk_free_gb'],
}

FILES_FOR_AST = [
    'main.py', 'DMR/Cleaner/__init__.py', 'DMR/Render/__init__.py',
    'DMR/Render/dmrender.py', 'DMR/Uploader/__init__.py',
    'DMR/Uploader/subprocess_uploader.py', 'DMR/Task/liveevents.py',
    'DMR/Downloader/stream_downloader.py', 'DMR/notify.py',
    'tools/gen_restart_notify.py', 'tools/audit_cloud.py',
    'tools/cd2_watchdog.py', 'tools/cd2_queue_health.py',
]


def ast_check():
    print('=' * 78)
    print('第一层：静态检查（AST 找未定义名字）')
    print('=' * 78)
    bad = 0
    for rel in FILES_FOR_AST:
        p = os.path.join(ROOT, rel.replace('/', os.sep))
        if not os.path.exists(p):
            print(f'  -- {rel} 不存在')
            continue
        try:
            tree = ast.parse(open(p, encoding='utf-8').read())
        except SyntaxError as e:
            print(f'  [X] {rel} 语法错误: {e}')
            bad += 1
            continue

        imported, defined, used, has_star = set(), set(), set(), False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imported.add((a.asname or a.name).split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name == '*':
                        has_star = True
                    else:
                        imported.add(a.asname or a.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Store):
                    defined.add(node.id)
                else:
                    used.add(node.id)
            elif isinstance(node, ast.arg):
                defined.add(node.arg)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                defined.add(node.name)
            elif isinstance(node, ast.alias):
                defined.add(node.asname or node.name.split('.')[0])

        if has_star:
            print(f'  [!] {rel} 有 import *（静态判不了，看第二层）')
            continue
        known = imported | defined | set(dir(__builtins__))
        unknown = sorted(n for n in used
                         if n not in known and not n.startswith('_'))
        if unknown:
            print(f'  [X] {rel}: 可能未定义 {unknown}')
            bad += 1
        else:
            print(f'  [OK] {rel}')
    return bad


def runtime_check():
    print()
    print('=' * 78)
    print('第二层：运行时检查（import + 关键名字可用）')
    print('=' * 78)
    import importlib
    bad = 0
    for mod, names in REQUIRED.items():
        try:
            m = importlib.import_module(mod)
        except Exception as e:
            print(f'  [X] {mod} 导入失败: {type(e).__name__}: {e}')
            bad += 1
            continue
        missing = [n for n in names if not hasattr(m, n)]
        if missing:
            print(f'  [X] {mod} 缺少名字: {missing}')
            bad += 1
        else:
            print(f'  [OK] {mod}  ({len(names)} 个关键名字都在)')
    return bad


def real_clean_test():
    """真实清理测试：造临时文件走一遍 delete，确认真的被删。

    这个测试本来能提前抓到 Cleaner 的 basename bug。
    """
    print()
    print('=' * 78)
    print('第三层：真实清理测试（临时文件走一遍 delete）')
    print('=' * 78)

    tmpdir = tempfile.mkdtemp(prefix='dmr_clean_test_')
    src = os.path.join(tmpdir, 'test_source.mkv')
    ass = os.path.join(tmpdir, 'test_danmaku.ass')
    with open(src, 'wb') as f:
        f.write(b'x' * 1024)
    with open(ass, 'w', encoding='utf-8') as f:
        f.write('danmaku')

    try:
        import queue as _q
        from DMR.Cleaner import Cleaner

        # Cleaner.__init__(pipe=(send_queue, recv_queue), **kwargs)
        send_q, recv_q = _q.Queue(), _q.Queue()
        lg = logging.getLogger('test_cleaner')
        lg.addHandler(logging.NullHandler())
        cl = Cleaner(pipe=(send_q, recv_q))

        # 用 FileInfo 包一下，模拟真实的清理任务
        from DMR.utils import FileInfo
        fi = FileInfo(path=src)
        try:
            fi['dm_file_id'] = ass
        except Exception:
            pass

        task = {'method': 'delete', 'args': {}, 'files': [fi],
                'source': 'test', 'request_id': 'test'}
        cl._clean_subprocess(task)

        src_gone = not os.path.exists(src)
        ass_gone = not os.path.exists(ass)
        print(f'  源文件被删:   {src_gone}  {"[OK]" if src_gone else "[X]"}')
        print(f'  弹幕文件被删: {ass_gone}  {"[OK]" if ass_gone else "[X]"}')
        return 0 if (src_gone and ass_gone) else 1
    except Exception as e:
        import traceback
        print(f'  [X] 清理测试抛异常: {type(e).__name__}: {e}')
        traceback.print_exc()
        return 1
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    b1 = ast_check()
    b2 = runtime_check()
    b3 = real_clean_test()
    print()
    print('=' * 78)
    print('总结')
    print('=' * 78)
    print(f'  静态检查问题: {b1}')
    print(f'  运行时问题:   {b2}')
    print(f'  真实清理问题: {b3}')
    if b1 + b2 + b3 == 0:
        print('\n  [OK] 全部通过')
    else:
        print('\n  [X] 有问题，需要修复')
    sys.exit(0 if (b1 + b2 + b3) == 0 else 1)
