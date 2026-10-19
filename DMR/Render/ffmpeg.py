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
        # 源视频时长（秒）。只用于计算"渲染超时"上限，见 call_ffmpeg。
        # ⚠️ 2026-10-19：这个属性最初由超时逻辑 getattr 读取，但**从来没有人赋值**，
        #    于是超时恒为 600 秒 —— 而实测 72 次渲染里有 2 次超过 600 秒
        #    （最长 16.1 分钟，3 小时分段），libx265 降级更是要 31 分钟。
        #    那些正常渲染会被这个"保护"直接杀掉。现在由 set_source() 显式赋值。
        self.src_duration = 0.0

    def set_source(self, video_info=None, path=None) -> None:
        """渲染前登记源时长，供超时计算使用。

        优先用 ``VideoInfo.duration``（录制侧按墙钟算，最贴近真实时长）；
        拿不到（0/None/-1）再退回 ffprobe；两者都失败则保持 0，
        由 ``call_ffmpeg`` 用保守下限兜底。
        """
        duration = 0.0
        try:
            duration = float(getattr(video_info, 'duration', 0) or 0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration <= 0 and path:
            try:
                # ⚠️ FFprobe.get_duration 失败时返回 **-1**（哨兵值），必须显式排除
                probed = float(FFprobe.get_duration(path) or 0)
                duration = probed if probed > 0 else 0.0
            except Exception:
                duration = 0.0
        self.src_duration = duration if duration > 0 else 0.0
        self.logger.debug(
            f'渲染超时基线：源时长 {self.src_duration:.0f} 秒 → 上限 '
            f'{self._render_timeout():.0f} 秒')

    def _render_timeout(self) -> float:
        """渲染超时上限（秒）。

        正常渲染约 1/6 实时，软编码降级约 1/2 实时，这里给 10 倍源时长 + 10 分钟，
        足以覆盖任何正常情况；下限 1 小时，用于"源时长探测失败"时仍能兜住卡死。
        """
        try:
            duration = float(self.src_duration or 0)
        except (TypeError, ValueError):
            duration = 0.0
        return max(3600.0, duration * 10 + 600)

    def call_ffmpeg(self, cmds, **kwargs):
        ffmpeg_args = [str(x) for x in cmds]
        self.logger.debug(f'ffmpeg render args: {ffmpeg_args}')

        with tempfile.TemporaryFile() as logfile:
            # stdout 是 sys.stdout 或临时文件，都不是管道：Python 不会为其分配 bufsize
            # 指定的缓冲，原来的 bufsize=10**8 是无效参数（现已移除）。
            if self.debug:
                self.render_proc = subprocess.Popen(
                    ffmpeg_args, stdin=sys.stdin, stdout=sys.stdout, stderr=subprocess.STDOUT)
            else:
                self.render_proc = subprocess.Popen(
                    ffmpeg_args, stdin=subprocess.PIPE, stdout=logfile, stderr=subprocess.STDOUT)

            # ⚠️ 必须读退出码！原版把 wait() 的返回值丢了，改成靠日志里有没有
            # "video:" 来猜成功 —— 只要 ffmpeg 打印过 Stream mapping 段再失败，
            # 就被判成成功，0 字节/残缺产物继续往下游走（2026-10-05 的 libopus
            # 事故正是这样把失败渲染当成功，然后清理逻辑删掉了源视频）。
            # ⚠️ 2026-10-19：加超时。渲染卡死（如 QSV 会话被占满后
            #    彻底不响应）时，max_workers=1 的线程池会被永久占住，
            #    后续渲染全部排队。超时值见 _render_timeout()。
            _timeout = self._render_timeout()
            try:
                returncode = self.render_proc.wait(timeout=_timeout)
            except subprocess.TimeoutExpired:
                self.logger.error(
                    f'渲染超过 {_timeout:.0f} 秒未完成（源时长 {self.src_duration:.0f} 秒），'
                    f'强制终止: {self.render_proc.args[:3]}')
                try:
                    self.render_proc.kill()
                except Exception:
                    pass
                returncode = -1

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
