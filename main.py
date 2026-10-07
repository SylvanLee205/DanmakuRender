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
            U: 直播已结束.               (liveevents, INFO)
            一一一天: 直播开始.           (PROGRESS)
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

from DMR import DanmakuRender
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
        print(f'DanmakuRender-5 {VERSION}.')
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

    logger.debug(f'VERSION: {VERSION}')

    # 启动横幅：因为静默模式下控制台没有 INFO 日志，很容易看不出程序还在跑。
    # 用 print 直接输出（不经 logger），确保任何级别下都显示。
    try:
        _lvl_txt = {logging.DEBUG: 'DEBUG(很吵)', logging.INFO: 'INFO',
                    logging.WARNING: 'WARNING(只有警告)', PROGRESS: 'PROGRESS(关键进度)',
                    logging.ERROR: 'ERROR(只留错误)',
                    logging.CRITICAL: 'CRITICAL'}.get(_console_level, '?')
        print()
        print('=' * 68)
        print(f'  DanmakuRender-5 {VERSION}   已启动')
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

    dmr = DanmakuRender(config, logger=logger, debug=args.debug)
    dmr.start()

    # 注意：这里**不**再打印"已加载 N 个主播"之类的汇总横幅。
    # 因为控制台已经会逐个输出：
    #     [engine][info]: 下载任务 XXX 已启动。
    #     [liveevents][info]: XXX: 直播已结束.   (或 直播开始.)
    # 用户扫一眼终端就能看出哪个主播加载成功、哪个开播了 —— 这比汇总更有用。
    # 也不打印"控制台会空白"的提示，避免和真实日志混淆。

    # ── 心跳：定期往日志写一行，证明程序还在跑 ──
    # 用 INFO 级别（控制台也会显示，但 30 分钟才一行，不构成噪音）。
    # 主要作用是让"日志文件还在增长"成为"程序活着"的证据。
    n_tasks = len(getattr(config, 'replay_config', {}) or {})

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

    try:
        while 1:
            time.sleep(60)
    except KeyboardInterrupt:
        dmr.stop()
        exit(0)

