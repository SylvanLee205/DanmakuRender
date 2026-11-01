"""复现 DMR ffmpeg 下载引擎的命令，抓真实报错。

从运行中的测试任务进程里取出完整命令行，改成可诊断的形式（限时 20 秒）重跑。
"""
import subprocess
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）

# 从 WMI 拿不到（需要 psutil），这里直接按 DMR 的构造逻辑重建命令
sys.path.insert(0, _PROJECT_ROOT)
import os
os.chdir(_PROJECT_ROOT)
import logging
logging.basicConfig(level=logging.CRITICAL)

from DMR.Config import Config
from DMR.LiveAPI import LiveAPI


cfg = Config(_PROJECT_ROOT + r'\configs\global.yml')
task = cfg.replay_config['_引擎测试']
da = task['download_args']
adv = da.get('advanced_video_args') or {}

api = LiveAPI('douyin', '765184155745')
url = api.GetStreamURL()
hdr = api.GetStreamHeader()
print('=' * 78)
print('诊断 ffmpeg 拉流')
print('=' * 78)
print(f'  stream_url: {str(url)[:120]}')
print(f'  header keys: {list((hdr or {}).keys())}')

stream_args = adv.get('ffmpeg_stream_args') or [
    '-rw_timeout', '10000000', '-analyzeduration', '15000000',
    '-probesize', '50000000', '-thread_queue_size', '16']

cmd = ['ffmpeg', '-v', 'verbose', '-y',
       '-headers', ''.join('%s: %s\r\n' % x for x in (hdr or {}).items()),
       *stream_args,
       '-i', str(url), '-c', 'copy',
       '-t', '10', '-f', 'mpegts',
       os.path.join('.temp', '_ffdiag.ts')]

print()
print('  命令:')
print('    ' + ' '.join(str(x) for x in cmd)[:600])
print()
print('  运行（最多 40 秒）...')
try:
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=40)
    ok = r.returncode == 0
    print(f'  exit={r.returncode}  {"✅ 成功" if ok else "❌ 失败"}')
    tail = (r.stderr or '')
    lines = [l for l in tail.split('\n') if l.strip()]
    print()
    print('  ffmpeg 输出（最后 25 行）:')
    for l in lines[-25:]:
        print(f'    {l[:150]}')
except subprocess.TimeoutExpired:
    print('  ⏱ 40 秒超时 —— ffmpeg 卡在拉流，说明连不上或不推数据')

p = os.path.join('.temp', '_ffdiag.ts')
if os.path.exists(p):
    print()
    print(f'  产物: {os.path.getsize(p)} 字节')
    os.remove(p)
