import copy
import logging
import os
import platform
import tempfile
import time

from .baserender import BaseRender
from .ffmpeg import RawFFmpegRender
from os.path import exists, splitext
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
                 dmconvert: dict=None,
                 gop_multiplier=None,
                 gop_default_fps: float = 30,
                 ffmpeg: str = None,
                 fallback_vencoder: str = 'libx265',
                 fallback_vencoder_args: list = None,
                 hw_retry: int = 2,
                 hw_retry_delay: float = 60,
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
        # XML 弹幕转换参数（见 DMR/Config/default.yml 的 render_args.dmrender.dmconvert）
        self.dmconvert = dmconvert if isinstance(dmconvert, dict) else {}
        # GOP（关键帧间隔）：N 时 GOP = round(源帧率 * N)，即每 N 秒一个关键帧。
        # None/0/False/'off' 时不干预，交给编码器默认；'auto' 等价于 8。
        self.gop_multiplier = self._parse_gop_multiplier(gop_multiplier)
        self.gop_default_fps = float(gop_default_fps or 30)
        # ── 硬件编码失败时的软件编码降级（2026-10-18 新增）──────────────
        # 起因：用户在后台跑双路批量渲染（都占 QSV），DMR 的 hevc_qsv 渲染
        # 在 33:47 报 Invalid FrameType:0 / -1094995529 直接失败，留下残缺产物。
        # 实测：同样的文件在 GPU 空闲时 4 种编码方案全部成功 —— 这是**资源争抢**，
        # 不是素材损坏。
        # 做法：硬件编码器（*_qsv / *_nvenc / *_vaapi / *_amf）渲染失败时，
        # 自动用软件编码器重试一次。正常情况下仍走硬件（快 2 倍+）。
        # 设为 None 或空串可关闭降级。
        self.fallback_vencoder = (fallback_vencoder or '').strip() or None
        if fallback_vencoder_args is None:
            # 实测对比（60 秒片段，同一素材）：
            #   QSV medium gq30      7.0 MB / 958 kbps / 12.7s   ← 当前配置
            #   libx265 veryfast crf28  7.7 MB / 1053 kbps / 22.3s (1.8x)
            #   libx265 medium  crf30   6.4 MB /  879 kbps / 36.4s (2.9x)
            # 取 veryfast+crf28：体积只比硬件大 10%，速度只慢 1.8 倍。
            fallback_vencoder_args = ['-preset', 'veryfast', '-crf', '28', '-tag:v', 'hvc1']
        self.fallback_vencoder_args = list(fallback_vencoder_args)
        # 硬件编码重试（用户要求：尽量硬解硬编，实在不行再软编码）
        self.hw_retry = max(0, int(hw_retry or 0))
        self.hw_retry_delay = max(0.0, float(hw_retry_delay or 0))
        self.ffmpeg = ffmpeg if ffmpeg else ToolsList.get('ffmpeg')
        self.debug = debug

        self.logger = logging.getLogger(__name__)
        self._check_encoder_args()
        self.raw_ffmpeg = RawFFmpegRender(debug=self.debug)

    #: 这些后缀的编码器属于硬件加速，可能因为会话被占用而失败
    _HW_ENCODER_MARKS = ('_qsv', '_nvenc', '_vaapi', '_amf', '_videotoolbox')

    def _is_hw_encoder(self, name: str) -> bool:
        return bool(name) and any(m in str(name).lower() for m in self._HW_ENCODER_MARKS)

    @staticmethod
    def _danmaku_last_timestamp(ass_path) -> float:
        """读 .ass 里最后一条 Dialogue 的时间戳（秒），失败返回 0。

        ⚠️ 为什么用它做时长参考（2026-10-18）：
            抖音的 FLV 流经常有时间戳跳变，导致录制文件的**容器时长被虚报**。
            实测：断尾人类 22:52 的分段实际只有 38 分钟，
            但 ffprobe 的 format.duration 报 13065 秒（217 分钟，虚报 5.7 倍）。
            如果用源容器时长做校验基准，正常的 38 分钟产物会被判成 17.7% 残缺。
            弹幕是按真实时间写的，最后一条 Dialogue 的时间戳 ≈ 分段真实时长，
            对本流水线来说是最可靠的参考。
        """
        if not ass_path:
            return 0.0
        try:
            last = 0.0
            pat = re.compile(r'^Dialogue:[^,]*,'
                             r'(\d+):(\d+):(\d+)\.(\d+)')
            with open(str(ass_path), 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    m = pat.match(line)
                    if not m:
                        continue
                    h, mi, sec, cs = (int(m.group(1)), int(m.group(2)),
                                      int(m.group(3)), int(m.group(4)))
                    ts = h * 3600 + mi * 60 + sec + cs / 100.0
                    if ts > last:
                        last = ts
            return last
        except Exception:
            return 0.0

    _QUALITY_ARGS = ('-global_quality', '-qp', '-qscale', '-crf', '-cq', '-qmin', '-qmax')

    def _check_encoder_args(self):
        """校验编码参数是否缺少 :v 流说明符（防 0 字节渲染事故）。

        这些参数不带流说明符时会被 ffmpeg 同时套到音频编码器上；
        libopus/libvorbis 只支持码率模式，遇到质量模式会直接失败，
        导致渲染输出 0 字节文件（2026-10-05 事故）。
        """
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
        """按源视频帧率生成 -g 参数。失败返回空列表（不影响渲染）。"""
        if not self.gop_multiplier:
            return []
        if any(str(x).rstrip(':v') == '-g' for x in self.vencoder_args):
            self.logger.debug('vencoder_args 中已指定 -g，跳过自动 GOP 设置。')
            return []
        fps = FFprobe.get_fps(video, fallback=self.gop_default_fps)
        if fps <= 0:
            fps = self.gop_default_fps
            self.logger.warning(f'获取视频帧率失败，GOP 按默认帧率 {fps} 计算。')
        gop = max(1, int(round(fps * self.gop_multiplier)))
        # GOP 是技术细节，控制台不必看：debug 级别（控制台不显示，日志保留）
        self.logger.debug(f'GOP: 源帧率 {fps:g} x {self.gop_multiplier:g} = {gop} 帧关键帧间隔。')
        return ['-g', str(gop)]

    def _video_resolution(self, video: str) -> tuple:
        """探测视频分辨率，供 XML→ASS 转换使用（ASS 的坐标基准）。"""
        w, h = FFprobe.get_resolution(video)
        if not (w and h):
            self.logger.warning(f'获取视频 {video} 分辨率失败, XML 弹幕转换将使用默认分辨率 1920x1080.')
            w, h = 1920, 1080
        return w, h

    def _prepare_danmaku(self, video: str, danmaku: str) -> tuple:
        """把弹幕准备成 ffmpeg ``subtitles`` 滤镜能吃的格式。

        本程序自己录制的弹幕已经是 ``.ass``，直接返回；外部来源的 ``.xml``
        （B站录播最常见的格式）先转换成 ``.ass``。

        :returns: ``(可渲染的弹幕路径, 需要清理的临时文件路径或 None)``
        """
        if not is_danmaku_xml(danmaku):
            return danmaku, None

        resolution_x, resolution_y = self._video_resolution(video)
        # 配置项与上游库参数名一致（font_name/font_size/displayarea/...），
        # 只把分辨率换成探测到的真实值；未在配置里写的键用 xml2ass 的默认值。
        args = dict(self.dmconvert)
        args['resolution_x'] = args.get('resolution_x') or resolution_x
        args['resolution_y'] = args.get('resolution_y') or resolution_y

        # 写进临时文件而不是 XML 旁边：渲染可能对源目录只读，且避免污染用户文件。
        # 放在输出目录同级优先，便于与产物同盘；失败则退回系统临时目录。
        fd, ass_file = tempfile.mkstemp(
            prefix=f'.{os.path.basename(splitext(danmaku)[0])}.',
            suffix=f'.{DEFAULT_ASS_SUFFIX}',
            dir=self._temp_dir_for(video),
        )
        os.close(fd)          # 只要名字，交给 dmconvert 写入

        self.logger.info(f'检测到 XML 弹幕，正在转换为 ASS: {danmaku}')
        try:
            xml_to_ass(danmaku, ass_file, args=args)
        except Exception:
            self._remove_quietly(ass_file)
            raise
        return ass_file, ass_file

    def _temp_dir_for(self, video: str) -> str:
        """选一个可写的临时目录：优先与视频同目录（同盘、便于排查），否则系统临时目录。"""
        for candidate in (os.path.dirname(os.path.abspath(video)), None):
            try:
                if candidate is None:
                    return tempfile.gettempdir()
                if os.access(candidate, os.W_OK):
                    return candidate
            except OSError:
                continue
        return tempfile.gettempdir()

    def _remove_quietly(self, path: str) -> None:
        if not path:
            return
        try:
            os.remove(path)
        except OSError as e:
            self.logger.debug(f'清理临时弹幕文件 {path} 失败: {e}')

    def render_helper(self, video: str, danmaku: str, output: str, to_stdout: bool = False, logfile=None,
                      vencoder: str = None, vencoder_args: list = None):
        """渲染单个视频。

        ``vencoder`` / ``vencoder_args`` 为空时用实例配置；
        软件编码降级时会显式传入替代编码器（见 ``_try_software_fallback``）。
        """
        vencoder = vencoder or self.vencoder
        vencoder_args = list(vencoder_args) if vencoder_args is not None else self.vencoder_args

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

            '-c:v', vencoder,
            # GOP（关键帧间隔）自动设置：gop_multiplier = N 时 -g = round(源帧率 × N)。
            # ⚠️ 2026-10-15 复查发现：合并上游时这个调用点漏了，
            #    导致 gop_multiplier=8 的配置**完全没生效**（方法定义了但没人调）。
            #    放在 -c:v 之后、用户 vencoder_args 之前 —— 这样若用户在
            #    vencoder_args 里自己写了 -g，会覆盖我们的值（符合预期）。
            *self._build_gop_args(video),
            *vencoder_args,
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

        # XML 弹幕先转成 ASS（本程序自录的 .ass 会原样返回，临时文件为 None）
        danmaku, temp_danmaku = self._prepare_danmaku(video.path, danmaku)
        start_time = datetime.now()
        try:
            status, info = self.render_helper(video.path, danmaku, output, **kwargs)

            # ── 硬件编码重试 + 最后才降级软件（2026-10-18 新增）────────────
            # 起因：用户在后台跑双路批量渲染（都占 QSV），DMR 的 hevc_qsv
            # 渲染报 Invalid FrameType:0 / -1094995529 并留下残缺产物。
            # 实测：GPU 空闲时 4 种编码方案（含纯 qsv）全部成功；而且同一晚
            # 23:08 在两个批量进程都在跑的情况下，DMR 的 QSV 渲染又成功了
            # —— 说明这不是"会话数硬上限"，而是**间歇性**的资源争抢。
            #
            # 所以策略是「硬件优先」：
            #   1. 硬件编码失败 → 等 hw_retry_delay 秒后**再用硬件重试**，
            #      最多 hw_retry 次（默认 2 次）—— 间歇性争抢往往重试就过
            #   2. 全部硬件尝试都失败 → 才降级到软件编码（libx265），只降一次
            # 用户明确要求：尽量硬解硬编，实在不行再软编码。
            if (not status and self._is_hw_encoder(self.vencoder)
                    and self.hw_retry > 0):
                for attempt in range(1, self.hw_retry + 1):
                    self.logger.warning(
                        f'硬件编码器 {self.vencoder} 渲染失败（第 {attempt}/'
                        f'{self.hw_retry} 次重试），{self.hw_retry_delay} 秒后'
                        f'再用硬件重试。\n'
                        f'  常见原因：GPU 编码会话被其他程序占用'
                        f'（别的渲染任务、录屏、转码脚本等）。\n'
                        f'  错误尾部: {str(info)[-300:]}')
                    self._remove_quietly(output)
                    time.sleep(self.hw_retry_delay)
                    status, info = self.render_helper(
                        video.path, danmaku, output, **kwargs)
                    if status:
                        self.logger.info(
                            f'硬件编码第 {attempt} 次重试成功（{self.vencoder}）。')
                        break

            # 硬件彻底不行 → 软件编码兜底（只降级一次）
            if (not status and self.fallback_vencoder
                    and self._is_hw_encoder(self.vencoder)
                    and self.fallback_vencoder != self.vencoder):
                self.logger.warning(
                    f'硬件编码器 {self.vencoder} 重试 {self.hw_retry} 次仍失败，'
                    f'降级到软件编码器 {self.fallback_vencoder}。\n'
                    f'  软件编码会明显更慢，建议排查是什么长期占用 GPU。\n'
                    f'  错误尾部: {str(info)[-300:]}')
                # 清掉失败留下的残缺产物，避免 ffmpeg 因为文件已存在而拒绝
                self._remove_quietly(output)
                status, info = self.render_helper(
                    video.path, danmaku, output,
                    vencoder=self.fallback_vencoder,
                    vencoder_args=self.fallback_vencoder_args,
                    **kwargs)
                if status:
                    self.logger.info(
                        f'软件编码降级成功（{self.fallback_vencoder}）。'
                        f'建议排查是什么占用了 GPU，否则每次渲染都要多花一倍时间。')
        finally:
            # 必须等 ffmpeg 渲染结束才能删：subtitles 滤镜是在渲染期间读这个文件的
            self._remove_quietly(temp_danmaku)

        # ⚠️ 保险闸：即使 ffmpeg 报成功，也要校验产物非空。
        # 上游已在 Render/ffmpeg.py 从根因修过（改为读 wait() 退出码，不再靠
        # 日志里有没有 "video:" 猜成功），所以正常情况下这里不会触发。
        # 但 2026-10-05 的事故教训是：0 字节产物一旦被当成品，下游会上传空文件、
        # 并让清理逻辑删掉源视频（不可恢复）。多一道校验成本极低，故保留。
        if status:
            try:
                out_size = os.path.getsize(output) if exists(output) else 0
            except OSError:
                out_size = 0
            if out_size == 0:
                try:
                    if exists(output):
                        os.remove(output)
                except Exception as e:
                    self.logger.warning(f'删除 0 字节产物失败 {output}: {e}')
                return False, (f'渲染产物为 0 字节，已删除（源视频保留）。'
                               f'通常是 ffmpeg 参数错误，ffmpeg 输出尾部:\n'
                               f'{str(info)[-800:]}')

        if status:
            output_info:VideoInfo = copy.deepcopy(video)
            output_info.dtype = 'dm_video'
            output_info.path = output
            output_info.file_id = uuid()
            output_info.size = os.path.getsize(output)
            output_info.ctime = start_time
            output_info.dm_file_id = None
            output_info.src_video_id = video.file_id

            # ── 时长一致性校验（2026-10-18 新增）──────────────────────────
            # 起因：断尾人类 2026-10-18 19:56 的分段，源视频 3791.6 秒、
            # 但渲染产物只有 2027.3 秒（53%）—— 因为源流在中途时间戳损坏，
            # hevc_qsv 遇到坏帧直接放弃（Invalid FrameType:0 / -1094995529）。
            # ffmpeg 退出码非 0 时上游会上报失败，但**产物已经留在磁盘上**，
            # 体积有 270MB，逃过了"0 字节保险闸"，看起来像个正常产物。
            # 严重性：下游会上传这个残缺视频，且清理规则会删掉源视频 ——
            # 那一段录播就永久变成残缺品了。
            #
            # 这里比较"产物时长 vs 源视频时长"，短太多就判定为失败。
            # 阈值取 90%：正常渲染的时长误差在 1% 以内（弹幕不影响时长），
            # 90% 足够宽松，不会误杀正常的结尾裁剪。
            # 任何异常都只记日志、不影响原有判定（fail-open）。
            try:
                # 参考时长优先级：
                #   1) 弹幕最后时间戳 —— 最可靠（FLV 容器时长会虚报，见辅助方法注释）
                #   2) VideoInfo.duration
                #   3) ffprobe 读源文件
                ref_dur = self._danmaku_last_timestamp(danmaku)
                if ref_dur > 0:
                    src_dur = ref_dur
                    ref_src = '弹幕最后时间戳'
                else:
                    src_dur = float(getattr(video, 'duration', 0) or 0)
                    if src_dur <= 0:
                        src_dur = float(FFprobe.get_duration(video.path) or 0)
                    ref_src = '源文件容器时长'
                out_dur = float(FFprobe.get_duration(output) or 0)
                if src_dur > 0 and out_dur > 0:
                    ratio = out_dur / src_dur
                    if ratio < 0.90:
                        try:
                            os.remove(output)
                        except Exception as e:
                            self.logger.warning(f'删除残缺产物失败 {output}: {e}')
                        return False, (
                            f'渲染产物时长异常：{ref_src} {src_dur:.0f} 秒 → 产物仅 '
                            f'{out_dur:.0f} 秒（{ratio*100:.0f}%），已删除（源视频保留）。\n'
                            f'通常是**源视频本身损坏**（录制期间流时间戳错乱），'
                            f'导致编码器中途放弃。ffmpeg 输出尾部:\n'
                            f'{str(info)[-800:]}')
            except Exception as e:
                self.logger.debug(f'时长校验跳过（不影响渲染结果）: {e}')

            return status, output_info
        else:
            return status, info

    def stop(self):
        self.logger.debug('ffmpeg render stop.')
        self.raw_ffmpeg.stop()
