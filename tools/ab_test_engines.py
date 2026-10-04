"""真实引擎对测：对同一个正在直播的房间，依次用各录制引擎跑固定时长，比较结果。

用法：
    # 指定一个正在直播的抖音房间
    python tools\ab_test_engines.py --url https://live.douyin.com/56909717876 --seconds 60

    # 或者让脚本自己从 configs 里找一个在播的主播
    python tools\ab_test_engines.py --seconds 60

测试内容（对每个引擎依次）：
    1. 取一次流地址
    2. 用 subprocess 直接跑该引擎的下载器，固定秒数后终止
    3. 检查产出文件：大小、能否解码、时长、帧数、丢帧情况
    4. 记录退出码和 stderr

只写临时目录，不影响 ./直播回放。
"""
import argparse
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFPROBE = r'C:\User Program Files\FFmpeg\bin\ffprobe.exe'
VENV_PY = r'F:\DanmakuRender_AutoUp\.venv\Scripts\python.exe'


def log(msg):
    print(msg, flush=True)


def pick_live_room():
    """从配置里找一个正在直播的主播。"""
    import logging
    logging.basicConfig(level=logging.CRITICAL)
    from DMR.Config import Config
    from DMR.LiveAPI import LiveAPI

    cfg = Config('configs/global.yml')
    for task in cfg.get_replaytasks():
        rc = cfg.get_replay_config(task)
        url = (rc.get('download_args') or {}).get('url')
        if not url:
            continue
        try:
            if LiveAPI(url).Onair():
                log(f'  找到在播主播: {task}  {url}')
                return url, task
        except Exception:
            continue
    return None, None


def get_stream_info(url):
    """返回 (stream_url, header)。"""
    import logging
    logging.basicConfig(level=logging.CRITICAL)
    from DMR.LiveAPI import LiveAPI
    api = LiveAPI(url)
    return api.GetStreamURL(), api.GetStreamHeader()


def probe(path):
    try:
        out = subprocess.check_output([
            FFPROBE, '-v', 'error', '-print_format', 'json',
            '-show_format', '-show_streams', '-count_frames', path,
        ], stderr=subprocess.STDOUT, timeout=300)
        return json.loads(out.decode('utf-8', 'replace'))
    except Exception as e:
        return {'error': str(e)}


def run_engine(engine, stream_url, header, seconds, outdir):
    """跑一个引擎，返回 (文件名, 退出码, 输出尾巴)。"""
    os.makedirs(outdir, exist_ok=True)
    header_json = json.dumps(header)

    if engine == 'streamgears':
        cmd = [VENV_PY, 'DMR/Downloader/streamgears_wrapper.py',
               '-i', stream_url, '-o', os.path.join(outdir, 'sg'),
               '-s', '3600', '--header', header_json]
    elif engine == 'ffmpeg':
        cmd = ['ffmpeg', '-y', '-headers', ''.join(f'{k}: {v}\r\n' for k, v in header.items()),
               '-i', stream_url, '-c', 'copy', '-f', 'matroska',
               os.path.join(outdir, 'ff.mkv')]
    elif engine == 'streamlink':
        cmd = ['streamlink', '--output', os.path.join(outdir, 'sl.ts'),
               stream_url, 'best']
    else:
        return None, None, f'不支持的引擎 {engine}'

    log(f'    执行: {" ".join(str(c) for c in cmd)[:150]}...')
    start = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            cwd=ROOT)
    try:
        out, _ = proc.communicate(timeout=seconds + 25)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        # 正常情况：到时间主动终止
        if os.name == 'nt':
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        proc.kill()
        out, _ = proc.communicate()
        code = 'TIMEOUT(主动终止)'
    elapsed = time.time() - start

    tail = (out or b'').decode('utf-8', 'replace')[-400:]
    files = [f for f in glob.glob(os.path.join(outdir, '*'))
             if os.path.isfile(f) and os.path.getsize(f) > 0
             and not f.endswith('.part')]
    log(f'    耗时 {elapsed:.1f}s  退出码 {code}  产出 {len(files)} 个文件')
    return files, code, tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default=None)
    ap.add_argument('--seconds', type=int, default=60)
    ap.add_argument('--engines', default='streamgears,ffmpeg')
    opt = ap.parse_args()

    log('=' * 70)
    log('录制引擎对测')
    log('=' * 70)

    url = opt.url
    task = None
    if not url:
        log('\n[1] 自动寻找在播主播...')
        url, task = pick_live_room()
        if not url:
            log('  !! 当前没有任何主播在播，无法测试。')
            log('     等有主播开播后重跑，或用 --url 指定一个正在直播的房间。')
            return 1
    log(f'\n测试对象: {url}')

    log('\n[2] 获取流地址...')
    stream_url, header = get_stream_info(url)
    if not stream_url:
        log('  !! 取流地址失败')
        return 1
    log(f'  {stream_url[:100]}...')
    log(f'  判定协议: {"HLS(m3u8)" if ".m3u8" in stream_url else "FLV"}')

    tmp = tempfile.mkdtemp(prefix='dmr_abtest_')
    results = {}
    try:
        for engine in [e.strip() for e in opt.engines.split(',') if e.strip()]:
            log(f'\n[3] === 引擎: {engine} ===')
            outdir = os.path.join(tmp, engine)
            try:
                files, code, tail = run_engine(engine, stream_url, header, opt.seconds, outdir)
            except Exception as e:
                log(f'    异常: {type(e).__name__}: {e}')
                results[engine] = {'error': str(e)}
                continue
            if not files:
                log('    !! 没有任何产出文件')
                results[engine] = {'error': '无产出', 'tail': tail}
                continue

            biggest = max(files, key=os.path.getsize)
            info = probe(biggest)
            size_mb = os.path.getsize(biggest) / 1024 / 1024
            row = {'file': os.path.basename(biggest), 'size_mb': round(size_mb, 1),
                   'exit': str(code), 'tail': tail}
            if 'error' in info:
                row['probe_error'] = info['error']
            else:
                dur = float(info.get('format', {}).get('duration', 0) or 0)
                vs = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), {})
                row['duration'] = round(dur, 1)
                row['codec'] = vs.get('codec_name')
                row['frames'] = int(vs.get('nb_read_frames', 0) or 0)
                row['resolution'] = f"{vs.get('width')}x{vs.get('height')}"
            results[engine] = row
            log(f'    产出: {row}')

        log('\n' + '=' * 70)
        log('汇总')
        log('=' * 70)
        for engine, row in results.items():
            log(f'\n--- {engine} ---')
            for k, v in row.items():
                if k == 'tail':
                    log(f'    {k}: ...{str(v)[-200:]}')
                else:
                    log(f'    {k}: {v}')
        log(f'\n临时文件保留在: {tmp}')
    finally:
        pass

    return 0


if __name__ == '__main__':
    sys.exit(main())
