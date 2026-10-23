import logging
import os
import queue
import threading

from DMR.utils import *

class Downloader():
    def __init__(self,
                 pipe:Tuple[queue.Queue, queue.Queue],
                 state_repo=None,
                 **kwargs,
                 ) -> None:
        self.send_queue, self.recv_queue = pipe
        self.logger = logging.getLogger('DMR.Downloader')
        self.kwargs = kwargs
        self.stoped = True

        # 状态持久化（P1）：下载任务用它登记录制场次与已完成的产物分段。
        # ⚠️ 2026-10-15 复查发现：合并上游时这个参数漏了，导致
        #    Downloader 实例没有 state_repo 属性，newtask 也就无法把它
        #    透传给 StreamDownloadTask —— 结果"分段登记到状态库"是哑的
        #    （unit_tests/test_state_init.py::test_downloader_plugin_receives_state_repo
        #      正好抓到了这个）。现已补齐。
        self.state_repo = state_repo

        self._piperecvprocess = None
        self.download_tasks = {}
    
    def _pipeSend(self, event, msg, target='engine', dtype=None, data=None, **kwargs):
        if self.send_queue:
            msg = PipeMessage(
                source='downloader',
                target=target,
                event=event,
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
                if message.target == 'downloader':
                    if message.event == 'stoptask':
                        self.stoptask(message.data)
                    elif message.event == 'newtask':
                        self.newtask(message)
                    elif message.event == 'exit':
                        break
            except Exception as e:
                self.logger.error(f'Message:{message} raise an error.')
                self.logger.exception(e)
                # 2026-10-23：newtask 失败不能就这么算了 —— 见下方重试逻辑。
                self._schedule_newtask_retry(message)

    # ── 2026-10-23：下载任务创建失败自动重试 ────────────────────────
    # 实盘事故：抖音接口 5 秒读超时发生在 StreamDownloadTask 构造
    # （LiveAPI(url) → 解析房间号）的那一瞬间，newtask 抛异常 →
    # 消息被 _pipeRecvMonitor 的 except 吞掉 → **这个主播本次开播就不会被
    # 录制**，而且没有任何自动重试，只能重启程序或改动配置才会重新派发。
    # "没录起来"是最大的隐患，所以这里补一个有界重试（不是无限重试，
    # 避免配置本身有问题时刷屏）。
    NEWTASK_MAX_RETRY = 3
    NEWTASK_RETRY_DELAY = 30

    def _schedule_newtask_retry(self, message) -> None:
        """newtask 创建失败时安排重发；其它事件不重试（没有重发语义）。"""
        if getattr(message, 'event', None) != 'newtask':
            return
        data = message.data if isinstance(message.data, dict) else {}
        tries = int(data.get('_dl_retry', 0) or 0)
        name = data.get('taskname', '?')
        if tries >= self.NEWTASK_MAX_RETRY:
            self.logger.error(
                f'下载任务 {name} 连续 {tries} 次创建失败，本次放弃。'
                f'重启程序或改动任意配置可重新派发。')
            return
        data['_dl_retry'] = tries + 1
        delay = self.NEWTASK_RETRY_DELAY * (tries + 1)
        self.logger.warning(
            f'下载任务 {name} 创建失败，{delay} 秒后重试'
            f'（第 {tries + 1}/{self.NEWTASK_MAX_RETRY} 次）。')
        timer = threading.Timer(delay, self._requeue_newtask, args=(message,))
        timer.daemon = True
        timer.start()

    def _requeue_newtask(self, message) -> None:
        if self.stoped or self.recv_queue is None:
            return
        self.recv_queue.put(message)
        
    def stoptask(self, taskname:str):
        if taskname in self.download_tasks:
            self.download_tasks[taskname].stop()
            del self.download_tasks[taskname]
            self._pipeSend(event='info', msg=f'下载任务 {taskname} 已停止。', dtype='str', data=taskname)
        else:
            raise ValueError(f'下载任务 {taskname} 不存在。')
        
    def newtask(self, message:PipeMessage):
        taskname = message.data['taskname']
        dltype = message.data['dltype']
        config = message.data['config']
        if taskname in self.download_tasks:
            raise ValueError(f'下载任务 {taskname} 已存在。')
        
        if dltype == 'live':
            if config.get('sync', False):
                from .sync_stream_downloader import SyncStreamDownloadTask
                downloader_task = SyncStreamDownloadTask
            else:
                from .stream_downloader import StreamDownloadTask
                downloader_task = StreamDownloadTask
        elif dltype == 'videos':
            from .video_downloader import VideoDownloadTask
            downloader_task = VideoDownloadTask
        elif dltype == 'virtual':
            from .virtual_downloader import VirtualDownloaderTask
            downloader_task = VirtualDownloaderTask

        # 把状态库透传给具体的下载任务（StreamDownloadTask 用它登记场次与分段）
        if self.state_repo is not None:
            config = {**config, 'state_repo': self.state_repo}
        self.download_tasks[taskname] = downloader_task(taskname=taskname, send_queue=self.send_queue, **config)
        self.download_tasks[taskname].start()
        self._pipeSend(event='info', msg=f'下载任务 {taskname} 已启动。', dtype='str', data=taskname)
        
    def start(self):
        self.stoped = False
        self._piperecvprocess = threading.Thread(target=self._pipeRecvMonitor, daemon=True)
        self._piperecvprocess.start()

    def stop(self):
        self.stoped = True
        self.recv_queue.put(PipeMessage(source='downloader', target='downloader', event='exit'))
        for taskname in list(self.download_tasks.keys()):
            self.stoptask(taskname)
        self.logger.info('Downloader stoped.')
        self._pipeSend(event='info', msg='下载器已停止.')
