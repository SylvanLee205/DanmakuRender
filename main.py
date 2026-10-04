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
import yaml
from glob import glob
from os.path import exists, splitext

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.append('./tools')

VERSION = '2026.05.01'

from DMR import DanmakuRender
from DMR.Config import Config


def _startup_recover(config, logger, enabled=True, wait=False, min_age_minutes=10):
    """启动时自动检测并恢复中断录制留下的 .part 文件。

    为什么放在程序内部而不是 bat 里：
        这样无论用什么方式启动（双击 main.py、Start_Render.bat、计划任务、开机自启）
        都会执行恢复，不依赖某个特定的启动脚本。

    安全性（很重要）：
        - 只处理最后修改早于 min_age_minutes 分钟的文件。
          程序刚启动时正在录制的分段一定是很新的，所以不会被误处理。
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
    parser.add_argument('--recover_min_age', type=int, default=10,
                        help='只恢复最后修改早于 N 分钟的 .part（默认 10）')
    args = parser.parse_args()

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
    console_handler.setLevel(logging.INFO) 
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

    # 启动时自动恢复中断录制（在起引擎之前，日志已就绪）
    _startup_recover(config, logger,
                     enabled=not args.no_recover,
                     wait=args.recover_wait,
                     min_age_minutes=args.recover_min_age)

    dmr = DanmakuRender(config, logger=logger, debug=args.debug)
    dmr.start()
    
    try:
        while 1:
            time.sleep(60)
    except KeyboardInterrupt:
        dmr.stop()
        exit(0)

