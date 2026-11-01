from tools import check_pypi, check_update
check_pypi()

import time
import argparse
import threading
from datetime import datetime
import os
import sys
import logging
import logging.handlers
# ── 自定义日志级别：PROGRESS ──────────────────────────────────────
# 目的：控制台既要"安静"（不显示 GOP/engine 字典/每个任务的状态流转），
#       又要能看出程序在干活（不然像卡死）。
# 数值取 25，落在 INFO(20) 和 WARNING(30) 之间：
#     --quiet          -> PROGRESS（只显示关键进度 + 警告错误）
#     --quiet=info     -> INFO（详细，原行为）
#     --quiet=error    -> ERROR（只留错误）
#     --quiet=debug    -> DEBUG（很吵）
PROGRESS = 25
logging.addLevelName(PROGRESS, 'PROGRESS')


class _ConsoleNoiseFilter(logging.Filter):
    """控制台噪音过滤器：丢掉 engine 内部的消息字典。

    ⚠️ 为什么要这个：
        DMR 的 engine 每处理一条管道消息就打一遍完整字典，
        例如：
            [engine][debug]: {'source': 'downloader', 'target': 'replay/U',
                              'event': 'liveend', 'request_id': None, 'msg': '直播已结束',
                              'dtype': None, 'data': None}
        启动 32 个任务时这类消息有 130+ 行，是控制台"看着乱"的主要来源。
        它对用户毫无信息量（用户要看的是"哪个主播加载了、开播没有"）。

    ⚠️ 为什么不用"提高级别"来解决：
        因为用户希望**保留**这些：
            下载任务 U 已启动。          (engine, INFO)
            U: 直播已结束.               (liveevents, PROGRESS)
            U: 直播开始                  (liveevents, PROGRESS)
            解析直播间失败 / ERROR / WARNING
        如果简单提高到 WARNING，这些就全没了，用户就不知道主播有没有加载成功。
        所以做法是：**放行绝大部分消息，只精确丢掉那一种噪音。**

    过滤规则：只丢 DMR.engine 打出的、以 '{' 开头且含 'source' 的消息。
    带 ERROR/WARNING/异常的关键字一律放行（宁可多显示，不可漏报）。
    """
    _KEEP_KEYWORDS = ('error', 'fail', 'warn', 'exception', 'traceback',
                      '错误', '失败', '异常')

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if record.name != 'DMR.engine':
                return True
            msg = record.getMessage()
            if not msg.lstrip().startswith('{'):
                return True
            low = msg.lower()
            if any(k in low for k in self._KEEP_KEYWORDS):
                return True          # 含错误信息的字典照常显示
            return 'source' not in msg
        except Exception:
            return True


import yaml
from glob import glob
from os.path import exists, splitext

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.append('./tools')

VERSION = '2026.05.01'

from DMR import DanmakuRepo
from DMR.Config import Config


def _startup_recover(config, logger, enabled=True, wait=False, min_age_minutes=2):
    """启动时自动检测并恢复中断录制留下的 .part 文件。

    为什么放在程序内部而不是 bat 里：
        这样无论用什么方式启动（双击 main.py、Start_Render.bat、计划任务、开机自启）
        都会执行恢复，不依赖某个特定的启动脚本。

    安全性（很重要）：
        - 只处理最后修改早于 min_age_minutes 分钟的文件（默认 2）。
        - ⚠️ 阈值为什么是 2 分钟而不是 10：
          程序启动时会先把上一次残留的 .part 扫一遍，此时 DMR 自己的下载
          任务才刚开始拉起，不会有"正在录制中"的分段。如果阈值设 10 分钟，
          上次崩溃/重启留下的新 .part（通常只有几分钟）就会被漏掉，
          要等**下一次**启动才能捡回来。2 分钟既覆盖了这种情况，
          又留出了足够的余量（单个分段通常 1 小时，绝不可能 2 分钟就写完）。
        - ffprobe 读不出来的文件一律跳过，不动它。
        - 恢复完的文件不再是 .part，天然幂等。
        - 整个过程包在 try/except 里，**任何异常都不能影响主程序启动**。
        - 用 --no_recover 可以整体关掉。

    wait=False 时在后台线程跑（不阻塞主程序）；wait=True 时同步跑完再启动引擎。
    """
    if not enabled:
        logger.info('已通过 --no_recover 关闭中断录制恢复。')
        return None

    def _job():
        # ── 第一步：ffmpeg 引擎遗留的分段（无 .part，需改名接管）──────
        # ⚠️ 2026-10-18 新增：切到 engine=ffmpeg 后，崩溃/重启会留下
        # `[正在录制]<主播>-<YYYYMMDD-HHMMSS>-PartNNN.<ts|mkv|mp4>`。
        # ffmpeg 的 segment 是流式写的，这些文件**本身可用**（TS 尤其如此，
        # 实测截断到 50% 后 ffprobe 报的时长准确、能完整解码），
        # 所以不需要像 biliup 的 .part 那样去"修复"，只要改名入库即可。
        # 必须在 recover_part 之前跑：recover_part 只认 `.part`，认不出这些。
        try:
            from tools.recover_ffmpeg_segments import recover_all as _ff_recover
            _ff = _ff_recover(config, min_age_minutes=min_age_minutes,
                              apply_changes=True, logger=logger)
            if _ff.get("scanned"):
                logger.info(
                    f"ffmpeg 分段恢复：扫描 {_ff['scanned']} / "
                    f"成功 {len(_ff['recovered'])} / 失败 {len(_ff['failed'])}"
                )
        except Exception as e:
            logger.warning(f"ffmpeg 分段恢复跳过（不影响正常录制）: "
                           f"{type(e).__name__}: {e}")

        try:
            from tools.recover_part import recover_all
            res = recover_all(cfg=config, min_age_minutes=min_age_minutes,
                              do_render=True, do_upload=True, apply=True, logger=logger)
            if res.get('scanned'):
                logger.info(
                    f"中断录制恢复完成：扫描 {res['scanned']} / 恢复 {len(res['recovered'])} / "
                    f"渲染 {len(res['rendered'])} / 上传 {res['uploaded']}"
                )
        except Exception as e:
            logger.error(f'中断录制恢复过程出错（不影响正常录制）: {type(e).__name__}: {e}')
            try:
                logger.exception(e)
            except Exception:
                pass

    if wait:
        _job()
        return None
    t = threading.Thread(target=_job, name='startup-recover', daemon=True)
    t.start()
    return t


def _verify_configs(config, logger):
    """启动时校验配置完整性。

    ⚠️ 为什么需要：
        configs/ 是唯一的真实配置源，装着 global.yml（含我们的魔改：rclone
        上传、跳过上传规则、清理规则等）和 33 个主播的任务配置。
        2026-10-15 合并上游时就差点踩坑 —— dev 的 global.yml 丢了
        upload_args_task_default（上传规则本体）和 clean_args，
        而且 rclone 的 realtime 被改成 True（会改变上传行为）。
        当时靠人工发现才避开。这个校验把它变成自动的。

    检查三件事：
        1. global.yml 存在，且关键配置段都在
        2. 任务配置数量（和状态库/预期对比，骤减就报警）
        3. 和最近一次配置快照做差异校验（若有快照）

    任何异常都只记日志，绝不阻断启动。
    """
    try:
        import glob as _glob
        import yaml as _yaml

        logger.info('=' * 60)
        logger.info('配置完整性校验')

        # 1. global.yml 关键段
        cfg_path = 'configs/global.yml'
        CRITICAL = [
            ('upload_args', '上传配置（含 rclone 网盘）'),
            ('upload_args_task_default', '上传规则本体'),
            ('clean_args', '清理配置'),
            ('render_args', '渲染配置'),
            ('download_args', '下载配置'),
        ]
        missing = []
        if not exists(cfg_path):
            missing.append('global.yml（整个文件缺失！）')
        else:
            try:
                txt = open(cfg_path, encoding='utf-8').read()
            except Exception:
                txt = ''
            for key, desc in CRITICAL:
                if key not in txt:
                    missing.append(f'{key} —— {desc}')

        if missing:
            logger.error('配置缺失 %d 项，**上传/清理可能失效**：', len(missing))
            for m in missing:
                logger.error('    ❌ %s', m)
            logger.error('    恢复方法: python tools\\backup_configs.py list')
            logger.error('              python tools\\backup_configs.py restore <快照名>')
        else:
            logger.info('  ✅ global.yml 关键段完整')

        # 2. 任务配置数量
        tasks = [f for f in _glob.glob('configs/*.yml')
                 if not os.path.basename(f).startswith('global')]
        logger.info('  ✅ 任务配置 %d 个', len(tasks))
        if len(tasks) == 0:
            logger.error('  ❌ 一个任务配置都没有！configs 目录可能被清空了。')
        elif len(tasks) < 10:
            logger.warning('  ⚠️ 任务配置只有 %d 个，明显偏少（正常 30+），'
                           '请确认是否被误删。', len(tasks))

        # 3. 和最近快照对比
        snap_root = r'F:\_DMR配置快照'
        try:
            if os.path.isdir(snap_root):
                snaps = sorted(d for d in os.listdir(snap_root)
                               if os.path.isdir(os.path.join(snap_root, d)))
                if snaps:
                    mf = os.path.join(snap_root, snaps[-1], 'manifest.json')
                    if exists(mf):
                        import json as _json
                        man = _json.load(open(mf, encoding='utf-8'))
                        cur = set()
                        for root, dirs, files in os.walk('configs'):
                            dirs[:] = [d for d in dirs if d != '__pycache__']
                            for f in files:
                                cur.add(os.path.relpath(os.path.join(root, f),
                                                        'configs'))
                        lost = sorted(set(man.get('files', {})) - cur)
                        # ⚠️ 2026-10-19：快照里可能残留 .bak/.tmp/编辑器临时文件
                        #    （旧版 backup_configs 会收录它们）。这些不是"配置丢失"，
                        #    否则每次启动都会报一条假 ERROR，把真正的告警淹掉。
                        #    实测：DMR-灰蒙蒙.yml.bak-20261018-223751 被清理后，
                        #    启动自检连续报「丢失 1 个配置」。
                        lost = [x for x in lost
                                if not ('.bak' in x.lower() or x.endswith('~')
                                        or x.lower().endswith('.tmp')
                                        or x.lower().endswith('.swp'))]
                        if lost:
                            logger.error('  ❌ 相比快照 %s 丢失 %d 个配置:',
                                         snaps[-1], len(lost))
                            for x in lost[:8]:
                                logger.error('        %s', x)
                            if len(lost) > 8:
                                logger.error('        ... 还有 %d 个', len(lost) - 8)
                            logger.error('    恢复: python tools\\backup_configs.py '
                                         'restore %s', snaps[-1])
                        else:
                            logger.info('  ✅ 与最近快照一致（%s）', snaps[-1])
        except Exception as e:
            logger.debug('快照对比跳过: %s', e)

        logger.info('=' * 60)
    except Exception as e:
        # 校验本身绝不能影响启动
        try:
            logger.debug(f'配置校验过程出错（不影响启动）: {type(e).__name__}: {e}')
        except Exception:
            pass


def _verify_pipeline_switches(config, logger):
    """启动自检：检查每个任务的"自动化开关"，防止它们被静默翻转。

    ⚠️ 为什么需要（真实风险）：
        每个任务配置里的 common_event_args 控制整条流水线：
            auto_render  录完是否自动渲染
            auto_upload  渲染完是否自动上传
            auto_clean   上传完是否自动清理

        这些开关**没有任何保护** —— 一旦配置被覆盖（比如把 Mod 的配置
        同步到生产，而 Mod 里 auto_upload=False），流水线就会**静默停掉**：
        不报错、不警告、日志里一切正常，只是录播永远堆在本地不出去。
        等发现时往往已经攒了几天几十 GB。

        本函数在每次启动时把有效值打印出来，并在明显异常时给出醒目警告，
        让"上传被关掉"这件事**不可能被忽略**。

    判断逻辑：
        auto_upload 全为 False  → 🔴 重度警告（上传链路已停）
        auto_render 全为 False  → 🔴 重度警告（不会生成弹幕版）
        auto_clean  全为 False  → 🟡 提示（本地文件会一直累积）
        混合状态                → 逐项列出，便于核对是否本意

    任何异常都只记日志，绝不阻断启动。
    """
    try:
        rc = getattr(config, 'replay_config', None) or {}
        if not rc:
            logger.warning('流水线开关检查：未能读取任务配置（replay_config 为空）')
            return

        SWITCHES = [
            ('auto_render', '自动渲染'),
            ('auto_upload', '自动上传'),
            ('auto_clean', '自动清理'),
        ]
        stats = {k: {'on': 0, 'off': 0, 'none': 0, 'off_tasks': []}
                 for k, _ in SWITCHES}
        for name, cfg in rc.items():
            cea = ((cfg or {}).get('common_event_args') or {})
            for key, _ in SWITCHES:
                v = cea.get(key)
                s = stats[key]
                if v is True:
                    s['on'] += 1
                elif v is False:
                    s['off'] += 1
                    if len(s['off_tasks']) < 8:
                        s['off_tasks'].append(name)
                else:
                    s['none'] += 1

        total = len(rc)
        logger.info('=' * 60)
        logger.info('流水线开关检查（共 %d 个任务）', total)
        for key, label in SWITCHES:
            s = stats[key]
            flag = '✅' if s['on'] == total else ('🟡' if s['on'] else '🔴')
            logger.info('  %s %-10s 开启 %d / 关闭 %d / 未设置 %d',
                        flag, label, s['on'], s['off'], s['none'])
            if s['off'] and s['off'] < total:
                logger.info('       关闭的任务：%s%s', ', '.join(s['off_tasks']),
                            '…' if s['off'] > len(s['off_tasks']) else '')

        # ── 重度警告：整条流水线被关掉 ──
        if stats['auto_upload']['on'] == 0:
            logger.warning(
                '\n'
                '  ' + '!' * 58 + '\n'
                '  🔴 所有任务的 auto_upload 都是关闭状态 —— **上传链路已停！**\n'
                '      后果：渲染出的弹幕版只会留在本地，永远不会传到网盘。\n'
                '      排查：\n'
                '        1) 是否把 Mod 的配置同步到了生产？（Mod 里 auto_upload=False）\n'
                '        2) git -C F:\\DanmakuRepo diff -- configs/\n'
                '        3) python tools\\backup_configs.py verify\n'
                '      恢复：python tools\\backup_configs.py restore <快照名>\n'
                '  ' + '!' * 58)
        if stats['auto_render']['on'] == 0:
            logger.warning(
                '\n'
                '  ' + '!' * 58 + '\n'
                '  🔴 所有任务的 auto_render 都是关闭状态 —— **不会生成弹幕版！**\n'
                '      后果：只录到原始视频，不会渲染弹幕。\n'
                '  ' + '!' * 58)
        if stats['auto_clean']['on'] == 0:
            logger.warning('  🟡 所有任务的 auto_clean 都关闭 —— '
                           '本地源文件会一直累积（磁盘会慢慢满）')
        logger.info('=' * 60)
    except Exception as e:
        try:
            logger.debug(f'流水线开关检查出错（不影响启动）: {type(e).__name__}: {e}')
        except Exception:
            pass


def _verify_critical_names(logger):
    """启动自检：确保渲染/上传路径需要的名字都能拿到。

    ⚠️ 为什么需要（2026-10-15 事故）：
        合并上游时 DMR/utils/__init__.py 少了 `from .xml2ass import *`，
        导致 dmrender.py 的 `from DMR.utils import *` 拿不到 is_danmaku_xml。
        这个错误**只在真正渲染时才暴露**，后果是每个分段都渲染失败
        （3 个分段 2.3 GB 白白滞留，直到用户发现终端在报错）。

        注意：`import DMR.Render.dmrender` 本身是成功的 ——
        因为 is_danmaku_xml 在函数体内使用，只有调用时才解析名字。
        所以必须**显式检查这些名字是否存在**，不能只测"模块能导入"。

    任何异常都只记日志，绝不阻断启动。
    """
    try:
        import importlib

        CHECK = [
            ('DMR.Render.dmrender',
             ['is_danmaku_xml', 'xml_to_ass', 'DEFAULT_ASS_SUFFIX',
              'FFprobe', 'VideoInfo', 'StreamerInfo', 'safe_filename',
              'replace_keywords']),
            ('DMR.Cleaner', ['basename', 'FileInfo', 'exists', 'isdir']),
            ('DMR.Uploader', ['VideoInfo', 'Uploader']),
            ('DMR.Downloader.stream_downloader',
             ['basename', 'VideoInfo', 'StreamerInfo', 'replace_keywords',
              'rename_safe', 'FFprobe']),
            ('DMR.Task.liveevents',
             ['PROGRESS', 'PipeMessage', 'VideoInfo', 'ArtifactState',
              'ArtifactKind']),
        ]

        problems = []
        for mod, names in CHECK:
            try:
                m = importlib.import_module(mod)
            except Exception as e:
                problems.append(f'{mod} 无法导入: {type(e).__name__}: {e}')
                continue
            miss = [n for n in names if not hasattr(m, n)]
            if miss:
                problems.append(f'{mod} 缺少名字: {miss}')

        if problems:
            logger.error('=' * 60)
            logger.error('启动自检发现问题 %d 项 —— **渲染/上传会失败**：',
                         len(problems))
            for p in problems:
                logger.error('    ❌ %s', p)
            logger.error('    常见原因：某个 __init__.py 少了 `from .xxx import *`')
            logger.error('    检查工具: python tools\\check_critical_names.py')
            logger.error('=' * 60)
        else:
            logger.info('  ✅ 关键名字自检通过（渲染/上传路径正常）')
    except Exception as e:
        try:
            logger.debug(f'关键名字自检出错（不影响启动）: {type(e).__name__}: {e}')
        except Exception:
            pass


def _log_build_id(logger):
    """启动时把当前 git 提交记进日志。

    为什么需要：这是台长期在跑的生产机，"现在跑的到底是哪版代码"每次都要靠
    进程启动时间和 git log 去推断；改完代码重启后也没法一眼确认新代码已加载。
    这里直接读 .git（不启子进程），把短 hash 打进日志第一屏。

    任何异常都只记 debug —— 这条日志绝不能影响启动。
    """
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        head = os.path.join(root, '.git', 'HEAD')
        if not os.path.exists(head):
            return
        with open(head, 'r', encoding='utf-8') as f:
            ref = f.read().strip()
        sha = ref
        if ref.startswith('ref:'):
            ref_path = os.path.join(root, '.git', ref[4:].strip())
            if not os.path.exists(ref_path):
                return
            with open(ref_path, 'r', encoding='utf-8') as f:
                sha = f.read().strip()
        sha = sha.strip()
        if 7 <= len(sha) <= 40 and all(c in '0123456789abcdef' for c in sha.lower()):
            logger.info('代码版本: %s @ %s', VERSION, sha[:7])
        else:
            logger.debug('代码版本: %s（无法解析 git HEAD: %r）', VERSION, ref)
    except Exception as e:
        try:
            logger.debug('读取代码版本失败（不影响启动）: %s: %s',
                         type(e).__name__, e)
        except Exception:
            pass


if __name__ == '__main__':    
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='configs/global.yml')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--version', action='store_true')
    parser.add_argument('--skip_update', action='store_true')
    parser.add_argument('--no_recover', action='store_true',
                        help='关闭启动时的中断录制(.part)自动恢复')
    parser.add_argument('--recover_wait', action='store_true',
                        help='恢复过程同步执行（等恢复渲染完再开始录制），默认后台跑')
    parser.add_argument('--recover_min_age', type=int, default=2,
                        help='只恢复最后修改早于 N 分钟的 .part（默认 2）')
    parser.add_argument('--quiet', nargs='?', const='quiet', default=None,
                        metavar='LEVEL',
                        help='控制台输出级别。不带值 = info（推荐，保留主播加载/'
                             '开播/下播等全部信息，只过滤 engine 的消息字典噪音）；'
                             '也可指定 progress（更简）/warning/error/debug。'
                             '注意：只影响控制台，日志文件始终保留全部 DEBUG。')
    parser.add_argument('--no-console-filter', action='store_true',
                        help='关掉控制台噪音过滤（会显示 engine 的消息字典）。'
                             '仅在排查管道问题时才需要。')
    args = parser.parse_args()

    # ── 单实例锁（防跨会话双开，2026-10-19）─────────────────────────
    # 能拉起 DMR 的入口有三个：开机任务（session 0）、登录自启（session 1）、
    # 手动双击。三者的进程检查之间有几秒空档，同时通过就会起两个 DMR，
    # 而两个实例共用同一份状态库和录制目录，会互相覆盖产物状态。
    # 详见 DMR/utils/instance_lock.py（Windows 命名互斥体，进程退出自动释放）。
    # 任何异常都 fail-open：无人值守机器上"能起来"优先。
    if not args.version:
        from DMR.utils.instance_lock import acquire as _acquire_instance_lock
        if _acquire_instance_lock() == 'busy':
            _busy_msg = ('已有 DanmakuRepo 实例在运行，本次启动退出。\n'
                         '两个实例会用同一份状态库和录制目录，互相覆盖产物状态。\n'
                         '确实要再起一个（例如换了 --config），先停掉正在跑的那个。')
            print(_busy_msg)
            sys.exit(3)

    # 控制台日志级别
    #   默认 / --quiet      -> INFO（推荐：主播加载、开播、下播都能看到）
    #   --quiet=progress    -> PROGRESS（只留关键进度 + 警告错误）
    #   --quiet=warning     -> WARNING（只有警告错误）
    #   --quiet=error       -> ERROR（只有错误）
    #   --quiet=debug       -> DEBUG（全部，很吵）
    #
    # ⚠️ 设计说明（2026-10-07 根据用户反馈调整）：
    #   用户要的是"信息丰富但整齐"，不是"最安静"。
    #   关键在于：**保留 INFO 全部消息**（这样能看出主播有没有加载成功），
    #   同时**过滤掉 engine 的消息字典**（那 130+ 行大段 JSON 才是"乱"的来源）。
    #   过滤由 _ConsoleNoiseFilter 完成，不通过提高级别实现。
    # 日志文件不受影响，永远是 DEBUG，所以放心。
    _lvl_name = (args.quiet or 'info').lower()
    if _lvl_name in ('quiet', ''):
        _lvl_name = 'info'
    _console_level = {
        'debug': logging.DEBUG,
        'info': logging.INFO,
        'progress': PROGRESS,
        'warning': logging.WARNING,
        'warn': logging.WARNING,
        'error': logging.ERROR,
        'critical': logging.CRITICAL,
    }.get(_lvl_name, logging.INFO)

    if args.version:
        print(f'DanmakuRepo {VERSION}.')
        print('https://github.com/SmallPeaches/DanmakuRender')
        exit(0)
    
    if not args.skip_update:
        check_update(VERSION)
    
    config = Config(args.config)

    logger = logging.getLogger('DMR')
    logger.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(_console_level)
    console_handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s]: %(message)s"))
    # 控制台噪音过滤：只丢 engine 的消息字典，其余全部放行。
    # --no-console-filter 可关闭（排查管道问题时用）。
    if not args.no_console_filter:
        console_handler.addFilter(_ConsoleNoiseFilter())
    
    os.makedirs('logs', exist_ok=True)
    log_file = f'logs/DMR-{datetime.now().strftime("%Y%m%d")}.log'
    if exists(log_file):
        _cnt = len(glob(splitext(log_file)[0] + '*'))
        log_file = splitext(log_file)[0] + f'({_cnt})' + splitext(log_file)[1]
    file_handler = logging.handlers.TimedRotatingFileHandler(log_file, when='D', interval=1, backupCount=3, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("[%(asctime)s][%(module)s][%(levelname)s]: %(message)s"))
    
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    # 可选：进程内内存诊断（默认关闭；设 DMR_MEM_PROBE=1 启用）。
    # 启用后可用 `kill -USR1 <pid>` 随时打印内存快照，
    # `kill -USR2 <pid>` 打印并尝试把 glibc 堆空洞还给系统。
    try:
        from tools.mem_probe_inproc import install as _install_mem_probe
    except Exception as _e:
        logger.debug(f'内存诊断未启用: {_e}')

    logger.debug(f'VERSION: {VERSION}')
    _log_build_id(logger)

    # 启动横幅：因为静默模式下控制台没有 INFO 日志，很容易看不出程序还在跑。
    # 用 print 直接输出（不经 logger），确保任何级别下都显示。
    try:
        _lvl_txt = {logging.DEBUG: 'DEBUG(很吵)', logging.INFO: 'INFO',
                    logging.WARNING: 'WARNING(只有警告)', PROGRESS: 'PROGRESS(关键进度)',
                    logging.ERROR: 'ERROR(只留错误)',
                    logging.CRITICAL: 'CRITICAL'}.get(_console_level, '?')
        print()
        print('=' * 68)
        print(f'  DanmakuRepo {VERSION}   已启动')
        print(f'  控制台输出级别: {_lvl_txt}')
        print(f'  完整日志(DEBUG): {log_file}')
        if _console_level >= PROGRESS:
            print('  （控制台只显示关键进度和警告/错误；'
                  '想看详细输出用 --quiet=info）')
        print('=' * 68)
        print()
    except Exception:
        pass

    # 启动时自动恢复中断录制（在起引擎之前，日志已就绪）
    _startup_recover(config, logger,
                     enabled=not args.no_recover,
                     wait=args.recover_wait,
                     min_age_minutes=args.recover_min_age)

    # 启动时校验配置完整性（防止 configs 被误删/覆盖）
    _verify_configs(config, logger)

    # 启动时自检关键名字（防止"用了但拿不到"导致渲染/上传静默失败）
    _verify_critical_names(logger)

    # 启动时检查自动化开关（防 auto_upload 等被静默翻转，导致流水线无声停摆）
    _verify_pipeline_switches(config, logger)

    dmr = DanmakuRepo(config, logger=logger, debug=args.debug)
    dmr.start()

    # 注意：这里**不**再打印"已加载 N 个主播"之类的汇总横幅。
    # 因为控制台已经会逐个输出：
    #     [engine][info]: 下载任务 XXX 已启动。
    #     [liveevents][PROGRESS]: XXX: 直播已结束.   (或 直播开始.)
# 注意：直播状态是 PROGRESS 级别（25），不是 INFO —— 见 docs/控制台日志格式规范.md
    # 用户扫一眼终端就能看出哪个主播加载成功、哪个开播了 —— 这比汇总更有用。
    # 也不打印"控制台会空白"的提示，避免和真实日志混淆。

    # ── 启动成功 → 发重启通知 ──
    # 放在 dmr.start() **之后**，所以通知里的状态是真实的：
    #   - 主播名单来自实际加载的配置（不是写死的数字）
    #   - CD2 状态实时查
    # 在后台线程里发，避免网络慢时拖住启动。
    _task_names = list((getattr(config, 'replay_config', {}) or {}).keys())
    n_tasks = len(_task_names)

    def _send_startup_notify():
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(
                os.path.abspath(__file__)), 'tools'))
            from gen_restart_notify import notify as _notify
            ok, title, _ = _notify(task_names=_task_names, task_count=n_tasks,
                                   quiet=True)
            logger.debug(f'[通知] {"已发送" if ok else "发送失败"}: {title}')
        except Exception as e:
            logger.debug(f'[通知] 发送异常: {type(e).__name__}: {e}')

    try:
        threading.Thread(target=_send_startup_notify, daemon=True,
                         name='DMR-startup-notify').start()
    except Exception:
        pass

    # ── 心跳：定期往日志写一行，证明程序还在跑 ──
    # 用 INFO 级别（控制台也会显示，但 30 分钟才一行，不构成噪音）。
    # 主要作用是让"日志文件还在增长"成为"程序活着"的证据。

    def _heartbeat():
        while True:
            time.sleep(1800)          # 每 30 分钟
            try:
                logger.info(f'[心跳] 程序运行中，监听 {n_tasks} 个主播。')
            except Exception:
                pass

    try:
        threading.Thread(target=_heartbeat, daemon=True,
                         name='DMR-heartbeat').start()
    except Exception:
        pass

    # ── 优雅停止 ──
    # 为什么不直接 psutil kill：硬杀会让 ffmpeg 来不及收尾 —— 正在录的分段
    # 停留在 `[正在录制]` 状态、rename 不执行，正在渲染的任务也会半途而废。
    # 走 dmr.stop() 时，ffmpeg 会收到 'q'（见 DMR/Downloader/ffmpeg.py 的
    # communicate('q')）优雅写完当前段，随后 segment_callback 把它改名成
    # 正式名；下次启动 reconciler 发现目录里有源视频就会补派渲染。
    #
    # 触发方式：stop_dmr.py 创建 .temp/graceful_stop_<PID>（带 PID，
    # 绝不会误伤别的实例）。
    _GRACEFUL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 '.temp')
    _GRACEFUL_FLAG = os.path.join(_GRACEFUL_DIR, f'graceful_stop_{os.getpid()}')

    def _graceful_requested() -> bool:
        try:
            return os.path.isfile(_GRACEFUL_FLAG)
        except Exception:
            return False

    def _clear_graceful_flag() -> None:
        try:
            os.remove(_GRACEFUL_FLAG)
        except OSError:
            pass

    def _wait_seconds(n: int) -> None:
        """分段 sleep 并检查优雅停止标志，比一次性 sleep(60) 响应快得多。"""
        deadline = time.time() + n
        while time.time() < deadline:
            if _graceful_requested():
                return
            time.sleep(0.2)

    try:
        while 1:
            _wait_seconds(60)
            if _graceful_requested():
                logger.info('收到优雅停止请求，正在收尾录制与渲染...')
                try:
                    dmr.stop()
                except Exception as e:
                    logger.exception(f'优雅停止过程中出错: {e}')
                _clear_graceful_flag()
                logger.info('优雅停止完成，退出。')
                exit(0)
    except KeyboardInterrupt:
        _clear_graceful_flag()
        dmr.stop()
        exit(0)
