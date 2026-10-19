import json
import logging
import os
import queue
import threading
import time

from concurrent.futures import ThreadPoolExecutor
from os.path import exists, isdir, isfile, abspath, dirname, basename
from typing import Tuple
from DMR.utils import *


class Cleaner():
    def __init__(self,
                 pipe:Tuple[queue.Queue, queue.Queue],
                 **kwargs,
                 ) -> None:
        
        self.send_queue, self.recv_queue = pipe
        self.logger = logging.getLogger('DMR.Cleaner')
        self.kwargs = kwargs
        self.stoped = True

        self._piperecvprocess = None
        self.clean_executors = ThreadPoolExecutor(max_workers=1)
        # ⚠️ 2026-10-19：必须用 RLock。add_task 已持有这把锁，
        #    而它里面调的 _journal_add 也要拿同一把。
        #    普通 Lock 不可重入 → 自死锁（第一版就是这么挂住的）。
        self._lock = threading.RLock()
        # P0-1：重读待删清单，把上次进程没来得及执行的延迟清理接回来
        try:
            self._rearm_pending()
        except Exception as e:
            self.logger.error(f'恢复待删清单失败（不影响正常清理）: {type(e).__name__}: {e}')
    
    # ── 待删清单（P0-1 修复，2026-10-19）──────────────────────────────
    #
    # 背景：延迟清理原来只用 threading.Timer，进程一重启就丢；
    # 而状态在派发瞬间已写成 cleaned（终态），重启后既没人重试、也没人知道。
    # 实测：10-19 00:06 一次重启就让 38 个源视频（6.42 GB）的删除定时器全部蒸发。
    #
    # 现在把「待删清单」落盘为权威记录：进程内 Timer 只是加速手段，
    # 真正的真相在 JSON 里。启动时重读并按到期时间重新 arm。

    @staticmethod
    def _journal_path() -> str:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(root, 'logs', 'pending_clean.json')

    def _journal_load(self) -> list:
        p = self._journal_path()
        if not os.path.exists(p):
            return []
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as e:
            self.logger.warning(f'待删清单损坏，已忽略: {type(e).__name__}: {e}')
            return []

    def _journal_save(self, entries: list) -> None:
        p = self._journal_path()
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(entries, f, ensure_ascii=False, indent=1)
            os.replace(tmp, p)   # 原子替换，避免半截文件
        except Exception as e:
            self.logger.error(f'写待删清单失败: {type(e).__name__}: {e}')

    def _journal_add(self, entry: dict) -> None:
        with self._lock:
            entries = self._journal_load()
            entries = [e for e in entries if e.get('id') != entry.get('id')]
            entries.append(entry)
            self._journal_save(entries)

    def _journal_remove(self, entry_id) -> None:
        if not entry_id:
            return
        with self._lock:
            entries = self._journal_load()
            kept = [e for e in entries if e.get('id') != entry_id]
            if len(kept) != len(entries):
                self._journal_save(kept)

    class _PendingFile:
        """把落盘的路径还原成 _clean_subprocess 需要的最小对象。"""

        __slots__ = ('path', 'dm_file_id')

        def __init__(self, path, dm_file_id=None):
            self.path = path
            self.dm_file_id = dm_file_id

        def get(self, name, default=None):
            if name == 'dm_file_id':
                return self.dm_file_id
            return default

        def __getitem__(self, name):
            if name == 'dm_file_id':
                return self.dm_file_id
            raise KeyError(name)

    def _rearm_pending(self) -> None:
        """启动时重读待删清单：到期的立刻删，未到期的重新 arm。"""
        entries = self._journal_load()
        if not entries:
            return
        now = time.time()
        alive, overdue = [], []
        for e in entries:
            pairs = e.get('pairs') or []
            # 文件已经不存在 → 直接从清单剔除（幂等）
            pairs = [(a, b) for a, b in pairs if a and os.path.exists(a)]
            if not pairs:
                continue
            e['pairs'] = pairs
            (overdue if float(e.get('due_ts') or 0) <= now else alive).append(e)

        self.logger.info(
            f'待删清单：{len(entries)} 条，其中已到期 {len(overdue)} 条、'
            f'未到期 {len(alive)} 条（文件已消失的已剔除）'
        )

        def _mk_task(e):
            return {
                'uuid': e.get('id'),
                'journal_id': e.get('id'),
                'source': 'cleaner',
                'request_id': None,
                'method': 'delete',
                'args': {},
                'files': [self._PendingFile(a, b) for a, b in e['pairs']],
                'config': {},
            }

        for e in overdue:
            self.logger.info(
                f'补删过期项（应在 {time.strftime("%m-%d %H:%M", time.localtime(float(e["due_ts"])))} '
                f'删除）: {", ".join(basename(a) for a, _ in e["pairs"])}'
            )
            self.clean_executors.submit(self._clean_subprocess, _mk_task(e))

        for e in alive:
            wait_s = max(0.0, float(e['due_ts']) - now)
            timer = threading.Timer(wait_s, self.clean_executors.submit,
                                    args=(self._clean_subprocess, _mk_task(e)))
            timer.daemon = True
            timer.start()
            self.logger.debug(
                f'重新 arm 延迟清理（还剩 {wait_s/3600:.1f} 小时）: '
                f'{", ".join(basename(a) for a, _ in e["pairs"])}'
            )

        # ⚠️ 2026-10-19 修：原来只在 overdue 非空时才保存，
        #    于是“文件全部已消失、没有到期项”时清单**永远不会被清空**，
        #    每次启动都重复扫一遍废条目。现在只要发生了剔除就写回。
        if len(alive) + len(overdue) != len(entries):
            self._journal_save(alive)

    def _pipeSend(self, event, msg, target='engine', request_id=None, dtype=None, data=None, **kwargs):
        if self.send_queue:
            msg = PipeMessage(
                source='cleaner',
                target=target,
                event=event,
                request_id=request_id,
                msg=msg,
                dtype=dtype,
                data=data,
                **kwargs,
            )
            self.send_queue.put(msg)

    def _pipeRecvMonitor(self):
        while self.stoped == False and self.recv_queue is not None:
            message:PipeMessage = self.recv_queue.get()
            try:
                if message.target == 'cleaner':
                   if message.event == 'newtask':
                       self.add_task(message)
            except Exception as e:
                self.logger.error(f'Message:{message} raise an error.')
                self.logger.exception(e)

    def start(self):
        self.stoped = False
        self._piperecvprocess = threading.Thread(target=self._pipeRecvMonitor, daemon=True)
        self._piperecvprocess.start()

    def add_task(self, msg:PipeMessage):
        with self._lock:
            config = msg.data
            method = config.get('method')
            if not method: return 
            task = {
                'uuid': uuid(),
                'source': msg.source,
                'request_id': msg.request_id,
                'method': config.get('method'),
                'args': config.get('args', {}),
                'files': config.get('files'),
                'config': config,
            }
            _delay = config.get('delay', 0) or 0
            if _delay > 0:
                # P0-1：先把待删项落盘，再挂进程内定时器。
                # 定时器只是加速手段，真正的真相在 logs/pending_clean.json --
                # 进程重启也不会丢（这是 6.42 GB 泄漏的根因）。
                if method == 'delete':
                    try:
                        pairs = []
                        for _f in (task['files'] or []):
                            _dm = _f.get('dm_file_id') if hasattr(_f, 'get') else None
                            pairs.append([getattr(_f, 'path', None), _dm])
                        self._journal_add({
                            'id': task['uuid'],
                            'due_ts': time.time() + float(_delay),
                            'created_ts': time.time(),
                            'delay': float(_delay),
                            'pairs': pairs,
                            'source': task.get('source'),
                        })
                        task['journal_id'] = task['uuid']
                        self.logger.debug(
                            f"延迟清理已落盘（{_delay/3600:.1f} 小时后执行）: "
                            f"{', '.join(basename(p or '') for p, _ in pairs)}"
                        )
                    except Exception as e:
                        self.logger.error(
                            f'写待删清单失败（本次仍会清理，但重启后会丢）: '
                            f'{type(e).__name__}: {e}')
                else:
                    self.logger.warning(
                        f'延迟清理的 method={method} 目前**不支持落盘**'
                        f'（只有 delete 支持）。进程重启后这次清理会丢失。')
                _t = threading.Timer(_delay, self.clean_executors.submit,
                                     args=(self._clean_subprocess, task))
                _t.daemon = True
                _t.start()
            else:
                self.clean_executors.submit(self._clean_subprocess, task)

    def _clean_subprocess(self, task):
        try:
            method = task['method']
            clean_args = task['args']
            dst = clean_args.get('dest')
            cleaned_files = []
            for file in task['files']:
                file:FileInfo
                if not exists(file.path):
                    self.logger.warning(f'文件 {file.path} 不存在，跳过清理.')
                    continue

                # ── 清理消息：原文件和弹幕文件合并成一行 ──
                # 弹幕文件（.ass）本身属于原视频的附属产物，分开报会很乱。
                # 目标格式：
                #     正在清理原文件: xxx.mkv（含弹幕）
                #     已在清理循环里决定（见下方 dm_file 判断）
                _base = basename(file.path)
                dm_file = file.get('dm_file_id')
                _has_dm = bool(dm_file and exists(dm_file))

                if _has_dm:
                    self.logger.log(25, f'正在清理原文件: {_base}（含弹幕文件）')  # PROGRESS
                else:
                    self.logger.log(25, f'正在清理原文件: {_base}')  # PROGRESS

                src = abspath(file.path)
                if dst and not dst.startswith('*'):
                    dst = abspath(replace_keywords(dst, file, replace_invalid=True))
                    if not exists(dst):
                        self.logger.info(f'目标文件夹 {dst} 不存在，即将自动创建.')
                        os.makedirs(dst)

                files = [src]
                if _has_dm:
                    files.append(dm_file)
                # 记录 (原文件路径, 是否含弹幕文件)，供完成事件拼文案用
                cleaned_files.append((src, _has_dm))
                
                for f in files:
                    if method == 'move':
                        from .move import move
                        move.move(f, dst)
                    elif method == 'copy':
                        from .copy import copy
                        copy.copy(f, dst)
                    elif method == 'delete':
                        from .delete import delete
                        # ⚠️ 2026-10-19：删除做幂等。
                        # 幂等场景：进程内定时器与启动重 arm 可能同时命中同一文件，
                        # 第二次会报 PermissionError/FileNotFoundError。
                        # 只要文件确实已不存在，就当成功。
                        try:
                            delete.delete(f)
                        except (FileNotFoundError, PermissionError):
                            if not exists(f):
                                self.logger.debug(f'文件已被删除（竞态，当成功）: {basename(f)}')
                            else:
                                raise
                    elif method == 'custom':
                        from ..utils import runcmd
                        cmds = [replace_keywords(str(x), file) for x in clean_args.get('command')]
                        wait = clean_args.get('wait', True)
                        p = runcmd.runcmd(cmds, wait=wait, **clean_args.get('subprocess_kwargs', {}))
                        if wait and p.returncode != 0:
                            raise RuntimeError(f'命令执行失败: {cmds}')
                
            # 完成文案与"正在清理原文件"保持一致：只留文件名，
            # 有弹幕的标注（含弹幕文件）
            _parts = []
            for _p, _dm in cleaned_files:
                # 弹幕文件不在 cleaned_files 里单独列（它归入原文件）
                _parts.append(basename(_p) + ('（含弹幕文件）' if _dm else ''))
            self._pipeSend('end', f'清理完成: {", ".join(_parts)}', target=task['source'], request_id=task['request_id'])
            # P0-1：真正删完了才把清单条目移除。
            # 失败时**保留**条目 —— 下次启动会再试一次（文件不存在的会被自动剔除，
            # 所以不会无限循环）。
            self._journal_remove(task.get('journal_id'))
        except Exception as e:
            self.logger.exception(e)
            self._pipeSend('error', f'清理错误 {e}.', target=task['source'], request_id=task['request_id'], dtype='Exception', data=e)
            
    def stop(self):
        self.stoped = True
