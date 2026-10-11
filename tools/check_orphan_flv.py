"""检查那三个孤儿 .flv 是否有可恢复内容，能否抢救。

背景：
  哭哭不嘻嘻 目录里有三个 [正在录制]xxx.flv，从没被改名成正式分段。
  对比正常流程：streamgears 分段结束 -> "stop once" -> Rename -> livesegment
  这三个缺少 "stop once"+"Rename"，说明 streamgears 是被强制结束的
  （比如 DMR 重启、进程被杀），所以文件名留在 [正在录制] 状态。

  文件大小 848/859/109 MB —— 里面有真实录制内容，应该抢救。

检查：
  1. 用 ffprobe 看真实的流信息（时长/分辨率/是否有视频轨）
  2. 判断是可完整播放，还是尾部损坏
  3. 给出抢救方案（改名 + 走渲染上传流程）
"""
import json
import os
import shutil
import subprocess
import time

UP = r'F:\DanmakuRender_AutoUp'
D = os.path.join(UP, '直播回放', '哭哭不嘻嘻')


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


def probe_full(p):
    """详细探测：流信息 + 时长。"""
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_streams',
                        '-show_format', '-of', 'json', p],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=300)
    if r.returncode != 0:
        return None, (r.stderr or '').strip()[:300]
    try:
        return json.loads(r.stdout), None
    except Exception as e:
        return None, str(e)


print('=' * 78)
print('1. 文件基本信息')
print('=' * 78)
flvs = sorted(f for f in os.listdir(D) if f.endswith('.flv'))
for f in flvs:
    p = os.path.join(D, f)
    st = os.stat(p)
    print(f'  {f}')
    print(f'      大小 {st.st_size/1024/1024:.2f} MB   '
          f'修改 {time.strftime("%m-%d %H:%M:%S", time.localtime(st.st_mtime))}')

print()
print('=' * 78)
print('2. ffprobe 详细分析')
print('=' * 78)
for f in flvs:
    p = os.path.join(D, f)
    print(f'\n  === {f} ===')
    info, err = probe_full(p)
    if not info:
        print(f'      ❌ 无法解析: {err}')
        continue
    fmt = info.get('format') or {}
    print(f'      容器: {fmt.get("format_name")}')
    print(f'      时长: {fmt.get("duration")} 秒')
    print(f'      码率: {fmt.get("bit_rate")}')
    streams = info.get('streams') or []
    print(f'      流数: {len(streams)}')
    for s in streams:
        ct = s.get('codec_type')
        codec = s.get('codec_name')
        extra = ''
        if ct == 'video':
            extra = f' {s.get("width")}x{s.get("height")} {s.get("r_frame_rate")}'
        elif ct == 'audio':
            extra = f' {s.get("sample_rate")}Hz {s.get("channels")}ch'
        print(f'        - {ct}: {codec}{extra}')

print()
print('=' * 78)
print('3. 能否完整解码（检查尾部是否损坏）')
print('=' * 78)
for f in flvs:
    p = os.path.join(D, f)
    print(f'\n  === {f} ===')
    # 用 ffmpeg 快速解码到 null，统计错误
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', p,
                        '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=900)
    errlines = [l for l in (r.stderr or '').split('\n') if l.strip()]
    print(f'      ffmpeg exit={r.returncode}')
    print(f'      错误行数: {len(errlines)}')
    for l in errlines[:8]:
        print(f'        {l[:150]}')
    if not errlines and r.returncode == 0:
        print('      ✅ 完整可解码，无错误')

print()
print('=' * 78)
print('4. 抢救建议')
print('=' * 78)
print('''  这三个 .flv 是**真实录制内容**，只是没被改名进流程。
  抢救办法：
    1. 按 stream_downloader 的命名规则改名成正式分段：
         [正在录制]哭哭不嘻嘻-20261007223036-....flv
         -> 哭哭不嘻嘻-2026年10月07日22点30分.mkv
    2. 然后 DMR 的启动恢复（_startup_recover / recover_part.py）
       或者手动触发渲染上传

  ⚠️ 先确认文件可解码（上面第 3 步全绿再动手）
''')
