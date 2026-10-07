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
                        help='降低控制台输出。不带值 = PROGRESS（只显示关键进度 '
                             '如直播开始/渲染完成/上传完成 + 警告错误）；'
                             '也可指定 info（详细，原行为）/warning/error/debug。'
                             '注意：只影响控制台，日志文件始终保留全部 DEBUG。')
    args = parser.parse_args()

    # 控制台日志级别
    #   默认（不带 --quiet） -> INFO（原行为，详细）
    #   --quiet             -> PROGRESS（关键进度 + 警告错误）★推荐
    #   --quiet=info        -> INFO（和默认一样）
    #   --quiet=warning     -> WARNING（只有警告错误，最安静）
    #   --quiet=error       -> ERROR（只有错误）
    #   --quiet=debug       -> DEBUG（排查用，很吵）
    # 日志文件不受影响，永远是 DEBUG，所以放心降噪。
    _lvl_name = (args.quiet or 'info').lower()
    if _lvl_name in ('quiet', ''):
        _lvl_name = 'progress'
    _console_level = {
        'debug': logging.DEBUG,
        'info': logging.INFO,
        'progress': PROGRESS,
        'warning': logging.WARNING,
        'warn': logging.WARNING,
        'error': logging.ERROR,
        'critical': logging.CRITICAL,
    }.get(_lvl_name, PROGRESS)

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

    # ── 启动汇总：让用户一眼看出"程序起来了、监听了多少主播" ──
    # 背景：控制台降噪后，如果所有主播都没开播，控制台会长时间空白，
    # 用户分不清"正常空闲"和"程序卡死"。所以这里明确报一次任务数，
    # 并说明"空白是正常的"。
    try:
        n_tasks = len(getattr(config, 'replay_config', {}) or {})
        print('=' * 68)
        print(f'  已加载并开始监听 {n_tasks} 个主播')
        print('  每个主播的状态检查结果会写进日志文件；')
        print('  控制台只在【开播 / 渲染 / 上传 / 清理】时输出。')
        print('  → 所以控制台长时间空白 = 所有主播都没开播，属于正常。')
        print(f'  → 想看每个主播的状态，查日志: {log_file}')
        print('=' * 68)
        print()
    except Exception:
        pass

    # ── 心跳：定期往日志写一行，证明程序还在跑 ──
    # 用 INFO 级别（控制台不显示），只在日志文件里留痕。
    # 这样"日志文件还在增长"就能作为"程序活着"的证据。
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

