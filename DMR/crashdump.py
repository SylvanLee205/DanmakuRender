"""崩溃现场快照：把"出事那一刻"完整留在磁盘上。

为什么需要
----------
现在的日志是**正常退出也会写**的，崩溃时只能从 tail 里猜。真正要查的是：
    * 哪个线程、哪一行炸的（完整 traceback）
    * 当时其他线程在干什么（死锁？卡在网络？）
    * 崩溃前最后几十行日志
    * 进程状态（内存、句柄）

这些如果不主动抓，事后一个都拿不到。

抓什么
------
1. ``sys.excepthook``      —— 主线程未捕获异常
2. ``threading.excepthook``—— 子线程未捕获异常（**最常见**，以前完全静默）
3. ``faulthandler``        —— C 层崩溃（段错误、0xC0000005），
                              这是 faulthandler 唯一能抓到的场景

产物
----
    .temp/crash-YYYYmmdd-HHMMSS-<pid>.txt   每个崩溃一个文件，保留最近 12 个
    .temp/faulthandler.log                  C 层崩溃的原始栈（常驻写入）

⚠️ 只写文件、**不发通知**。崩溃通知由 autostart/守护脚本负责，
   这里再发一次会重复轰炸。

用法（main.py 启动时调一次）::

    from DMR import crashdump
    crashdump.install()
"""
import faulthandler
import os
import sys
import threading
import time
import traceback

__all__ = ('install', 'snapshot', 'KEEP')

#: 保留多少个崩溃文件
KEEP = 12

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMP = os.path.join(_ROOT, '.temp')
_LOGS = os.path.join(_ROOT, 'logs')

_fh_file = None
_installed = False


def _tail_log(n=300) -> str:
    """取最近一个 DMR 日志的尾部。"""
    try:
        names = [f for f in os.listdir(_LOGS)
                 if f.startswith('DMR-') and f.endswith('.log')]
        if not names:
            return '(没有日志文件)'
        newest = max((os.path.join(_LOGS, f) for f in names), key=os.path.getmtime)
        with open(newest, encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        return f'--- {os.path.basename(newest)} 最后 {n} 行 ---\n' + ''.join(lines[-n:])
    except Exception as e:
        return f'(读日志失败: {e})'


def _process_info() -> str:
    out = [f'PID       : {os.getpid()}',
           f'主线程     : {threading.main_thread().name}',
           f'线程数     : {threading.active_count()}',
           f'工作目录   : {os.getcwd()}',
           f'解释器     : {sys.executable}',
           f'Python     : {sys.version.splitlines()[0]}']
    try:
        import psutil
        p = psutil.Process()
        mem = p.memory_info()
        out.append(f'内存(RSS) : {mem.rss / 1024 / 1024:.0f} MB')
        out.append(f'句柄/连接 : {p.num_handles() if hasattr(p, "num_handles") else "n/a"}'
                   f' / {len(p.net_connections())}')
    except Exception:
        pass
    return '\n'.join(out)


def _thread_stacks() -> str:
    names = {t.ident: t.name for t in threading.enumerate()}
    parts = []
    frames = sys._current_frames()
    for ident, frame in frames.items():
        parts.append(f'\n=== 线程 {names.get(ident, "?")} (id={ident}) ===')
        parts.extend(traceback.format_stack(frame))
    return ''.join(parts) if parts else '(拿不到线程栈)'


def snapshot(reason: str, exc_info=None) -> str:
    """写一份崩溃快照，返回文件路径（失败返回 ''）。"""
    try:
        os.makedirs(_TEMP, exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        # ⚠️ 同一秒内可能连爆两次（主线程 + 子线程），光用秒级时间戳会互相覆盖。
        #    实测：同时触发线程异常和主线程异常，只留下了后一个。
        base = os.path.join(_TEMP, f'crash-{stamp}-{os.getpid()}')
        path = base + '.txt'
        _n = 1
        while os.path.exists(path):
            path = f'{base}-{_n}.txt'
            _n += 1

        chunks = [
            '=' * 70,
            f'DanmakuRepo 崩溃快照',
            f'时间: {time.strftime("%Y-%m-%d %H:%M:%S")}',
            f'类型: {reason}',
            '=' * 70,
            '',
            '【异常】',
        ]
        if exc_info:
            chunks.append(''.join(traceback.format_exception(*exc_info)))
        else:
            chunks.append('(无异常对象 —— 可能是 C 层崩溃或主动退出)')

        chunks += ['', '【进程】', _process_info(), '',
                   '【所有线程栈】', _thread_stacks(), '',
                   '【日志尾部】', _tail_log(), '']

        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(chunks))

        _prune()
        return path
    except Exception:
        return ''


def _prune() -> None:
    """只保留最近 KEEP 个崩溃文件。"""
    try:
        files = [os.path.join(_TEMP, f) for f in os.listdir(_TEMP)
                 if f.startswith('crash-') and f.endswith('.txt')]
        files.sort(key=os.path.getmtime)
        for old in files[:-KEEP]:
            try:
                os.remove(old)
            except OSError:
                pass
    except Exception:
        pass


def _excepthook(exc_type, exc_value, exc_tb):
    path = snapshot('未捕获异常（主线程）', (exc_type, exc_value, exc_tb))
    # 仍然打到 stderr，保持原有行为（守护脚本/控制台能看到）
    sys.__excepthook__(exc_type, exc_value, exc_tb)
    if path:
        try:
            print(f'\n[DMR] 崩溃快照已保存: {path}', file=sys.stderr)
        except Exception:
            pass


def _thread_excepthook(args):
    # 子线程异常以前**完全静默** —— 线程死了没人知道。
    if args.exc_type is SystemExit:
        return
    which = getattr(args.thread, 'name', '?')
    path = snapshot(f'未捕获异常（线程 {which}）',
                    (args.exc_type, args.exc_value, args.exc_traceback))
    try:
        print(f'\n[DMR] 线程 {which} 异常，快照: {path}', file=sys.stderr)
    except Exception:
        pass


def install() -> bool:
    """装好三个钩子。重复调用无副作用。"""
    global _fh_file, _installed
    if _installed:
        return True

    try:
        os.makedirs(_TEMP, exist_ok=True)
        _fh_file = open(os.path.join(_TEMP, 'faulthandler.log'), 'a', encoding='utf-8')
        faulthandler.enable(file=_fh_file, all_threads=True)
    except Exception:
        _fh_file = None

    sys.excepthook = _excepthook
    if hasattr(threading, 'excepthook'):
        threading.excepthook = _thread_excepthook

    _installed = True
    return True


def dump_now(reason='手动触发') -> str:
    """手动抓一份现场（排查"卡住不动"时用）。"""
    return snapshot(reason)
