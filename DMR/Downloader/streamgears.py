import json
import logging
import subprocess
import sys
import os
import glob

from datetime import datetime
from os.path import splitext, split, join, exists
import tempfile
import time
from DMR.utils import *
from DMR.LiveAPI import Onair


class StreamgearsDownloader():
    default_header = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
        }
    def __init__(self,  
                 stream_url:str, 
                 output_dir:str,
                 segment:int,
                 url:str,
                 taskname:str,
                 debug=False,
                 header:dict=None,
                 segment_callback=None,
                 inprogress_callback=None,
                 **kwargs):
        
        self.stream_url = stream_url
        self.header = header if header else self.default_header
        self.output_dir = output_dir
        self.segment = segment
        self.debug = debug
        self.taskname = taskname
        self.url = url
        # 上报"正在写入"的文件，使录制中途被强杀后残file能被对账发现
        self.inprogress_callback = inprogress_callback
        self.segment_callback = segment_callback
        self.kwargs = kwargs

        self.logger = logging.getLogger(__name__)
        self.stoped = False
    
    def start_helper(self):
        raw_name = join(self.output_dir, f'[正在录制]{self.taskname}-%Y%m%d%H%M%S-{self.uuid}')
        stream_url, header = self.stream_url, self.header

        streamgears_args = [
            sys.executable, 
            'DMR/Downloader/streamgears_wrapper.py',
            '-i', stream_url,
            '-o', raw_name, 
            '-s', self.segment,
            '--header', json.dumps(header),
        ]

        streamgears_args = [str(x) for x in streamgears_args]
        self.logger.debug(f'Stream-gears downloader args: {streamgears_args}')

        # stdout 是 sys.stdout 或临时文件，都不是管道：Python 不会为其分配 bufsize
        # 指定的缓冲，原来的 bufsize=10**8 是无效参数（现已移除）。
        if self.debug:
            self.streamgears_proc = subprocess.Popen(streamgears_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=subprocess.STDOUT)
            self.streamgears_proc.wait()
            return

        with tempfile.TemporaryFile(dir='.temp') as logfile:
        # with open('.temp/test.log', 'wb') as logfile:
            self.streamgears_proc = subprocess.Popen(streamgears_args, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT)

            # ── 停滞看门狗（2026-10-18 新增）────────────────────────────
            # 问题：biliup 偶尔会"连着但收不到数据"—— 进程活着、TCP 通、
            #   CPU 缓慢增长，但 .flv.part 长时间一个字节都不写。
            #   实测：断尾人类 2026-10-18 20:56 的分段卡在 495.9MB 达 18 分钟，
            #   同时弹幕 .ass 一直在写（说明直播还在），而 stop_wait_time=120
            #   意味着程序要等 2 小时才会判下播 —— 这期间全都在丢素材。
            # 做法：跟踪"最新分段的文件大小"，若 STALL_TIMEOUT 秒内没有任何
            #   增长就主动抛异常，交给外层的退避重连逻辑重新拉流。
            # 阈值取 300 秒（5 分钟）：正常直播不会连续 5 分钟一个字节都不写。
            STALL_TIMEOUT = 300
            _last_path, _last_size, _last_grow_ts = None, -1, time.time()

            while not self.stoped:
                if self.streamgears_proc.poll() is not None:
                    break

                files = sorted(glob.glob(join(self.output_dir, f'*{self.uuid}*')))
                # 列表最后一个文件是正在写入、尚未封闭的分段，上报它使中途被杀的
                # 残file有记录（仅在变化时上报，避免重复写库）
                if files and files[-1] != getattr(self, '_last_reported', None) \
                        and self.inprogress_callback:
                    self._last_reported = files[-1]
                    self.inprogress_callback(files[-1])
                # 最后一个文件不算在内
                for p in range(len(files)-1):
                    self.segment_callback(files[p])

                # ── 停滞判定 ──
                if files:
                    cur = files[-1]
                    try:
                        size = os.path.getsize(cur)
                    except OSError:
                        size = -1
                    if cur != _last_path or size > _last_size:
                        # 换了新分段，或体积有增长 → 视为活跃
                        _last_path, _last_size, _last_grow_ts = cur, size, time.time()
                    elif size >= 0 and time.time() - _last_grow_ts > STALL_TIMEOUT:
                        logfile.seek(0)
                        _tail = logfile.read().decode('utf8', errors='ignore')[-600:]
                        # 先停掉子进程，避免它和新一轮录制同时写文件
                        try:
                            self.stoped = True
                            self.streamgears_proc.kill()
                        except Exception:
                            pass
                        raise RuntimeError(
                            f'{self.taskname} 录制停滞：分段 {os.path.basename(cur)} '
                            f'在 {STALL_TIMEOUT} 秒内没有任何增长（停在 {size} 字节），'
                            f'判定为"假连接"，主动重连。biliup 输出尾部:\n{_tail}')

                time.sleep(10)

            if not self.stoped and Onair(self.url):
                logfile.seek(0)
                log = logfile.read().decode('utf8', errors='ignore')
                raise RuntimeError(f'{self.taskname} Stream-gears 异常退出 {log[-1000:]}.')

    def start(self):
        # 生成一个uuid，用于标记这次录制的文件
        self.uuid = uuid(16)
        return self.start_helper()
    
    def stop(self):
        self.stoped = True
        try:
            self.streamgears_proc.kill()
            out, _ = self.streamgears_proc.communicate(timeout=0.1)
            if out: 
                self.logger.debug(f'{self.taskname} streamgears: {out}')
        except Exception as e:
            self.logger.debug(e)

        files = sorted(glob.glob(join(self.output_dir, f'*{self.uuid}*')))
        for p in range(len(files)):
            self.segment_callback(files[p])
        
        self.logger.debug('Stream-gears downloader stoped.')
