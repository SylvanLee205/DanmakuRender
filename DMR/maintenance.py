"""周期性维护：日志轮转、磁盘水位保护、定时体检、录播索引页。

由 ``DanmakuRepo._monintor`` 每分钟调用一次 ``Maintenance.tick()``，
内部按自己的节奏决定要不要干活（日志 6 小时、磁盘 5 分钟、体检/索引每天一次）。

设计原则
--------
1. **绝不抛异常向上**。维护失败只记 warning，绝不能拖垮录制。
2. **动作可逆或只增不改**。清理只删「已渲染完成」的源视频、只删超期日志。
3. **通知要节流**。同一个问题每天最多提醒一次，否则会刷屏。
4. **配置全部可关**。任何一项不想用，在 global.yml 里设 enabled: false。

配置长这样（global.yml 顶层）：:

    maintenance:
      log_keep_days: 14
      log_max_total_mb: 500
      disk_guard:
        enabled: true
        warn_gb: 120        # 低于此值：记警告
        critical_gb: 60     # 低于此值：立刻清已渲染的旧源视频
        emergency_gb: 20    # 低于此值：同上 + 强烈通知
      doctor:
        enabled: true
        at: '05:00'
      index:
        enabled: true
        at: '06:00'
"""
import json
import os
import shutil
import time

from .paths import p, data_root, TEMP

__all__ = ('Maintenance', 'is_disk_emergency')

#: 中间态 / 临时文件名特征，永远不删
_SKIP_SUFFIX = ('.part', '.tmp', '.ass', '.xml', '.converting', '.json', '.db')
#: 正在写入的录制分段前缀
_RECORDING_PREFIX = '[正在录制]'
#: 视为「源视频」的扩展名
_SOURCE_EXT = ('.mp4', '.mkv', '.flv', '.ts', '.mov')
#: 视为「已渲染产物」的特征
_DM_MARK = '（弹幕版）'

#: 磁盘是否处于 emergency。模块级共享状态 —— 下载器在开始新一轮录制前查它。
#: 为什么用模块级而不是传参：下载器是插件，拿不到 DanmakuRepo 主对象的引用，
#: 硬塞进去要改一大串构造签名，不值当。
_DISK_EMERGENCY = False


def is_disk_emergency() -> bool:
    """磁盘是否已到 emergency 水位（供下载器判断"该不该开新任务"）。"""
    return _DISK_EMERGENCY


def _set_emergency(flag: bool) -> None:
    global _DISK_EMERGENCY
    _DISK_EMERGENCY = bool(flag)


class Maintenance:
    """所有周期性维护动作的入口。"""

    #: 日志清理间隔（秒）
    LOG_INTERVAL = 6 * 3600
    #: 磁盘检查间隔（秒）
    DISK_INTERVAL = 300

    def __init__(self, config, logger, notify=None):
        self.logger = logger
        self.notify = notify
        self.cfg = (config or {}).get('maintenance') or {}
        self.state_path = os.path.join(TEMP, 'maintenance_state.json')
        self.state = self._load_state()

        self._last_log = 0.0
        self._last_disk = 0.0
        self._disk_level = None          # None / 'warn' / 'critical' / 'emergency'
        #: 处于 emergency 时置 True，下载器可据此跳过新任务
        self.paused_for_disk = False

    # ────────────────────────── 状态持久化 ──────────────────────────
    def _load_state(self) -> dict:
        try:
            with open(self.state_path, encoding='utf-8') as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _save_state(self) -> None:
        try:
            os.makedirs(TEMP, exist_ok=True)
            with open(self.state_path, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.debug(f'维护状态保存失败: {e}')

    def _once_per_day(self, key: str) -> bool:
        """同一件事每天只做一次。返回 True 表示"今天还没做过"。"""
        today = time.strftime('%Y-%m-%d')
        if self.state.get(key) == today:
            return False
        self.state[key] = today
        self._save_state()
        return True

    def _at_time(self, key: str, hhmm: str) -> bool:
        """到了每天的 HH:MM 且今天还没跑过。"""
        try:
            h, m = (int(x) for x in str(hhmm).split(':'))
        except Exception:
            h, m = 5, 0
        now = time.localtime()
        if (now.tm_hour, now.tm_min) < (h, m):
            return False
        return self._once_per_day(key)

    def _say(self, lines):
        try:
            if self.notify:
                self.notify(lines)
        except Exception as e:
            self.logger.debug(f'维护通知发送失败: {e}')

    # ────────────────────────── 主入口 ──────────────────────────
    def tick(self) -> None:
        now = time.time()
        if now - self._last_log > self.LOG_INTERVAL:
            self._last_log = now
            self._safe(self.clean_logs)
        if now - self._last_disk > self.DISK_INTERVAL:
            self._last_disk = now
            self._safe(self.check_disk)

        doc = self.cfg.get('doctor') or {}
        if doc.get('enabled', True) and self._at_time('doctor_date', doc.get('at', '05:00')):
            self._safe(self.run_doctor)

        idx = self.cfg.get('index') or {}
        if idx.get('enabled', True) and self._at_time('index_date', idx.get('at', '06:00')):
            self._safe(self.build_index)

    def _safe(self, fn) -> None:
        try:
            fn()
        except Exception as e:
            self.logger.warning(f'维护任务 {getattr(fn, "__name__", fn)} 失败: {e}')

    # ────────────────────────── 1. 日志轮转 ──────────────────────────
    def clean_logs(self) -> None:
        """按天数 + 总大小双阈值清理 logs/ 下的日志。

        为什么需要：main.py 用 TimedRotatingFileHandler(backupCount=3)，
        但每次重启都会新建一个带序号的文件（DMR-20261102(1).log …），
        那个 backupCount 管不到它们 —— 实测攒了 77 个文件 36 MB，
        而且只增不减。
        """
        logdir = p('logs')
        if not os.path.isdir(logdir):
            return
        keep_days = int(self.cfg.get('log_keep_days', 14))
        max_mb = float(self.cfg.get('log_max_total_mb', 500))

        files = []
        for name in os.listdir(logdir):
            if not name.lower().endswith('.log'):
                continue
            path = os.path.join(logdir, name)
            if not os.path.isfile(path):
                continue
            try:
                st = os.stat(path)
            except OSError:
                continue
            files.append((path, st.st_size, st.st_mtime))

        # ① 按天数删
        cutoff = time.time() - keep_days * 86400
        removed = 0
        for path, size, mtime in list(files):
            if mtime < cutoff:
                try:
                    os.remove(path)
                    removed += 1
                    files.remove((path, size, mtime))
                except OSError:
                    pass

        # ② 按总大小删（从最旧开始，至少保留今天的）
        total = sum(s for _, s, _ in files)
        limit = max_mb * 1024 * 1024
        if total > limit:
            files.sort(key=lambda x: x[2])
            today = time.strftime('%Y%m%d')
            for path, size, mtime in files:
                if total <= limit:
                    break
                if today in os.path.basename(path):
                    continue          # 今天的日志永远保留
                try:
                    os.remove(path)
                    total -= size
                    removed += 1
                except OSError:
                    pass

        if removed:
            self.logger.info('日志轮转：删除 %d 个旧日志，现存 %.1f MB',
                             removed, total / 1024 / 1024)

    # ────────────────────────── 2. 磁盘水位 ──────────────────────────
    def check_disk(self) -> None:
        guard = self.cfg.get('disk_guard') or {}
        if not guard.get('enabled', True):
            return
        root = data_root()
        try:
            free_gb = shutil.disk_usage(root).free / 1024 ** 3
        except OSError as e:
            self.logger.warning(f'磁盘检查失败（{root}）: {e}')
            return

        warn = float(guard.get('warn_gb', 120))
        crit = float(guard.get('critical_gb', 60))
        emerg = float(guard.get('emergency_gb', 20))

        if free_gb >= warn:
            if self._disk_level not in (None, 'ok'):
                self.logger.info('磁盘空间已恢复：剩余 %.1f GB', free_gb)
            self._disk_level = 'ok'
            self.paused_for_disk = False
            _set_emergency(False)
            return

        level = 'emergency' if free_gb < emerg else ('critical' if free_gb < crit else 'warn')
        drive = os.path.splitdrive(root)[0] or root
        self._disk_level = level

        if level == 'warn':
            self.logger.warning('磁盘空间偏低：%s 剩余 %.1f GB（警告线 %.0f GB）',
                                drive, free_gb, warn)
            if self._once_per_day('disk_warn'):
                self._say([f'⚠️ 磁盘空间偏低',
                           f'盘符：{drive}',
                           f'剩余：{free_gb:.1f} GB（低于 {warn:.0f} GB）',
                           '',
                           '还不会影响录制，但建议尽快清理。'])
            return

        # critical / emergency：立刻清已渲染完成的旧源视频
        freed = self.emergency_clean(max_free_gb=crit if level == 'critical' else warn)
        try:
            free_now = shutil.disk_usage(root).free / 1024 ** 3
        except OSError:
            free_now = free_gb

        head = '🔴 磁盘空间告急' if level == 'emergency' else '🟠 磁盘空间紧张'
        self.logger.warning('%s：%s 剩余 %.1f GB，紧急清理释放 %.1f GB，现剩 %.1f GB',
                            head, drive, free_gb, freed, free_now)
        self.paused_for_disk = (level == 'emergency' and free_now < emerg)
        # emergency 且清理后仍然不够 → 让下载器暂停开新任务（正在录的不受影响）
        _set_emergency(self.paused_for_disk)
        if self.paused_for_disk:
            self.logger.error('磁盘清理后仍低于紧急线，已暂停启动**新**录制任务 '
                              '（正在录制的会继续）。请立刻人工处理磁盘空间。')

        # 同一级别每天只通知一次
        if self._once_per_day(f'disk_{level}'):
            self._say([f'{head}',
                       f'盘符：{drive}',
                       f'剩余：{free_gb:.1f} GB → 清理后 {free_now:.1f} GB',
                       f'已删除 {freed:.1f} GB 已渲染完成的源视频',
                       '',
                       '需要人工介入：' if free_now < crit else '已自动缓解：',
                       '  1) 把「弹幕版」移到别的盘或网盘',
                       '  2) 或设 DMR_DATA_ROOT 指向更大的盘'])

    def emergency_clean(self, max_free_gb: float, logger=None) -> float:
        """删除「已经渲染出弹幕版」的最旧源视频，直到释放到目标水位。

        安全规则（每一条都来自真实事故）：
          * 跳过 ``[正在录制]`` 前缀 —— 那是正在写的文件
          * 跳过 .part/.ass/.xml 等中间产物
          * 必须有同目录的 ``xxx（弹幕版）.mp4`` 才允许删（说明已渲染完）
          * 只删超过 2 小时没动过的（防正在读）
          * 从最旧的开始删，够了就停

        返回释放的 GB 数。
        """
        logger = logger or self.logger
        root = os.path.join(data_root(), '直播回放')
        if not os.path.isdir(root):
            root = os.path.join(p(), '直播回放')
        if not os.path.isdir(root):
            return 0.0

        cands = []
        for dirpath, _dirs, files in os.walk(root):
            names = set(files)
            for name in files:
                if name.startswith(_RECORDING_PREFIX):
                    continue
                # ⚠️ 2026-11-02 血的教训：**弹幕版成品本身也会走到下面那句
                #    "有没有对应的弹幕版"检查里，而且会匹配到自己**，
                #    结果把成品删了。假目录测试时抓到的。
                if _DM_MARK in name:
                    continue
                if name.lower().endswith(_SKIP_SUFFIX):
                    continue
                if not name.lower().endswith(_SOURCE_EXT):
                    continue
                # 必须有对应的弹幕版产物才允许删（说明已经渲染完了）
                # 用「前缀 + 扩展名」精确匹配，不用 startswith(stem) ——
                # 后者在 stem 很短时会误匹配到别的文件。
                stem, ext = os.path.splitext(name)
                dm_base = f'{stem}{_DM_MARK}'
                if not any(n.startswith(dm_base) and n[len(dm_base):].startswith('.')
                           for n in names):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                if time.time() - st.st_mtime < 7200:      # 2 小时内不动
                    continue
                cands.append((st.st_mtime, path, st.st_size))

        if not cands:
            logger.warning('磁盘紧张，但找不到「已渲染完成的源视频」可清 —— '
                           '只能人工处理')
            return 0.0

        cands.sort()          # 最旧优先
        freed = 0
        try:
            free_gb = shutil.disk_usage(data_root()).free / 1024 ** 3
        except OSError:
            free_gb = 0
        target = max_free_gb

        for _mtime, path, size in cands:
            if free_gb + freed / 1024 ** 3 >= target:
                break
            try:
                os.remove(path)
                freed += size
                logger.info('磁盘清理：已删源视频 %s（%.1f MB）',
                            os.path.relpath(path, root), size / 1024 / 1024)
            except OSError as e:
                logger.debug(f'删除失败 {path}: {e}')

        return freed / 1024 ** 3

    # ────────────────────────── 3. 定时体检 ──────────────────────────
    def run_doctor(self) -> None:
        """跑一遍体检，**只有严重问题才通知**。"""
        try:
            tools_dir = p('tools')
            import sys
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)
            import doctor
            lines, n_bad, n_warn = doctor.run_checks()
        except Exception as e:
            self.logger.debug(f'体检模块不可用: {e}')
            return

        if n_bad == 0:
            self.logger.info('每日体检通过（%d 项警告）', n_warn)
            return

        problems = [f'· {ln}' for lv, ln, _h in lines if lv == 'BAD']
        self.logger.warning('每日体检发现 %d 项严重问题', n_bad)
        for ln in problems:
            self.logger.warning('  %s', ln)
        self._say(['🔴 每日体检发现问题'] +
                  problems +
                  ['', '详见：双击 Doctor.bat 查看处理办法'])

    # ────────────────────────── 4. 录播索引页 ──────────────────────────
    def build_index(self) -> None:
        try:
            tools_dir = p('tools')
            import sys
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)
            import build_index
            out = build_index.build()
            self.logger.info('录播索引已更新：%s', out)
        except Exception as e:
            self.logger.debug(f'索引页生成跳过: {e}')
