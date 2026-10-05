import os
import platform
import signal
import sys
import subprocess
import logging
import tempfile

from .baserender import BaseRender
from os.path import exists
from DMR.utils import *

class RawFFmpegRender(BaseRender):
    def __init__(self,
                 debug=False,
                 **kwargs
                 ):
        self.debug = debug
        self.logger = logging.getLogger(__name__)

    def call_ffmpeg(self, cmds, **kwargs):
        ffmpeg_args = [str(x) for x in cmds]
        self.logger.debug(f'ffmpeg render args: {ffmpeg_args}')

        with tempfile.TemporaryFile() as logfile:
            if self.debug:
                self.render_proc = subprocess.Popen(
                    ffmpeg_args, stdin=sys.stdin, stdout=sys.stdout, stderr=subprocess.STDOUT, bufsize=10**8)
            else:
                self.render_proc = subprocess.Popen(
                    ffmpeg_args, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT, bufsize=10**8)

            # ⚠️ 必须读退出码！原版把 wait() 的返回值丢了，改成靠日志里有没有
            # "video:" 来猜成功 —— 只要 ffmpeg 打印过 Stream mapping 段再失败，
            # 就被判成成功，0 字节/残缺产物继续往下游走（2026-10-05 的 libopus
            # 事故正是这样把失败渲染当成功，然后清理逻辑删掉了源视频）。
            returncode = self.render_proc.wait()

            log = ''
            logfile.seek(0)
            for line in logfile.readlines():
                log += line.decode('utf-8', errors='ignore').strip() + '\n'

            if returncode == 0:
                # 成功时把 Stream mapping 里的视频行作为 detail 返回（日志用）
                info = ''
                for line in log.split('\n'):
                    if 'video:' in line:
                        info = line.strip()
                return True, info

            # 失败：日志尾部比整段日志更有用（真正的报错在最后）
            if self.debug:
                return False, f'ffmpeg 退出码 {returncode}（debug 模式，完整输出见终端）'
            tail = '\n'.join(log.strip().split('\n')[-30:])
            return False, f'ffmpeg 退出码 {returncode}\n{tail}'
            
    def render_one(self, cmds, **kwargs):
        start_time = datetime.now()
        status, info = self.call_ffmpeg(cmds, **kwargs)
        if status:
            output_info:VideoInfo = video.copy()
            output_info.path = output
            output_info.file_id = uuid()
            output_info.size = os.path.getsize(output)
            output_info.ctime = start_time
            output_info.src_video_id = video.file_id
            return status, output_info
        else:
            return status, info
            
    def stop(self):
        try:
            out, _ = self.render_proc.communicate(b'q', timeout=5)
            self.logger.debug(out)
        except subprocess.TimeoutExpired:
            self.render_proc.kill()
        except Exception as e:
            self.logger.debug(e)
