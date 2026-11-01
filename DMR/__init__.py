import logging
import os
import shutil
import threading
import json
import time
import logging

from .engine import DMREngine
from .Config import Config
from .utils import filename_to_taskname
from .state import (
    RecoveryConfig,
    RecoveryManager,
    StateConsistencyError,
    StateRepository,
)


class DanmakuRepo():
    def __init__(self, config:Config, **kwargs) -> None:
        self.logger = logging.getLogger('DMR')
        self.config = config
        self.kwargs = kwargs
        self.stoped = True
        self.engine_args = self.config.get_config('dmr_engine_args')
        self.engine = DMREngine()

        # 状态持久化与启动对账（P1）。任何失败都不阻止录制本身。
        self.state_db_path = self._resolve_state_db_path()
        self.state_repo = None
        self.recovery_report = None
        #: 对账器实例（启动后期用它收集待恢复产物，避免重复对账）
        self.recovery_manager = None
        self._init_state()

    def _resolve_state_db_path(self) -> str:
        """状态库位置。

        **刻意固定为单一全局路径**：任务配置在任务被删除后会被遗忘，若按任务名
        为每个任务分配独立库文件，迁移配置目录或重命名任务都会静默丢失状态。
        代价是"同一状态库只能服务同一批任务"，由 :meth:`_init_state` 显式校验。
        """
        state_args = self.config.get_config('state') or {}
        return str(state_args.get('db_path')
                   or os.path.join('logs', 'dmr_state.db'))

    def _init_state(self) -> None:
        """打开状态库、校验任务集一致性、执行启动对账。"""
        try:
            repo = StateRepository(self.state_db_path).open()
            self.state_repo = repo
            self.logger.debug(
                f'状态库已打开：{self.state_db_path} '
                f'(schema v{repo.schema_version})'
            )

            self._check_task_set_consistency()

            recovery_config = RecoveryConfig.from_mapping(
                self.config.get_config('recovery'))
            # 保留 manager 实例：启动后期还要用它收集"待恢复产物"（不重新对账）
            self.recovery_manager = RecoveryManager(repo, recovery_config)
            self.recovery_report = self.recovery_manager.reconcile()
            self.logger.info(self.recovery_report.summary())

        except StateConsistencyError:
            # 一致性校验是安全阀，必须让程序终止 —— 不能降级为"无持久化继续跑"
            self._close_state()
            raise
        except Exception as e:
            self._close_state()
            self.logger.error(
                f'状态持久化初始化失败，本次运行将不会保存/恢复进度：{e}'
            )
            self.logger.exception(e)

    def _close_state(self) -> None:
        """关掉状态库并清空引用（用于初始化失败/停止时）。"""
        if self.state_repo is not None:
            try:
                self.state_repo.close()
            except Exception:
                pass
            self.state_repo = None

    def _check_task_set_consistency(self) -> None:
        """状态库与当前任务集不一致时的处置。

        状态库是**单一全局库**，靠 ``taskname`` 区分任务。任务配置放在
        ``configs/*.yml``（会被 ``.gitignore`` 忽略），用户经常把主播配置挪进
        ``configs/temp/`` 停用 —— 此时旧任务就从当前配置里"消失"了。

        历史行为是**拒绝启动**，防止配置目录指错时误删历史状态。但实测
        （2026-10-23）这个惩罚过重：停用主播的产物往往还有 ``src_video`` 停在
        ``recorded``（48 小时后悔期内），不属于终态，于是自动清理不认它 →
        拒绝启动 → 守护循环每 10 秒重拉 → 崩溃循环刷日志。
        而"该录的没录起来"远比"库里留几行用不到的状态"严重。

        现行策略：
          * 配置里一个任务都没有          → 仍然拒绝启动（基本是 config_path 指错）
          * 孤儿任务产物**全是终态**       → 自动清理历史并继续
          * 其余（有未终态产物的孤儿任务） → **默认隔离放行**，只记 warning；
            历史行保留，配置挪回 configs/ 即可继续用。已核实没有任何后台任务
            会回收这些行（purge_task 只有启动自动清理和
            tools/purge_task_state.py 两处调用），所以留着不会丢东西。
          * ``state.strict_consistency: true`` → 恢复旧的"拒绝启动"行为。
        """
        if self.state_repo is None:
            return
        known_tasks = {s.taskname for s in self.state_repo.list_sessions()}
        current_tasks = set(self.config.get_replaytasks())
        missing = known_tasks - current_tasks
        if not missing:
            return

        if not current_tasks:
            raise StateConsistencyError(
                f'状态库 {self.state_db_path} 中存在任务 {sorted(missing)} 的记录，'
                '但当前配置未加载任何任务。请检查 --config 指向的全局配置与其中的 '
                'dmr_engine_args.config_path 是否正确。'
            )

        # ── 2026-10-19：孤儿任务若产物全部已终态，自动清理并继续启动 ──
        # 起因：临时测试任务验证完删掉配置后，库里残留的已完成记录
        # 让程序拒绝启动并进入 12 秒一次的崩溃循环，只能手动删库 ——
        # 那会连带把正常任务的历史一并丢掉，惩罚过重。
        try:
            from .state.enums import TERMINAL_ARTIFACT_STATES
            purged = []
            for _tn in sorted(missing):
                _sids = [s.session_id for s in self.state_repo.list_sessions()
                         if s.taskname == _tn]
                _states = []
                for _sid in _sids:
                    _states += [a.state for a in
                                self.state_repo.list_artifacts(session_id=_sid)]
                _non_terminal = [st for st in _states
                                 if st not in TERMINAL_ARTIFACT_STATES]
                if _non_terminal:
                    continue      # 有未完成的，交给下面报错
                self.state_repo.purge_task(_tn)
                purged.append(_tn)
            if purged:
                self.logger.warning(
                    f'状态库里的孤儿任务 {purged} 产物已全部终态，'
                    f'已自动清理它们的历史记录（不影响其它任务）。')
                missing = missing - set(purged)
                if not missing:
                    return
        except Exception as e:
            self.logger.debug(f'孤儿任务自动清理跳过（不影响启动）: '
                              f'{type(e).__name__}: {e}')

        # ── 2026-10-23：从"拒绝启动"改为"隔离并继续" ──────────────────
        # 用户经常把主播配置挪进 configs/temp/ 停用；这些任务的产物往往还有
        # src_video 停在 recorded（48 小时后悔期内），上面的自动清理不认它，
        # 于是旧逻辑直接拒绝启动 → 守护循环 10 秒重拉 → 崩溃循环刷日志。
        # 而"该录的没录起来"才是最大的隐患，远比"库里留几行用不到的状态"严重。
        # 安全性：没有任何后台任务会回收这些行（purge_task 只有启动自动清理和
        # tools/purge_task_state.py 两处调用），留着不会丢东西；把配置挪回
        # configs/ 就能继续用这些历史。确要认真时可打开 strict_consistency。
        from .state.enums import TERMINAL_ARTIFACT_STATES as _TERMINAL
        strict = bool((self.config.get_config('state') or {})
                      .get('strict_consistency', False))
        if strict:
            raise StateConsistencyError(
                f'状态库 {self.state_db_path} 记录了任务 {sorted(missing)}，'
                f'但当前配置中没有这些任务（当前任务：{sorted(current_tasks)}）。\n'
                '已启用 state.strict_consistency，按严格模式拒绝启动。请任选其一：\n'
                f'  1) 切换回正确的配置目录（dmr_engine_args.config_path）；\n'
                f'  2) 若确定不再需要旧任务，运行 '
                f'tools/purge_task_state.py --apply（比删整个库安全）。'
            )

        detail = []
        for _tn in sorted(missing):
            _sids = [s.session_id for s in self.state_repo.list_sessions()
                     if s.taskname == _tn]
            _alive = 0
            for _sid in _sids:
                _alive += sum(
                    1 for a in self.state_repo.list_artifacts(session_id=_sid)
                    if a.state not in _TERMINAL)
            detail.append(f'{_tn}({len(_sids)} 场, 未终态产物 {_alive} 项)')
        self.logger.warning(
            f'状态库里有 {len(missing)} 个任务不在当前配置中：'
            f'{", ".join(detail)}。已按"停用归档"隔离处理，不影响启动；'
            f'历史记录保留，配置挪回 configs/ 即可继续使用。'
            f'如需彻底清除，运行 tools/purge_task_state.py --apply。'
        )

    def _inject_state_repo(self) -> None:
        """把状态库交给需要它的组件。

        下载器使用模块级引用而非配置项：``download_args`` 属于用户可写的任务配置，
        把运行时对象塞进去会污染配置命名空间并可能被意外序列化。
        """
        if self.state_repo is None:
            return
        try:
            from .Downloader import stream_downloader

            stream_downloader.set_state_repo(self.state_repo)
        except Exception as e:
            self.logger.warning(f'向下载器注入状态库失败，录制进度将不会被保存：{e}')

    def start(self):
        self.stoped = False
        os.makedirs('.temp', exist_ok=True)
        
        self.logger.debug(f'Global Config:\n{json.dumps(self.config.global_config, indent=4, ensure_ascii=False)}')
        self.logger.debug(f'Replay Config:\n{json.dumps(self.config.replay_config, indent=4, ensure_ascii=False)}')
        self._inject_state_repo()
        self.engine.start()
        plugin_enabled = self.config.get_config('dmr_engine_args')['enabled_plugins']
        for plugin_name in plugin_enabled:
            plugin_config = self.config.get_config(plugin_name+'_kernel_args')
            # 下载器登记产物、上传器记录稿件归属，都需要状态库
            if plugin_name in ('uploader', 'downloader') and self.state_repo is not None:
                plugin_config = dict(plugin_config or {})
                plugin_config['state_repo'] = self.state_repo
            self.engine.add_plugin(plugin_name, plugin_config)

        for taskname in self.config.get_replaytasks():
            replay_config = self.config.get_replay_config(taskname)
            self.engine.add_task(taskname, self._with_state_repo(replay_config))

        # 全部任务与插件就绪后，把"已录制/已渲染但未完成处理"的产物重新送回处理链。
        # 必须放在这里：渲染/上传插件此刻已在运行，派发出的消息才有消费者。
        self._resume_pending_artifacts()

        threading.Thread(target=self._monintor, daemon=True).start()

    def _resume_pending_artifacts(self) -> None:
        """重启后继续处理上次没做完的产物（渲染 / 上传 / 清理）。

        只处理 ``RECORDED`` 与 ``RENDERED``：
        - 更早的状态没有可用文件；
        - ``UPLOADED``/``CLEANED`` 等终态绝不重跑（否则会重复投稿）；
        - ``RENDERING``/``UPLOADING`` 已由启动对账降级为 ``RECORDED``，会自然入选。

        由 ``recovery.resume`` 开关控制（默认 ``True``）。
        单条产物恢复失败不影响其它产物，也不影响录制。
        """
        if self.state_repo is None or self.recovery_report is None:
            return
        if self.recovery_manager is None:
            return
        recovery_config = self.config.get_config('recovery') or {}
        if not recovery_config.get('resume', True):
            self.logger.info('recovery.resume 已关闭，本次不恢复未完成的产物。')
            return

        try:
            self.recovery_report.resumable.clear()
            self.recovery_manager.collect_resumable(
                self.recovery_report,
                tasknames=set(self.config.get_replaytasks()),
            )
        except Exception as e:
            self.logger.warning(f'收集待恢复产物失败，本次不恢复：{e}')
            return

        items = self.recovery_report.resumable
        if not items:
            return

        by_task: dict[str, list] = {}
        for item in items:
            by_task.setdefault(item.taskname, []).append(item)

        sent_total = 0
        for taskname, task_items in by_task.items():
            task_entry = self.engine.task_dict.get(taskname)
            if task_entry is None:
                self.logger.warning(
                    f'待恢复产物属于任务 {taskname}，但该任务未加载，已跳过。')
                continue
            try:
                messages = task_entry['class'].event_class.resume_recovered(task_items)
            except Exception as e:
                self.logger.warning(f'恢复任务 {taskname} 的产物失败：{e}')
                self.logger.exception(e)
                continue
            for message in messages or []:
                try:
                    self.engine.pipeSend(message)
                    sent_total += 1
                except Exception as e:
                    self.logger.warning(f'派发恢复消息失败：{e}')

        self.logger.info(
            f'恢复处理：{len(items)} 个未完成产物，已重新派发 {sent_total} 个任务。')

    def _with_state_repo(self, replay_config: dict | None) -> dict | None:
        """把状态库注入任务配置。

        ``LiveEvents`` 通过任务配置读取它，用于镜像渲染/上传/清理进度。
        需要状态库的另两个组件（下载器、上传器）走各自的注入路径。
        这里返回**副本**，避免把运行时对象写回 ``Config`` 持有的任务配置
        （那会让配置看起来可以被序列化，实际不能）。
        """
        if replay_config is None or self.state_repo is None:
            return replay_config
        return {**replay_config, 'state_repo': self.state_repo}

    def check_config_update(self):
        try:
            update_type, update_info = self.config.check_update()
            
            if update_type == 'global':
                # ⚠️ 2026-10-16：原来只是一行 info，会被 33 个任务的输出瞬间冲走，
                #    用户反映"没看到重启提示"。改成醒目的横幅 + 提醒，
                #    并在后续检查里重复最多 3 次（每次间隔由引擎的检查周期决定），
                #    避免重启前就忘了这件事。仍然只在控制台/日志各打一遍，
                #    不会刷屏。
                self._config_update_notices = getattr(
                    self, '_config_update_notices', 0) + 1
                if self._config_update_notices <= 3:
                    _times = (f'（第 {self._config_update_notices} 次提醒）'
                              if self._config_update_notices > 1 else '')
                    self.logger.warning(
                        '\n'
                        '  ' + '=' * 58 + '\n'
                        '  ⚠️  全局配置已更新，但**需要重启程序才会生效**！' + _times + '\n'
                        '      改的是: configs/global.yml\n'
                        '      重启方法: 关闭当前程序（或在终端按 Ctrl+C），\n'
                        '                Start_Render.bat 会自动把它拉起来。\n'
                        '  ' + '=' * 58)
            
            elif update_type == 'tasks':
                for config_path in update_info['new']:
                    taskname = filename_to_taskname(config_path)
                    self.logger.info(f'检测到新任务配置文件: {taskname}，正在添加任务...')
                    self.engine.add_task(taskname, self.config.get_replay_config(taskname))
                
                for config_path in update_info['deleted']:
                    taskname = filename_to_taskname(config_path)
                    self.logger.info(f'检测到任务配置文件删除: {taskname}，正在停止任务...')
                    self.engine.del_task(taskname)

                for config_path in update_info['updated']:
                    taskname = filename_to_taskname(config_path)
                    self.logger.info(f'检测到任务配置文件更新: {taskname}，正在重启任务...')
                    
                    self.engine.del_task(taskname)
                    time.sleep(5)
                    new_taskname = filename_to_taskname(config_path)
                    self.engine.add_task(new_taskname, self.config.get_replay_config(new_taskname))

        except Exception as e:
            self.logger.error(f'动态载入配置文件错误:')
            self.logger.exception(e)

    def _monintor(self):
        REFRESH_INTERVAL = 60
        time.sleep(REFRESH_INTERVAL)
        while not self.stoped:
            self.check_config_update()
            # clean temp file
            files = os.listdir('.temp')
            for file in files:
                try:
                    basename = os.path.splitext(os.path.basename(file))[0]
                    expired_time = basename.split('_')[-1]
                    if expired_time.isdigit():
                        expired_time = int(expired_time)
                    else:
                        expired_time = 0
                    # 只清理2024.01.01之后的过期文件，过早的文件认为不是程序创建的不清理
                    if expired_time > 1704038400 and expired_time < int(time.time()):
                        file = os.path.join('.temp', file)
                        if os.path.isfile(file):
                            os.remove(file)
                            self.logger.debug(f'已清理临时文件: {file}')
                        elif os.path.isdir(file):
                            shutil.rmtree(file)
                            self.logger.debug(f'已清理临时文件夹: {file}')
                except Exception as e:
                    self.logger.debug(f'清理临时文件{file}失败: {e}')
            
            time.sleep(REFRESH_INTERVAL)

    def stop(self):
        self.stoped = True
        self.engine.stop()
        if self.state_repo is not None:
            self.state_repo.close()
            self.state_repo = None
