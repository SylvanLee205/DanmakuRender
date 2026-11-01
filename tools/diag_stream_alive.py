"""诊断断尾人类的流是否还在推数据（只读探测，不改任何状态）。

目的：区分两种情况 ——
  A. 抖音 CDN 还在推数据，只是本地 streamgears 卡了  → 重启下载器能救
  B. 抖音 CDN 本身不发了（主播端网络/编码异常）      → 重启也没用
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, r'F:\DanmakuRepo')
os.chdir(r'F:\DanmakuRepo')
import logging
logging.basicConfig(level=logging.CRITICAL)

from DMR.Config import Config
from DMR.LiveAPI import LiveAPI

TASK = '断尾人类'

cfg = Config(r'F:\DanmakuRepo\configs\global.yml')
t = cfg.replay_config.get(TASK)
if not t:
    print(f'  找不到任务 {TASK}')
    sys.exit(1)

d = t['download_args']
print('=' * 74)
print(f'诊断 {TASK} 的流状态')
print('=' * 74)
print(f'  url       : {d.get("url")}')
print(f'  platform  : {d.get("platform")}')

# 取流
try:
    rid = str(d.get('url') or '').rstrip('/').split('/')[-1]
    plat = d.get('platform') or 'douyin'
    print(f'  rid       : {rid}   plat: {plat}')
    from DMR.LiveAPI import Onair, GetStreamURL as _GSU
    try:
        print(f'  Onair     : {Onair(plat, rid)}')
    except Exception as e:
        print(f'  Onair 失败: {type(e).__name__}: {e}')
    url = _GSU(plat, rid)

    print(f'  取流结果  : {"✅ 拿到" if url else "❌ None（可能已下播/风控）"}')
    if url:
        print(f'  流地址主机: {str(url).split("/")[2] if "//" in str(url) else "?"}')
except Exception as e:
    print(f'  ❌ 取流失败: {type(e).__name__}: {e}')
    url = None

if not url:
    print()
    print('  结论：拿不到流地址 → 主播可能已下播，或抖音风控。')
    print('        这种情况本地重启也没用。')
    sys.exit(0)

# 用 ffmpeg 试拉 15 秒，看收到多少数据
print()
print('  用 ffmpeg 试拉 15 秒（只读，不影响正在录制的进程）...')
cmd = ['ffmpeg', '-v', 'warning', '-fflags', '+discardcorrupt+genpts',
       '-i', str(url), '-t', '15', '-f', 'null', '-']
try:
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=90)
    out = (r.stderr or '')
    # 解析收到的帧/时间
    lines = [l for l in out.split('\n') if l.strip()]
    got = [l for l in lines if 'time=' in l or 'frame=' in l]
    print(f'    ffmpeg exit={r.returncode}')
    if got:
        last = got[-1]
        print(f'    最后进度: {last.strip()[:120]}')
    warn = [l for l in lines if any(k in l for k in
                                   ('Non-mono', 'Invalid', 'corrupt', 'error', 'Error'))]
    if warn:
        print(f'    警告 {len(warn)} 条，前 3 条:')
        for l in warn[:3]:
            print(f'      {l.strip()[:110]}')
    # 判定：能不能读到 15 秒内容
    ok = any('time=00:00:1' in l or 'time=00:00:0' in l for l in lines)
    print()
    if r.returncode == 0 or ok:
        print('  ✅ 结论：CDN 还在推数据（ffmpeg 能读到内容）')
        print('     → 说明是**本地 streamgears 卡住了**，重启该任务的下载器可以救。')
    else:
        print('  ⚠️ 结论：ffmpeg 也读不到内容')
        print('     → 可能是 CDN/主播端问题，重启也未必有用。')
except subprocess.TimeoutExpired:
    print('    ⚠️ ffmpeg 超时（90 秒）→ 流几乎不推数据')
except Exception as e:
    print(f'    ❌ {type(e).__name__}: {e}')
