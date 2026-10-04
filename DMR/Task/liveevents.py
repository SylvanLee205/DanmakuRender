import logging
import os
from .baseevents import BaseEvents
from ..utils import *

class LiveEvents(BaseEvents):
    def __init__(self, name, config):
        super().__init__(name, config)
        self.state_dict = {}
        self.ended_dict = {}
        self.logger = logging.getLogger(__name__)

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
            'render/error': self.defaultEvent,
            'uploader/end': self.onUploadEnd,
            'uploader/error': self.defaultEvent,
            'cleaner/end': self.defaultEvent,
            'cleaner/error': self.defaultEvent,
            'default': self.defaultEvent,
        }
    
    def defaultEvent(self, message:PipeMessage):
        self.logger.info(f'{self.name}: {message.msg}')

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
        self.logger.info(f'{self.name}: {message.msg}')
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
            # 如果有文件命中「跳过上传」规则，它不会产生 onUploadEnd 事件，
            # 这里补一次清理检查，否则原视频不会被删除
            if self.config['common_event_args'].get('auto_clean'):
                ret_msgs += self._check_for_clean(video.group_id)
                
        return ret_msgs
    
    def onLiveEnd(self, message:PipeMessage):
        self.logger.info(f'{self.name}: {message.msg}.')
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
        self.logger.info(f'{self.name}: {message.msg}.')
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
        if self.config['common_event_args'].get('auto_upload'):
            upload_msgs = self._check_for_upload(video.group_id)
            ret_msgs += upload_msgs

        # 如果启用了自动清理，即使不启用上传，在渲染完成后也尝试触发清理
        # 这样本地存档场景下，渲染完弹幕版后就能立即删除原视频和弹幕文件
        if self.config['common_event_args'].get('auto_clean'):
            clean_msgs = self._check_for_clean(video.group_id)
            ret_msgs += clean_msgs

        return ret_msgs
    
    def _check_for_clean(self, group_id=None):
        ret_msgs = []
        clean_args = self.config['clean_args']
        if not clean_args:
            return ret_msgs

        auto_upload_enabled = self.config['common_event_args'].get('auto_upload', False)

        # 如果传入了 group_id，只处理指定组；否则处理所有组
        iter_groups = [(group_id, self.state_dict[group_id])] \
            if group_id and group_id in self.state_dict \
            else list(self.state_dict.items())

        for _gid, video_states in iter_groups:
            for idx, video_state in enumerate(video_states):
                for vtype, info in video_state.items():
                    # 判断当前状态是否满足清理条件
                    # 启用上传：必须 uploaded 才清理
                    #   upload_skipped = 命中跳过规则，该传的都处理完了，同样可以清理
                    # 不启用上传：ready 就可以清理（本地存档场景）
                    if auto_upload_enabled:
                        if info['status'] not in ('uploaded', 'upload_skipped'):
                            continue
                    else:
                        if info['status'] != 'ready':
                            continue

                    file_handled = False
                    for clean_file_types, clean_arg in clean_args.items():
                        # 判断当前视频类型是否需要清理
                        if vtype not in clean_file_types.split('+') and clean_file_types != 'all':
                            continue

                        file_handled = True

                        # 兼容两种 YAML 写法：
                        #   列表式（推荐）: src_video: [{method: delete, delay: 0}, ...]
                        #   对象式（简写）  : src_video: {method: delete, delay: 0}
                        if isinstance(clean_arg, list):
                            arg_iter = clean_arg
                        elif isinstance(clean_arg, dict):
                            arg_iter = [clean_arg]
                        else:
                            continue

                        for arg in arg_iter:
                            files = [info['file']]
                            # 判断是否需要连带清理源文件（dm_video → src_video + 弹幕）
                            if vtype == 'dm_video' and arg.get('w_srcfile', False) == True \
                                    and video_state['src_video']['file'] is not None \
                                    and video_state['src_video']['status'] != 'cleaned':
                                files.append(video_state['src_video']['file'])
                                video_state['src_video']['status'] = 'cleaned'
                            # 判断是否需要连带清理转码前源文件
                            if vtype == 'src_video' and arg.get('w_srcpre', True) == True \
                                    and video_state['src_video_pre']['file'] is not None \
                                    and video_state['src_video_pre']['status'] != 'cleaned':
                                files.append(video_state['src_video_pre']['file'])
                                video_state['src_video_pre']['status'] = 'cleaned'

                            clean_msg = PipeMessage(
                                source=self.name,
                                target='cleaner',
                                event='newtask',
                                request_id=uuid(),
                                data={
                                    'taskname': self.name,
                                    'files': files,
                                    'method': arg['method'],
                                    'delay': arg['delay'],
                                    'args': arg,
                                }
                            )
                            ret_msgs.append(clean_msg)

                    if file_handled:
                        video_state[vtype]['status'] = 'cleaned'

        return ret_msgs
    
    def _free_state_memory(self):
        final_status = 'ready'
        if self.config['common_event_args'].get('auto_upload'):
            final_status = 'uploaded'
        if self.config['common_event_args'].get('auto_clean'):
            final_status = 'cleaned'
        
        for group_id in list(self.ended_dict.keys()):
            need_free = True
            for idx, video_state in enumerate(self.state_dict[group_id]):
                for vtype, info in video_state.items():
                    # upload_skipped（命中跳过规则）等价于 uploaded，都算这一环处理完了
                    if info['status'] is not None and info['status'] not in (final_status, 'upload_skipped'):
                        need_free = False
                        break
                if not need_free: break
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
        self.logger.info(f'{self.name}: {message.msg}.')
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
