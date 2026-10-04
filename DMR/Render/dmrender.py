import copy
import logging
import os
import platform

from .baserender import BaseRender
from .ffmpeg import RawFFmpegRender
from os.path import exists
from DMR.utils import *

class DmRender(BaseRender):
    def __init__(self,
                 hwaccel_args: list,
                 vencoder: str,
                 vencoder_args: list,
                 aencoder: str,
                 aencoder_args: list,
                 output_resize: str,
                 advanced_render_args: dict=None,
                 gop_multiplier=None,
                 gop_default_fps: float = 30,
                 ffmpeg: str = None,
                 debug=False,
                 **kwargs
                 ):
        self.hwaccel_args = hwaccel_args if hwaccel_args is not None else []
        self.vencoder = vencoder
        self.vencoder_args = vencoder_args
        self.aencoder = aencoder
        self.aencoder_args = aencoder_args
        self.output_resize = output_resize
        self.advanced_render_args = advanced_render_args if isinstance(advanced_render_args, dict) else {}
        # GOP（关键帧间隔）设置：gop_multiplier = N 时，GOP = round(源帧率 * N)，即每 N 秒一个关键帧
        # 为 None / 0 / False / 'off' 时不干预，交给编码器默认行为；为 'auto' 时等价于 8
        self.gop_multiplier = self._parse_gop_multiplier(gop_multiplier)
        self.gop_default_fps = float(gop_default_fps or 30)
        self.ffmpeg = ffmpeg if ffmpeg else ToolsList.get('ffmpeg')
        self.debug = debug

        self.logger = logging.getLogger(__name__)
        self._check_encoder_args()
        self.raw_ffmpeg = RawFFmpegRender(debug=self.debug)

    # 这些编码参数不带流说明符（写成 -global_quality 而不是 -global_quality:v）时，
    # ffmpeg 会把它们**同时套到音频编码器**上。libopus/libvorbis 只支持码率模式，
    # 遇到质量模式会直接报错：
    #   Quality-based encoding not supported, please specify a bitrate and VBR setting.
    # 结果就是渲染必然失败、输出 0 字节。这里提前把问题指出来。
    _QUALITY_ARGS = ('-global_quality', '-qp', '-qscale', '-crf', '-cq', '-qmin', '-qmax')

    def _check_encoder_args(self):
        unspecific = []
        for arg in list(self.vencoder_args or []) + list(self.aencoder_args or []):
            name = str(arg).split(':')[0]
            if name in self._QUALITY_ARGS and not str(arg).endswith(':v'):
                unspecific.append(str(arg))

        if unspecific:
            self.logger.warning(
                f'编码参数 {unspecific} 没有指定 :v 流说明符，ffmpeg 会把它同时应用到音频编码器 '
                f'({self.aencoder}) 上。如果音频编码器是 libopus/libvorbis，渲染会直接失败并输出 0 字节文件。'
                f'建议改写成 {[a + ":v" for a in unspecific]}。'
            )

    @staticmethod
    def _parse_gop_multiplier(value):
        if value is None or value is False:
            return None
        if isinstance(value, str):
            value = value.strip().lower()
            if value in ('', 'none', 'off', 'false', 'no', 'null', '~'):
                return None
            if value == 'auto':
                return 8.0
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _build_gop_args(self, video: str) -> list:
        """按源视频帧率生成 -g 参数。任何异常都不应影响渲染，失败时返回空列表。"""
        if not self.gop_multiplier:
            return []
        # 用户在 vencoder_args 里自己写了 -g / -g:v 时以用户为准
        if any(str(x).rstrip(':v') == '-g' for x in self.vencoder_args):
            self.logger.debug('vencoder_args 中已指定 -g，跳过自动 GOP 设置。')
            return []
        fps = FFprobe.get_fps(video, fallback=self.gop_default_fps)
        if fps <= 0:
            fps = self.gop_default_fps
            self.logger.warning(f'获取视频帧率失败，GOP 按默认帧率 {fps} 计算。')
        gop = max(1, int(round(fps * self.gop_multiplier)))
        self.logger.info(f'GOP: 源帧率 {fps:g} x {self.gop_multiplier:g} = {gop} 帧关键帧间隔。')
        return ['-g', str(gop)]

    def render_helper(self, video: str, danmaku: str, output: str, to_stdout: bool = False, logfile=None):
        ffmpeg_args = [self.ffmpeg, '-y']
        ffmpeg_args += self.hwaccel_args

        if self.output_resize:
            if 'x' in str(self.output_resize):
                scale_args = ['-s', self.output_resize]
            else:
                w, h = FFprobe.get_resolution(video)
                if not (h and w):
                    self.logger.warning(f'获取视频 {video} 分辨率失败, 将使用默认分辨率 1920x1080.')
                    w, h = 1920, 1080
                scale = float(self.output_resize)
                w, h = int(w*scale), int(h*scale)
                scale_args = ['-s', f'{w}x{h}']
        else:
            scale_args = ['-noautoscale']

        if platform.system().lower() == 'windows':
            danmaku = danmaku.replace("\\", "/").replace(":/", "\\:/")
        
        # 自定义video filter
        if self.advanced_render_args.get('filter_complex'):
            filter_name = '-filter_complex'
            filter_str = self.advanced_render_args.get('filter_complex')
            filter_str = replace_keywords(filter_str, {'danmaku': danmaku})
        else:
            filter_name = '-vf'
            filter_str = 'subtitles=filename=\'%s\'' % danmaku
        
        ffmpeg_args += [
            '-fflags', '+discardcorrupt+genpts',
            '-analyzeduration', '2147483647', '-probesize', '2147483647',
            '-i', video,
            filter_name, filter_str,

            '-c:v', self.vencoder,
            *self._build_gop_args(video),
            *self.vencoder_args,
            '-c:a', self.aencoder,
            *self.aencoder_args,
            *scale_args,
            output,
        ]

        return self.raw_ffmpeg.call_ffmpeg(ffmpeg_args)

    def render_one(self, video: VideoInfo, output: str, **kwargs):
        if not exists(video.path):
            raise RuntimeError(f'不存在视频文件 {video.path}，跳过渲染.')
        danmaku = kwargs.get('danmaku') or video.dm_file_id
        if not danmaku or not exists(danmaku):
            raise RuntimeError(f'不存在弹幕文件 {danmaku}，跳过渲染.')

        valid_output = safe_filename(output)
        if valid_output != output:
            self.logger.warning(f'输出文件名 {output} 不合法或已存在，已更改为 {valid_output}.')
            output = valid_output   

        start_time = datetime.now()
        status, info = self.render_helper(video.path, danmaku, output, **kwargs)
        if status:
            output_info:VideoInfo = copy.deepcopy(video)
            output_info.dtype = 'dm_video'
            output_info.path = output
            output_info.file_id = uuid()
            output_info.size = os.path.getsize(output)
            output_info.ctime = start_time
            output_info.dm_file_id = None
            output_info.src_video_id = video.file_id
            return status, output_info
        else:
            return status, info

    def stop(self):
        self.logger.debug('ffmpeg render stop.')
        self.raw_ffmpeg.stop()
