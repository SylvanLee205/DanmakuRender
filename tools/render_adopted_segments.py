"""渲染并上传「接管回来的孤儿分段」。

背景（2026-10-19）：重启 DMR 不会杀掉旧的 ffmpeg，产生孤儿进程重复录制。
孤儿文件已被 tools/recover_ffmpeg_segments.py 改名入库，但它们**不在状态库**里，
DMR 不会自动处理，所以这里手动走一遍 DMR 渲染管线 + rclone 上传。

用法：python tools/render_adopted_segments.py [--upload]
"""
import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, r'F:\DanmakuRender_AutoUp')
os.chdir(r'F:\DanmakuRender_AutoUp')
import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')

from DMR.Config import Config
from DMR.Render.dmrender import DmRender
from DMR.utils import VideoInfo, StreamerInfo

TASK = '哭哭不嘻嘻'
STREAMER = '哭哭不嘻嘻'
VDIR = os.path.join('直播回放', TASK)
ODIR = os.path.join('直播回放', TASK + '（弹幕版）')

# 要处理的分段（stems，不含扩展名）
STEMS = [
    '哭哭不嘻嘻-2026年10月19日03点39分-Part001',   # 1298 MB
    '哭哭不嘻嘻-2026年10月19日05点29分',            # 122.8 MB
    '哭哭不嘻嘻-2026年10月19日05点34分',            # 163.3 MB
]

RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
REMOTE = 'cd2:百度网盘/DMR录播/' + TASK


def dur(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                        'format=duration', '-of', 'default=nw=1:nk=1', p],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=300)
    try:
        return float((r.stdout or '0').strip() or 0)
    except ValueError:
        return 0.0


def ass_last(ass):
    """弹幕最后时间戳 —— 最可靠的时长基准（FLV/TS 容器时长都可能不准）。"""
    import re
    last = 0.0
    pat = re.compile(r'^Dialogue:[^,]*,\s*(\d+):(\d+):(\d+)\.(\d+)')
    try:
        with open(ass, encoding='utf-8', errors='replace') as f:
            for line in f:
                m = pat.match(line)
                if m:
                    h, mi, s, cs = (int(m.group(1)), int(m.group(2)),
                                    int(m.group(3)), int(m.group(4)))
                    last = max(last, h * 3600 + mi * 60 + s + cs / 100.0)
    except Exception:
        pass
    return last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--upload', action='store_true', help='渲染完顺带上传')
    args = ap.parse_args()

    cfg = Config(os.path.join(r'F:\DanmakuRender_AutoUp', 'configs', 'global.yml'))
    r = DmRender(**cfg.global_config['render_args']['dmrender'])

    print('=' * 78)
    print(f'渲染接管的孤儿分段（{len(STEMS)} 个）')
    print('=' * 78)
    print(f'  主编码器:   {r.vencoder}')
    print(f'  降级编码器: {r.fallback_vencoder}')
    print(f'  硬件重试:   {r.hw_retry} 次，间隔 {r.hw_retry_delay:.0f}s')
    print()

    os.makedirs(ODIR, exist_ok=True)
    results = []

    for stem in STEMS:
        src = os.path.join(VDIR, stem + '.ts')
        ass = os.path.join(VDIR, stem + '.ass')
        out = os.path.join(ODIR, stem + '（弹幕版）.mp4')

        print('-' * 78)
        print(f'  {stem}')
        if not os.path.exists(src):
            print(f'    ❌ 源文件不存在: {src}')
            results.append((stem, 'no-src', 0, 0))
            continue
        if not os.path.exists(ass):
            print(f'    ❌ 弹幕文件不存在: {ass}')
            results.append((stem, 'no-ass', 0, 0))
            continue

        ref = ass_last(ass)
        print(f'    源 {os.path.getsize(src)/1024**2:.1f} MB   弹幕参考时长 {ref:.0f}s ({ref/60:.1f}min)')

        if os.path.exists(out):
            od = dur(out)
            if ref > 0 and od / ref >= 0.9:
                print(f'    ⏭  产物已存在且时长正常（{os.path.getsize(out)/1024**2:.1f} MB），跳过渲染')
                results.append((stem, 'exists', os.path.getsize(out), od))
                if args.upload:
                    _upload(out, stem)
                continue
            print(f'    🔄 已有产物时长异常（{od:.0f}s / {ref:.0f}s），删掉重渲染')
            os.remove(out)

        vi = VideoInfo(path=src, dm_file_id=ass,
                       streamer=StreamerInfo(name=STREAMER),
                       taskname=TASK, dtype='src_video')
        t0 = time.time()
        status, info = r.render_one(video=vi, output=out)
        el = time.time() - t0

        if status:
            sz = os.path.getsize(out)
            od = dur(out)
            ratio = (od / ref * 100) if ref else 0
            print(f'    ✅ 渲染成功  {el/60:.1f} 分钟  {sz/1024**2:.1f} MB  '
                  f'产物 {od:.0f}s / 参考 {ref:.0f}s = {ratio:.1f}%')
            results.append((stem, 'ok', sz, od))
            if args.upload:
                _upload(out, stem)
        else:
            print(f'    ❌ 渲染失败  {el/60:.1f} 分钟')
            print(f'       {str(info)[:400]}')
            results.append((stem, 'fail', 0, 0))

    print()
    print('=' * 78)
    print('汇总')
    print('=' * 78)
    for stem, st, sz, od in results:
        tag = {'ok': '✅', 'exists': '✅', 'fail': '❌',
               'no-src': '⚠️', 'no-ass': '⚠️'}.get(st, '?')
        print(f'  {tag} {st:8} {sz/1024**2:8.1f} MB  {od:6.0f}s  {stem}')


def _upload(path, stem):
    print(f'    ⬆  上传到 {REMOTE}')
    try:
        r = subprocess.run([RCLONE, 'copy', path, REMOTE,
                            '--retries', '5', '--low-level-retries', '10',
                            '--transfers', '1', '--stats-one-line'],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=3600)
        if r.returncode == 0:
            chk = subprocess.run([RCLONE, 'lsf', REMOTE, '--files-only'],
                                 capture_output=True, text=True, encoding='utf-8',
                                 errors='replace', timeout=300)
            hit = os.path.basename(path) in (chk.stdout or '')
            print(f'       {"✅ 云端已确认" if hit else "⚠️ 上传成功但云端没找到"}')
        else:
            print(f'       ❌ rclone exit={r.returncode}  {(r.stderr or "")[:200]}')
    except Exception as e:
        print(f'       ❌ 上传异常: {type(e).__name__}: {e}')


if __name__ == '__main__':
    main()
