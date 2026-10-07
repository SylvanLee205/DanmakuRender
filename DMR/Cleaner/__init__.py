import logging
import os
import queue
import threading

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
        self._lock = threading.Lock()
    
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
            if config.get('delay', 0) > 0:
                threading.Timer(config.get('delay'), self.clean_executors.submit, args=(self._clean_subprocess, task)).start()
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
                        delete.delete(f)
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
        except Exception as e:
            self.logger.exception(e)
            self._pipeSend('error', f'清理错误 {e}.', target=task['source'], request_id=task['request_id'], dtype='Exception', data=e)
            
    def stop(self):
        self.stoped = True
