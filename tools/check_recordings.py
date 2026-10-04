"""快速检查已录制文件的完整性（不做全帧扫描，秒级完成）。

完整性问题主要看这几项：
  - 能否打开、能否读到视频流
  - 容器时长 vs 视频流时长是否一致（截断会出现差异）
  - 文件大小是否与时长成比例（码率异常低说明大量丢帧/花屏）
  - 对 mkv 做一次真正的解码测试（解码前 60 秒，验证数据可解）
"""
import glob
import json
import os
import subprocess
import sys

FFPROBE = r'C:\User Program Files\FFmpeg\bin\ffprobe.exe'
FFMPEG = r'C:\User Program Files\FFmpeg\bin\ffmpeg.exe'
ROOT = r'F:\DanmakuRender_AutoUp\直播回放'


def probe(path, timeout=60):
    try:
        out = subprocess.check_output([
            FFPROBE, '-v', 'error', '-print_format', 'json',
            '-show_format', '-show_streams', path,
        ], stderr=subprocess.STDOUT, timeout=timeout)
        return json.loads(out.decode('utf-8', 'replace'))
    except subprocess.TimeoutExpired:
        return {'error': 'ffprobe 超时'}
    except Exception as e:
        return {'error': str(e)[:80]}


def decode_test(path, seconds=30):
    """真解码一小段，验证数据可用（不输出文件）。"""
    try:
        r = subprocess.run([
            FFMPEG, '-v', 'error', '-t', str(seconds), '-i', path,
            '-f', 'null', '-',
        ], capture_output=True, timeout=180)
        err = r.stderr.decode('utf-8', 'replace').strip()
        return ('OK' if r.returncode == 0 else 'FAIL'), err[:120]
    except subprocess.TimeoutExpired:
        return 'TIMEOUT', ''
    except Exception as e:
        return 'ERROR', str(e)[:80]


def main():
    videos = []
    for ext in ('*.mkv', '*.mp4', '*.flv'):
        videos += glob.glob(os.path.join(ROOT, '**', ext), recursive=True)
    videos = [v for v in videos if not v.endswith('.part')]
    videos.sort(key=os.path.getsize, reverse=True)

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    print(f'共 {len(videos)} 个视频，检查最大的 {limit} 个\n', flush=True)
    print(f'{"文件":<44}{"MB":>7}{"时长s":>8}{"分辨率":>11}{"码率M":>7}{"解码":>7}  备注')
    print('-' * 100, flush=True)

    problems = []
    for path in videos[:limit]:
        name = os.path.relpath(path, ROOT)
        if len(name) > 42:
            name = '...' + name[-39:]
        size_mb = os.path.getsize(path) / 1024 / 1024
        info = probe(path)
        if 'error' in info:
            print(f'{name:<44}{size_mb:>7.1f}{"-":>8}{"-":>11}{"-":>7}{"打不开":>7}  {info["error"]}', flush=True)
            problems.append((name, info['error']))
            continue

        fmt = info.get('format', {})
        dur = float(fmt.get('duration', 0) or 0)
        br = float(fmt.get('bit_rate', 0) or 0) / 1e6
        vs = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), {})
        as_ = next((s for s in info.get('streams', []) if s.get('codec_type') == 'audio'), None)
        res = f"{vs.get('width')}x{vs.get('height')}"
        vs_dur = float(vs.get('duration', 0) or 0)

        status, err = decode_test(path)
        note = []
        if as_ is None:
            note.append('无音频')
            problems.append((name, '无音频流'))
        if vs_dur and dur and abs(vs_dur - dur) > 5:
            note.append(f'时长不一致(流{vs_dur:.0f}s/容器{dur:.0f}s)')
            problems.append((name, '时长不一致'))
        if status != 'OK':
            note.append(f'解码异常:{err[:50]}')
            problems.append((name, f'解码{status}'))
        if br and br < 1.0 and dur > 60:
            note.append('码率偏低')
        print(f'{name:<44}{size_mb:>7.1f}{dur:>8.1f}{res:>11}{br:>7.2f}{status:>7}  {" ".join(note)}', flush=True)

    print()
    print(f'发现问题的文件: {len(problems)}')
    for n, p in problems:
        print(f'  - {n}: {p}')


if __name__ == '__main__':
    main()
