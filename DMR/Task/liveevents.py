import logging
import os
import time
from .baseevents import BaseEvents
from ..utils import *

# 自定义日志级别 PROGRESS(25)：介于 INFO(20) 和 WARNING(30) 之间。
# main.py 里用 --quiet（不带值）时把控制台设成这一级，效果：
#     显示：直播开始 / 渲染完成 / 上传完成 这类关键进度 + 警告错误
#     隐藏：engine 的消息字典、每个任务的"直播已结束"、各种调试细节
# 注意 addLevelName 是幂等的，重复调用无害。
PROGRESS = 25
logging.addLevelName(PROGRESS, 'PROGRESS')


class LiveEvents(BaseEvents):
    def __init__(self, name, config):
        super().__init__(name, config)
        self.state_dict = {}
        self.ended_dict = {}
        self.logger = logging.getLogger(__name__)
        # 开播/下播通知的防抖记录：{ '{kind}:{任务名}': 上次发送时间戳 }
        self._notify_last = {}

    @property
    def event_dict(self):
        return {
            'ready': self.onReady,
            'exit': self.onExit,
            'downloader/livestart': self.defaultEvent, 
            'downloader/livesegment': self.onLiveSegment,
            'downloader/liveend': self.onLiveEnd,
            'downloader/livestop': self.onLiveEnd,
            'render/end': self.onRenderEnd,
            'render/error': self.onTaskError,
            'uploader/end': self.onUploadEnd,
            'uploader/error': self.onTaskError,
            'cleaner/end': self.defaultEvent,
            'cleaner/error': self.defaultEvent,
            'default': self.defaultEvent,
        }
    
    def defaultEvent(self, message:PipeMessage):
        # 走 PROGRESS 级别：直播开始/下播、清理完成等关键事件会在
        # --quiet 模式下显示；而 engine 的消息字典等 DEBUG 内容不显示。
        self.logger.log(PROGRESS, f'{self.name}: {message.msg}')
        # 开播时发手机通知（这是"谁在播"最有价值的时刻 —— 启动通知发在
        # 录制之前，那时必然还没开播，所以"正在录制"只在开播时才准）
        if '直播开始' in str(message.msg):
            self._notify_live('start')

    # ── 开播 / 下播 手机通知 ──────────────────────────────────────
    def _notify_live(self, kind):
        """发开播/下播通知。在后台线程里做，不阻塞事件处理。

        kind: 'start' 开播 / 'end' 下播

        防抖：同一种事件对这个任务 60 秒内只发一次，避免
        （网络抖动导致的）重复开播事件把手机刷爆。
        """
        try:
            now = time.time()
            key = f'{kind}:{self.name}'
            last = self._notify_last.get(key, 0)
            if now - last < 60:
                return
            self._notify_last[key] = now

            import threading as _th

            def _do():
                try:
                    from DMR.notify import send
                    ts = time.strftime('%Y-%m-%d %H:%M:%S')
                    if kind == 'start':
                        title = f'🔴 开播：{self.name}'
                        send(title, [f'主播：{self.name}',
                                     f'时间：{ts}',
                                     '',
                                     '开始录制...'])
                    else:
                        title = f'⚪ 下播：{self.name}'
                        send(title, [f'主播：{self.name}',
                                     f'时间：{ts}'])
                except Exception:
                    pass

            _th.Thread(target=_do, daemon=True).start()
        except Exception:
            pass


    def onTaskError(self, message:PipeMessage):
        """渲染 / 上传失败时的状态收敛（render/error、uploader/error）。

        ⚠️⚠️ 为什么必须收敛状态（2026-10-05 审查发现的活体泄漏）：
            原来 render/error 和 uploader/error 都走 defaultEvent，
            只打一行日志、**完全不动状态**。后果：
              1) wait 里的 request_id 永远留着 → _check_for_clean 的第二道
                 防线（wait 非空不清理）永远挡着 → **源视频永不清理**
              2) dm_video 永久停在 'rendering' → 第三道防线也永远挡着
              3) 该分组永远达不到终态 → _free_state_memory 永不释放 → 内存泄漏
            实盘证据：18 次渲染错误 → 8 个 .mkv 共 1.76GB 永久滞留在磁盘；
            上线至今「视频信息已被释放」出现 0 次。

        修复做法：把失败的 request_id 从 wait 里剔除，把该 vtype 置成 'failed'
        （算终态，允许清理源文件、允许释放分组），然后补一次清理检查，
        免得这个失败的文件要等到下播才被处理。

        注意：error 事件的 `data` 是**错误描述字符串**（不是 dict），
        分组只能靠 request_id 反查 —— 所以这里遍历全部 state_dict。
        """
        self.logger.warning(f'{self.name}: {message.msg}')

        request_id = message.request_id
        ret_msgs = []
        touched_groups = set()

        if request_id is not None:
            for group_id, states in list(self.state_dict.items()):
                for video_state in states:
                    for vtype, info in video_state.items():
                        if request_id not in (info.get('wait') or []):
                            continue
                        info['wait'].remove(request_id)
                        touched_groups.add(group_id)
                        # wait 清空且仍停在"进行中"的状态 → 标 failed（终态）
                        if not info.get('wait') and info.get('status') in (
                                'rendering', 'uploading'):
                            info['status'] = 'failed'
                            self.logger.warning(
                                f'{self.name}: {vtype} 标记为 failed（任务失败，不再等待），'
                                f'文件: {getattr(info.get("file"), "path", "?")}'
                            )

        # 失败的文件也要走一次清理判定，别等到下播
        if self.config['common_event_args'].get('auto_clean'):
            for group_id in touched_groups:
                try:
                    ret_msgs += self._check_for_clean(group_id)
                except Exception as e:
                    self.logger.error(f'{self.name}: 失败文件清理判定出错: {type(e).__name__}: {e}')
        return ret_msgs

    def onReady(self, *args, **kwargs):
        return PipeMessage(
            source=self.name,
            target='downloader',
            event='newtask',
            data={
                'dltype': self.config['download_args']['dltype'],
                'taskname': self.name,
                'config': self.config['download_args'],
            }
        )
    
    def onLiveSegment(self, message:PipeMessage):
        # 分段录制完成属于关键进度（用户在 --quiet 下也想看到）
        self.logger.log(PROGRESS, f'{self.name}: {message.msg}')
        video:VideoInfo = message.data
        video_state = {
            # 'video_id': uuid(8),
            'src_video': {'status': None, 'file': None, 'wait': []},
            'src_video_pre': {'status': None, 'file': None, 'wait': []},
            'dm_video': {'status': None, 'file': None, 'wait': []},
        }
        if self.state_dict.get(video.group_id):
            self.state_dict[video.group_id].append(video_state)
        else:
            self.state_dict[video.group_id] = [video_state]

        ret_msgs = []
        if self.config['common_event_args'].get('auto_transcode'):
            transcode_args = self.config['render_args']['transcode']
            if transcode_args.get('output_name'):
                filename = replace_keywords(transcode_args['output_name'], video, replace_invalid=True) + \
                        f".{transcode_args.get('format','mp4')}"
            else:
                filename = os.path.splitext(os.path.basename(video.path))[0] + \
                        f"（转码后）.{transcode_args.get('format','mp4')}"
            if transcode_args.get('output_dir'):
                output_dir = transcode_args.get('output_dir')
            else:
                output_dir = os.path.dirname(video.path) + '（转码后）'
            output = os.path.join(output_dir, filename)
            transcode_msg = PipeMessage(
                source=self.name,
                target='render',
                event='newtask',
                request_id=uuid(),
                data={
                    'taskname': self.name,
                    'mode': 'transcode',
                    'video': video,
                    'output': output,
                    'args': transcode_args,
                }
            )
            self.state_dict[video.group_id][-1]['src_video_pre'].update({'status': 'ready', 'file': video})
            self.state_dict[video.group_id][-1]['src_video']['status'] = 'rendering'
            self.state_dict[video.group_id][-1]['src_video']['wait'].append(transcode_msg.request_id)
            ret_msgs.append(transcode_msg)
        else:
            self.state_dict[video.group_id][-1]['src_video'].update({'status': 'ready', 'file': video})
        
        if self.config['common_event_args'].get('auto_render'):
            render_args = self.config['render_args']['dmrender']
            if render_args.get('output_name'):
                filename = replace_keywords(render_args['output_name'], video, replace_invalid=True) + \
                        f".{render_args.get('format','mp4')}"
            else:
                filename = os.path.splitext(os.path.basename(video.path))[0] + \
                        f"（弹幕版）.{render_args.get('format','mp4')}"
            if render_args.get('output_dir'):
                output_dir = render_args.get('output_dir')
            else:
                output_dir = os.path.dirname(video.path) + '（弹幕版）'
            output = os.path.join(output_dir, filename)
            render_msg = PipeMessage(
                source=self.name,
                target='render',
                event='newtask',
                request_id=uuid(),
                data={
                    'taskname': self.name,
                    'mode': 'dmrender',
                    'video': video,
                    'output': output,
                    'args': render_args,
                }
            )
            self.state_dict[video.group_id][-1]['dm_video']['status'] = 'rendering'
            self.state_dict[video.group_id][-1]['dm_video']['wait'].append(render_msg.request_id)
            ret_msgs.append(render_msg)

        if self.config['common_event_args'].get('auto_upload'):
            ret_msgs += self._check_for_upload(video.group_id, len(self.state_dict[video.group_id])-1)

        # ⚠️⚠️ 这里**故意不调用** _check_for_clean！
        # 此刻 dm_video 还是 'rendering'、渲染进程正在读原视频。
        # 如果在这里清理，就会边渲染边删掉输入文件 —— 渲染必然失败，
        # 而且原文件已经不可恢复（2026-10-05 真实事故）。
        # 原视频的清理统一交给 onRenderEnd（弹幕版渲染完成）触发。

        return ret_msgs
    
    def onLiveEnd(self, message:PipeMessage):
        # 状态仍然是 INFO（控制台不显示）—— "下播"在控制台不值得占一行，
        # 但手机通知会发（见下方 _notify_live）。
        self.logger.info(f'{self.name}: {message.msg}.')
        self._notify_live('end')
        group_id = message.data
        if group_id is None:
            return
        
        if group_id in self.state_dict:
            self.ended_dict[group_id] = time.time()
        else:
            self.logger.debug(f'No such group:{group_id}.')
        
        ret_msgs = []
        if self.config['common_event_args'].get('auto_upload'):
            upload_msgs = self._check_for_upload(group_id)
            ret_msgs += upload_msgs
            # 命中跳过规则的文件不会产生 onUploadEnd 事件，这里补一次清理检查
            if self.config['common_event_args'].get('auto_clean'):
                ret_msgs += self._check_for_clean(group_id)

        # 本地存档场景（不启用上传）：直播结束时再做一次清理兜底
        # 防止某些分段在渲染完成时因 dm_video 尚未 ready 而未触发清理的情况
        if self.config['common_event_args'].get('auto_clean') \
                and not self.config['common_event_args'].get('auto_upload'):
            clean_msgs = self._check_for_clean(group_id)
            ret_msgs += clean_msgs

        self._free_state_memory()
        
        return ret_msgs
    
    def _get_upload_skip_rule(self) -> dict:
        """读取「高质量大文件跳过上传」规则（配置在 render_args.dmrender.skip_upload_rule）。"""
        try:
            rule = (self.config.get('render_args') or {}).get('dmrender', {}).get('skip_upload_rule')
        except Exception:
            rule = None
        return rule if isinstance(rule, dict) else {}

    def _mark_upload_skipped(self, video_state:dict, vtype:str, info:dict, skip_rule:dict,
                             sample_video=None) -> bool:
        """判断该文件是否命中跳过规则；命中则标记 upload_skipped 并返回 True。

        标记成 upload_skipped（而不是保持 ready）是必须的：
        清理逻辑在 auto_upload 打开时要求状态为 uploaded 才清理，
        如果只是"不提交上传任务"，状态会永远停在 ready，
        导致原视频永远删不掉。upload_skipped 会被当作"该传的都处理完了"。
        """
        if not skip_rule or not skip_rule.get('enabled'):
            return False
        # 已经处理过的不要重复判断，否则会把真实的上传中状态覆盖掉
        if info.get('status') != 'ready':
            return False
        if info.get('upload_skipped'):
            return True

        video = sample_video or info.get('file')
        if video is None:
            return False

        try:
            should_skip, detail = evaluate_upload_skip_rule(video, skip_rule, logger=self.logger)
        except Exception as e:
            self.logger.warning(f'跳过上传规则判断出错，按不跳过处理: {type(e).__name__}: {e}')
            return False

        if not should_skip:
            self.logger.debug(f'{self.name}: {vtype} 不跳过上传（{detail}）')
            return False

        self.logger.info(
            f'{self.name}: {vtype} 命中跳过上传规则（{detail}），'
            f'不上传（B站和网盘都跳过）。文件: {getattr(video, "path", "?")}'
        )
        info['upload_skipped'] = True
        info['status'] = 'upload_skipped'
        return True

    def _check_for_upload(self, group_id:str, _idx:int=None):
        ret_msgs = []
        if not self.state_dict.get(group_id):
            return ret_msgs
        
        upload_args = self.config['upload_args']
        skip_rule = self._get_upload_skip_rule()
        for idx, video_state in enumerate(self.state_dict[group_id]):
            if _idx is not None and idx != _idx:
                continue
            for vtype, info in video_state.items():
                if info['status'] != 'ready':
                    continue
                # 「高质量大文件跳过上传」规则：命中就整组跳过（B站和网盘都不传），
                # 并把状态标成 upload_skipped，让清理流程知道"这个文件不用等上传了"
                if self._mark_upload_skipped(video_state, vtype, info, skip_rule):
                    continue
                for upload_file_types, upload_arg in upload_args.items():
                    # 判断当前视频是否需要上传
                    if vtype in upload_file_types.split('+'):
                        for upid, arg in enumerate(upload_arg):
                            # 实时上传
                            if not arg.get('realtime'):
                                continue
                            if info['file'].duration < arg.get('min_length', 0):
                                self.logger.info(f'视频{info["file"].path}时长为{info["file"].duration}s，设置{arg.get("min_length", 0)}s，跳过上传.')
                                continue
                            upload_group_id = info['file'].upload_group_id if hasattr(info['file'], 'upload_group_id') else group_id
                            upload_msg = PipeMessage(
                                source=self.name,
                                target='uploader',
                                event='newtask',
                                request_id=uuid(),
                                data={
                                    'taskname': self.name,
                                    'files': [info['file']],
                                    'engine': arg['engine'],
                                    'stateless': False,
                                    'upload_group': upload_group_id+'_'+upload_file_types+'_'+str(upid),
                                    'args': arg,
                                }
                            )
                            self.state_dict[group_id][idx][vtype]['status'] = 'uploading'
                            self.state_dict[group_id][idx][vtype]['wait'].append(upload_msg.request_id)
                            ret_msgs.append(upload_msg)
        
        # 如果当前视频组已经被标记结束，检查是否有视频组完全准备好上传（用于非实时上传）
        if group_id in self.ended_dict:
            # 遍历所有视频类型
            video_types = list(self.state_dict[group_id][-1].keys())
            for vtype in video_types:
                # 检查是否全部准备上传
                videos = []
                for idx, video_state in enumerate(self.state_dict[group_id]):
                    if video_state[vtype]['status'] == 'ready':
                        videos.append(video_state[vtype]['file'])
                    else:
                        videos = []
                        break
                if not videos:
                    continue

                # 非实时上传同样先过一遍跳过规则（用第一个分段的文件判断）
                if self._mark_upload_skipped(self.state_dict[group_id][-1], vtype,
                                             self.state_dict[group_id][-1][vtype], skip_rule,
                                             sample_video=videos[0]):
                    for idx, _ in enumerate(self.state_dict[group_id]):
                        self.state_dict[group_id][idx][vtype]['status'] = 'upload_skipped'
                    continue

                # 判断当前视频是否需要上传
                for upload_file_types, upload_arg in upload_args.items():
                    if vtype in upload_file_types.split('+'):
                        for upid, arg in enumerate(upload_arg):
                            # 此处只做非实时上传
                            if arg.get('realtime'):
                                continue
                            up_videos = [video for video in videos if video.duration >= arg.get('min_length', 0)]
                            # 全部视频都短于 min_length 时必须跳过，否则下面 up_videos[0] 会抛 IndexError，
                            # 整个上传流程会中断（原版就有这个隐患）
                            if not up_videos:
                                self.logger.info(
                                    f'视频组 {group_id} 的 {vtype} 全部短于 {arg.get("min_length", 0)}s，跳过上传.'
                                )
                                continue
                            upload_group_id = up_videos[0].upload_group_id if hasattr(up_videos[0], 'upload_group_id') else group_id
                            upload_msg = PipeMessage(
                                source=self.name,
                                target='uploader',
                                event='newtask',
                                request_id=uuid(),
                                data={
                                    'taskname': self.name,
                                    'files': up_videos,
                                    'engine': arg['engine'],
                                    'stateless': True,
                                    'upload_group': upload_group_id+'_'+upload_file_types+'_'+str(upid),
                                    'args': arg,
                                }
                            )
                            # 标记状态信息
                            for idx, _ in enumerate(self.state_dict[group_id]):
                                self.state_dict[group_id][idx][vtype]['status'] = 'uploading'
                                self.state_dict[group_id][idx][vtype]['wait'].append(upload_msg.request_id)
                            ret_msgs.append(upload_msg)

        return ret_msgs
    
    def onRenderEnd(self, message:PipeMessage):
        # 渲染完成 = 关键进度
        self.logger.log(PROGRESS, f'{self.name}: {message.msg}.')
        request_id = message.request_id
        video:VideoInfo = message.data.get('output')
        video_states = self.state_dict[video.group_id]
        # 将状态信息中request_id对应的等待移除
        for idx, video_state in enumerate(video_states):
            for vtype, info in video_state.items():
                if request_id in info['wait']:
                    self.state_dict[video.group_id][idx][vtype]['wait'].remove(request_id)
                    if len(self.state_dict[video.group_id][idx][vtype]['wait']) == 0:
                        self.state_dict[video.group_id][idx][vtype]['status'] = 'ready'
                        self.state_dict[video.group_id][idx][vtype]['file'] = video
        
        ret_msgs = []
        # 注意顺序：先提交上传任务，再跑清理。
        # 清理已经和上传解耦（只看文件自己 ready 没有），
        # 所以这里能在 dm_video 渲染完成的**同一时刻**就把原视频删掉，
        # 不必等上传结果。
        if self.config['common_event_args'].get('auto_upload'):
            upload_msgs = self._check_for_upload(video.group_id)
            ret_msgs += upload_msgs

        if self.config['common_event_args'].get('auto_clean'):
            clean_msgs = self._check_for_clean(video.group_id)
            ret_msgs += clean_msgs

        return ret_msgs
    
    def _check_for_clean(self, group_id=None):
        """按 clean_args 清理文件。

        魔改说明（与上传器解耦）：
            原版逻辑是「启用上传时，必须 uploaded 才清理」，也就是
                「上传成功 → 才删原视频」。
            这会导致上传失败时原视频一直堆积。

            现在改成：**清理只看文件自己是否就绪，和上传状态完全无关**。
              - src_video 录制完（或转码完）就 ready  → 立即按规则删除
              - dm_video 渲染完就 ready               → 立即按规则处理（默认留存）
            上传成功或失败都不影响清理。想让弹幕版"上传后才删"，
            就在它的 clean_args 里配 method: delete，配合上传器的行为自己权衡。

            状态说明：处理过的文件会被标成 'cleaned'，不会重复清理。
        """
        ret_msgs = []
        clean_args = self.config['clean_args']
        if not clean_args:
            return ret_msgs

        # 如果传入了 group_id，只处理指定组；否则处理所有组
        iter_groups = [(group_id, self.state_dict[group_id])] \
            if group_id and group_id in self.state_dict \
            else list(self.state_dict.items())

        for _gid, video_states in iter_groups:
            for idx, video_state in enumerate(video_states):
                for vtype, info in video_state.items():
                    # 解耦后的判定：只要这个文件自己已经就绪（录制/渲染完成）就清理。
                    #   ready          = 就绪，等上传（或不需要上传）
                    #   upload_skipped = 命中跳过上传规则，同样算就绪
                    #   failed         = 渲染/上传失败（onTaskError 标的终态）。
                    #                    也必须允许清理，否则失败的文件会永远滞留
                    #                    —— 2026-10-05 实测 8 个 .mkv/1.76GB 就是这么积的。
                    # 注意必须把 upload_skipped 也认作可清理，否则命中跳过规则的文件
                    # 会停在 upload_skipped 状态，**永远清理不掉**（原视频会一直堆积）。
                    if info['status'] not in ('ready', 'upload_skipped', 'failed'):
                        continue

                    # ⚠️⚠️ 第二道保护：只要这个文件还有没跑完的异步任务，就先不动它。
                    # wait 非空 = 有 render/upload 任务在排队或执行中，
                    # 这时候删文件可能正好删掉别人正在读的输入（2026-10-05 事故）。
                    if info.get('wait'):
                        self.logger.debug(
                            f'{self.name}: {vtype} 暂不清理 —— 还有 {len(info["wait"])} 个任务未完成'
                        )
                        continue

                    # ⚠️⚠️ 第三道保护：原视频 / 转码前文件是"下游任务的输入"，
                    # 只要下游还在**读取**它，就绝对不能删 —— 否则会边渲染边删输入，
                    # 渲染必然失败且原文件救不回来（2026-10-05 事故根因）。
                    #   src_video      的读取者 = dm_video（弹幕版渲染）
                    #   src_video_pre  的读取者 = src_video（转码）
                    # 注意只挡 'rendering'，**不挡 'uploading'**：
                    #   上传是在读取 dm_video（另一个文件），不影响原视频，
                    #   而且 _check_for_upload 只是把任务投递出去就返回了、不会等结果。
                    #   挡 uploading 会导致原视频要等上传完成才删，违背"渲染完立即删"的要求。
                    if vtype in ('src_video', 'src_video_pre'):
                        consumers = ('dm_video',) if vtype == 'src_video' else ('src_video',)
                        still_reading = [
                            c for c in consumers
                            if c in video_state
                            and video_state[c].get('status') == 'rendering'
                        ]
                        if still_reading:
                            self.logger.debug(
                                f'{self.name}: {vtype} 暂不清理 —— 下游 {still_reading} 正在读取它'
                            )
                            continue

                    file_handled = False
                    for clean_file_types, clean_arg in clean_args.items():
                        # 判断当前视频类型是否需要清理
                        if vtype not in clean_file_types.split('+') and clean_file_types != 'all':
                            continue

                        # 兼容两种 YAML 写法：
                        #   列表式（推荐）: src_video: [{method: delete, delay: 0}, ...]
                        #   对象式（简写）  : src_video: {method: delete, delay: 0}
                        if isinstance(clean_arg, list):
                            arg_iter = clean_arg
                        elif isinstance(clean_arg, dict):
                            arg_iter = [clean_arg]
                        else:
                            # ⚠️ 配置写错了（例如 `src_video:` 后面留空 → None）。
                            # 原来这里静默 continue，但 file_handled 已经在上面被置 True，
                            # 结果状态被标成 'cleaned' 却没有派发任何清理任务
                            # → 文件永久留盘、状态却显示已处理、线索全失（2026-10-05 审查发现）。
                            # 现在：明确报警，并且**不置 file_handled**，让状态保持可重试。
                            self.logger.error(
                                f'{self.name}: clean_args 里 {clean_file_types} 的值类型不对'
                                f'（{type(clean_arg).__name__}），应为 list 或 dict。'
                                f'该规则被忽略，文件不会被清理。'
                            )
                            continue

                        # 确认真的要派发清理任务了，才置 file_handled
                        file_handled = True

                        for arg in arg_iter:
                            files = [info['file']]
                            # 判断是否需要连带清理源文件（dm_video → src_video + 弹幕）
                            # ⚠️ 一律用 .get() 取值：video_state 未必含全部 vtype
                            # （不同 dltype/转码配置下结构不同），直接下标会 KeyError，
                            # 而 KeyError 会冒泡打断整批清理、且已执行的副作用无法回滚
                            # —— 那些文件此后永不清理（2026-10-05 审查发现的 M7/L8）。
                            src_info = video_state.get('src_video') or {}
                            if vtype == 'dm_video' and arg.get('w_srcfile', False) == True \
                                    and src_info.get('file') is not None \
                                    and src_info.get('status') != 'cleaned':
                                files.append(src_info['file'])
                                src_info['status'] = 'cleaned'
                            # 判断是否需要连带清理转码前源文件
                            srcpre_info = video_state.get('src_video_pre') or {}
                            if vtype == 'src_video' and arg.get('w_srcpre', True) == True \
                                    and srcpre_info.get('file') is not None \
                                    and srcpre_info.get('status') != 'cleaned':
                                files.append(srcpre_info['file'])
                                srcpre_info['status'] = 'cleaned'

                            # ⚠️ method/delay 缺键会让整批清理中断，这里单独兜住
                            try:
                                method = arg['method']
                                delay = arg['delay']
                            except KeyError as e:
                                self.logger.error(
                                    f'{self.name}: clean_args 规则缺少 {e}，该规则被跳过。'
                                    f'规则内容: {arg}'
                                )
                                continue

                            clean_msg = PipeMessage(
                                source=self.name,
                                target='cleaner',
                                event='newtask',
                                request_id=uuid(),
                                data={
                                    'taskname': self.name,
                                    'files': files,
                                    'method': method,
                                    'delay': delay,
                                    'args': arg,
                                }
                            )
                            ret_msgs.append(clean_msg)

                    if file_handled:
                        video_state[vtype]['status'] = 'cleaned'

        return ret_msgs
    
    def _free_state_memory(self):
        """释放已处理完的视频组状态（只影响内存，和文件清理无关）。

        终态判定**按 vtype 分别算**（2026-10-05 修复）：

        原来是用一个全局 final_status 要求所有 vtype 都达到它，这在
        「clean_args 只配了 src_video、没配 dm_video」时**永远不可能成立**：
            src_video → cleaned（有清理规则，是终态）
            dm_video  → 永远停在 ready（没有清理规则，到不了 cleaned）
        → need_free 永远 False → **分组永不释放**。
        实盘证据：上线至今「视频信息已被释放」出现 0 次、「处理超时」0 次。

        现在的规则：每个 vtype 看它**自己**能到达的终态：
            有对应的 clean_args 规则 → 终态是 cleaned
            没有规则                 → 终态是 uploaded / upload_skipped / ready
        另外 'failed'（渲染/上传失败）一律算终态，否则失败的分组会永久占内存。
        """
        auto_upload = bool(self.config['common_event_args'].get('auto_upload'))
        auto_clean = bool(self.config['common_event_args'].get('auto_clean'))
        clean_args = self.config.get('clean_args') or {}

        def terminal_statuses(vtype):
            """返回该 vtype 被认为"处理完了"的状态集合。"""
            # 失败是终态（onTaskError 标的）——不释放就永远占内存
            term = {'failed', 'cleaned', None}
            if not auto_clean:
                # 没开清理：上传完成（或本来就 ready）就算完了
                term |= {'uploaded', 'upload_skipped', 'ready'}
                return term
            # 开了清理：看这个 vtype 有没有生效的清理规则
            has_rule = False
            for clean_file_types, clean_arg in clean_args.items():
                if clean_file_types == 'all' or vtype in clean_file_types.split('+'):
                    if isinstance(clean_arg, (list, dict)):
                        has_rule = True
                        break
            if has_rule:
                term.add('cleaned')
            else:
                # 没有清理规则的 vtype（例如 dm_video 默认留存）
                term |= {'uploaded', 'upload_skipped', 'ready'}
            return term

        for group_id in list(self.ended_dict.keys()):
            need_free = True
            for idx, video_state in enumerate(self.state_dict[group_id]):
                for vtype, info in video_state.items():
                    if info.get('wait'):
                        need_free = False
                        break
                    if info['status'] not in terminal_statuses(vtype):
                        need_free = False
                        break
                if not need_free:
                    break
            if need_free:
                self.logger.debug(f'视频组{group_id}处理完成，视频信息已被释放.')
                self.ended_dict.pop(group_id)
                self.state_dict.pop(group_id)

        for group_id in list(self.ended_dict.keys()):
            if time.time() - self.ended_dict[group_id] > 72*3600:
                self.logger.debug(f'视频组{group_id}处理超时，视频信息将被释放.')
                self.ended_dict.pop(group_id)
                self.state_dict.pop(group_id)

    def onUploadEnd(self, message:PipeMessage):
        # 上传完成 = 关键进度
        self.logger.log(PROGRESS, f'{self.name}: {message.msg}.')
        request_id = message.request_id
        # 将状态信息中request_id对应的等待移除
        for group_id, video_states in self.state_dict.items():
            for idx, video_state in enumerate(video_states):
                for vtype, info in video_state.items():
                    if request_id in info['wait']:
                        self.state_dict[group_id][idx][vtype]['wait'].remove(request_id)
                        if len(self.state_dict[group_id][idx][vtype]['wait']) == 0:
                            self.state_dict[group_id][idx][vtype]['status'] = 'uploaded'
        
        ret_msgs = []
        if self.config['common_event_args'].get('auto_clean'):
            clean_msgs = self._check_for_clean()
            ret_msgs += clean_msgs
        
        return ret_msgs

    def onExit(self, *args, **kwargs) -> None:
        self.logger.info(f'{self.name}: 任务结束.')
        self.state_dict.clear()
        self.ended_dict.clear()
        return PipeMessage(
            source=self.name,
            target='downloader',
            event='stoptask',
            data=self.name,
        )
