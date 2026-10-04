import os
import glob
import yaml
import logging
import hashlib
from copy import deepcopy
from typing import List
from DMR.utils import filename_to_taskname, merge_dict, ToolsList

# __all__ = ['Config', 'new_config']

class Config():
    _base_config_path = 'DMR/Config/default.yml'

    def __init__(self, global_config_path:str) -> None:
        self.global_config_path = global_config_path
        self.replay_config_path_raw = []
        self.replay_config_paths:List[str] = []
        self.file_hashes = {}
        self.logger = logging.getLogger(__name__)
        
        self._init_config()
        self.check_update()

    def _get_file_hash(self, path):
        try:
            with open(path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception:
            return None

    def _init_config(self):
        with open(self._base_config_path, 'r', encoding='utf-8') as f:
            self._base_config = yaml.safe_load(f)

        self.global_config = deepcopy(self._base_config)
        self.replay_config = {}

        with open(self.global_config_path, 'r', encoding='utf-8') as f:
            _global_config = yaml.safe_load(f)
        self.file_hashes[self.global_config_path] = self._get_file_hash(self.global_config_path)
        
        self.global_config = merge_dict(self.global_config, _global_config)

        for toolname, path in self.global_config.get('executable_tools_path',{}).items():
            if not path:
                ToolsList.get(toolname, auto_install=True)
            else:
                ToolsList.set(toolname, path)

        dmr_engine_args = self.global_config.get('dmr_engine_args', {})
        self.replay_config_path_raw = dmr_engine_args.get('config_path', ['./configs'])
        if isinstance(self.replay_config_path_raw, str):
            self.replay_config_path_raw = [self.replay_config_path_raw]

    def add_task_config(self, config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                _replay_config = yaml.safe_load(f)
            
            current_hash = self._get_file_hash(config_path)
            self.file_hashes[config_path] = current_hash
            
            taskname = filename_to_taskname(config_path)
            replay_config = {}
            
            common_args = _replay_config.get('common_event_args')
            if not common_args: return None
            replay_config['common_event_args'] = deepcopy(common_args)
            
            global_download_args = self.global_config['download_args']
            dltype = _replay_config.get('download_args', {}).get('dltype', 'live')
            replay_config['download_args'] = deepcopy(global_download_args.get(dltype, {}))
            if _replay_config.get('download_args'):
                replay_config['download_args'] = merge_dict(replay_config['download_args'], _replay_config['download_args'])

            if common_args.get('auto_render') or common_args.get('auto_transcode'):
                replay_config['render_args'] = deepcopy(self.global_config['render_args'])
                if _replay_config.get('render_args'):
                    replay_config['render_args'] = merge_dict(replay_config['render_args'], _replay_config['render_args'])

            if common_args.get('auto_upload'):
                global_upload_args = self.global_config['upload_args']
                replay_config['upload_args'] = {}

                # 任务 yml 里没写 upload_args 时，用 global.yml 的「任务级默认」，
                # 省得给每个任务都抄一遍。写法参考 clean_args_task_default。
                # 任务写了就以任务为准（不再合并，避免两个来源混在一起难以排查）。
                task_upload_args = _replay_config.get('upload_args') \
                    if isinstance(_replay_config.get('upload_args'), dict) else None
                if not task_upload_args:
                    task_upload_args = self.global_config.get('upload_args_task_default') \
                        if isinstance(self.global_config.get('upload_args_task_default'), dict) \
                        else None
                if not task_upload_args:
                    self.logger.warning(
                        f'{filename_to_taskname(config_path)}: auto_upload 已开启，'
                        f'但任务没写 upload_args、global.yml 也没有 upload_args_task_default，'
                        f'本次不会有任何上传。'
                    )

                if task_upload_args:
                    for upload_file_types, upload_args in task_upload_args.items():
                        if isinstance(upload_args, dict):
                            upload_args = [upload_args]
                        replay_config['upload_args'][upload_file_types] = []
                        for upload_arg in upload_args:
                            # target 决定这份上传继承 global.yml 里的哪一套默认参数
                            #   target: bilibili → 继承 upload_args.bilibili
                            #   target: rclone   → 继承 upload_args.rclone
                            # 没写 target 时按 engine 猜一个，方便只写 engine 的简写
                            target = upload_arg.get('target')
                            if not target:
                                engine = upload_arg.get('engine')
                                for name, cfg_default in global_upload_args.items():
                                    if name == 'upload_args_task_default':
                                        continue
                                    if isinstance(cfg_default, dict) and cfg_default.get('engine') == engine:
                                        target = name
                                        break
                                else:
                                    target = 'bilibili'
                            if not global_upload_args.get(target):
                                # 没配置这个上传目标（比如 global.yml 里删掉了 bilibili 段）
                                # 就跳过这一份，而不是报错中断任务
                                self.logger.warning(
                                    f'{filename_to_taskname(config_path)}: 上传目标 {target} 未在 '
                                    f'global.yml 的 upload_args 中配置，跳过这一份上传。'
                                )
                                continue
                            upload_config = deepcopy(global_upload_args[target])
                            upload_config.update(upload_arg)
                            replay_config['upload_args'][upload_file_types].append(upload_config)

            if common_args.get('auto_clean'):
                global_clean_args = self.global_config.get('clean_args', {}) or {}
                replay_config['clean_args'] = {}

                # 任务 yml 中写的 clean_args
                task_clean_args = _replay_config.get('clean_args') \
                    if isinstance(_replay_config.get('clean_args'), dict) else None

                # 如果任务没写 clean_args，使用 global 的「任务级默认规则」
                #   优先级：任务 yml 的 clean_args
                #        → global.clean_args_task_default（如果有）
                #        → 兜底：src_video 立即 delete（本地存档、留弹幕版场景）
                if not task_clean_args:
                    task_clean_args = self.global_config.get('clean_args_task_default') \
                        if isinstance(self.global_config.get('clean_args_task_default'), dict) \
                        else None
                if not task_clean_args:
                    task_clean_args = {'src_video': {'method': 'delete', 'delay': 0}}

                for clean_file_types, clean_args in task_clean_args.items():
                    if isinstance(clean_args, dict):
                        clean_args = [clean_args]
                    replay_config['clean_args'][clean_file_types] = []
                    for clean_arg in clean_args:
                        method = clean_arg.get('method')
                        if not method:
                            continue
                        if not global_clean_args.get(method):
                            raise ValueError(f'不存在可用的清理方法 {method}. 请在 global.yml 的 clean_args 中添加 {method} 作为默认参数模板。')
                        clean_config = deepcopy(global_clean_args[method])
                        clean_config.update(clean_arg)
                        replay_config['clean_args'][clean_file_types].append(clean_config)

            self.replay_config[taskname] = deepcopy(replay_config)
            return taskname
        except Exception as e:
            self.logger.error(f"Error loading config {config_path}:")
            self.logger.exception(e)
            return None

    def check_update(self):
        updated_tasks = []
        new_tasks = []
        deleted_tasks = []
        
        # Check global config
        try:
            current_hash = self._get_file_hash(self.global_config_path)
            if current_hash != self.file_hashes.get(self.global_config_path):
                self.file_hashes[self.global_config_path] = current_hash
                return 'global', None
        except Exception:
            pass

        # get replay configs
        current_files = set()
        for raw_path in self.replay_config_path_raw:
            if os.path.isfile(raw_path):
                current_files.add(raw_path)
            elif os.path.isdir(raw_path):
                config_files = glob.glob(os.path.join(raw_path, 'DMR-**.yml'))
                for f in config_files:
                    current_files.add(f)

        old_files = set(self.replay_config_paths)
        
        for f in current_files - old_files:
            if self.add_task_config(f):
                new_tasks.append(f)
        
        for f in old_files - current_files:
            deleted_tasks.append(f)
            t = filename_to_taskname(f)
            self.replay_config.pop(t, None)
            self.file_hashes.pop(f, None)
            
        for f in current_files & old_files:
            try:
                current_hash = self._get_file_hash(f)
                if current_hash != self.file_hashes.get(f) and self.add_task_config(f):
                    updated_tasks.append(f)
            except Exception:
                pass
        
        if new_tasks or deleted_tasks or updated_tasks:
            self.replay_config_paths = list(current_files)
            return 'tasks', {
                'new': list(new_tasks),
                'deleted': list(deleted_tasks),
                'updated': list(updated_tasks)
            }
        
        return None, None

    def get_config(self, name):
        return self.global_config.get(name)
    
    def get_replay_config(self, taskname):
        return self.replay_config.get(taskname)
    
    def get_replaytasks(self):
        return list(self.replay_config.keys())
