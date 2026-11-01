"""容错重渲染 Part001（1298 MB / 3498 秒）。

背景：
  · 上一次失败链路 = QSV 失败（GPU 被批量转码占满）→ 降级 libx265 → x265 访问冲突崩溃
  · 现在用户的批量转码已完成，GPU 完全空闲（实测活跃编码引擎 0）
  · 所以先按原样再试一次 QSV；同时加入输入侧容错参数，
    让坏帧被跳过而不是让编码器崩掉

容错参数（都是输入侧选项，通过 hwaccel_args 注入到 -i 之前）：
  -err_detect ignore_err   解码错误不复位、不中止
  -fflags +discardcorrupt+genpts  丢弃损坏帧并重建时间戳
"""
import os
import subprocess
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）

sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)
import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')

from DMR.Config import Config
from DMR.Render.dmrender import DmRender
from DMR.utils import VideoInfo, StreamerInfo


def _tool(name):
    """定位外部工具：环境变量 -> tools/ -> PATH -> 注册表 PATH -> 安装目录。

    见 DMR/utils/toolsmgr.py。不写死版本号和安装位置 ——
    换个 rclone 版本、换台电脑都不用改代码。
    """
    import os as _o
    import sys as _s
    _root = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
    if _root not in _s.path:
        _s.path.insert(0, _root)
    from DMR.utils.toolsmgr import find_tool
    return find_tool(name) or name


TASK = '哭哭不嘻嘻'
STEM = '哭哭不嘻嘻-2026年10月19日03点39分-Part001'
SRC = os.path.join('直播回放', TASK, STEM + '.ts')
ASS = os.path.join('直播回放', TASK, STEM + '.ass')
OUT = os.path.join('直播回放', TASK + '（弹幕版）', STEM + '（弹幕版）.mp4')
RCLONE = _tool('rclone')
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


def main():
    if not os.path.exists(SRC):
        print(f'  ❌ 源不存在: {SRC}')
        return 1

    cfg = Config(os.path.join(_PROJECT_ROOT, 'configs', 'global.yml'))
    ra = dict(cfg.global_config['render_args']['dmrender'])

    # 输入侧容错：hwaccel_args 会被插在 -i 之前
    ra['hwaccel_args'] = ['-err_detect', 'ignore_err',
                          '-fflags', '+discardcorrupt+genpts']

    r = DmRender(**ra)
    src_dur = dur(SRC)
    print('=' * 78)
    print('容错重渲染')
    print('=' * 78)
    print(f'  源:       {SRC}')
    print(f'  源大小:   {os.path.getsize(SRC)/1024**2:.1f} MB')
    print(f'  源时长:   {src_dur:.0f}s ({src_dur/60:.1f} min)')
    print(f'  主编码器: {r.vencoder}（GPU 已空闲，先试硬件）')
    print(f'  降级:     {r.fallback_vencoder}')
    print(f'  容错参数: {ra["hwaccel_args"]}')
    print()

    if os.path.exists(OUT):
        print(f'  删除旧产物: {os.path.getsize(OUT)/1024**2:.1f} MB')
        os.remove(OUT)

    vi = VideoInfo(path=SRC, dm_file_id=ASS,
                   streamer=StreamerInfo(name=TASK),
                   taskname=TASK, dtype='src_video')

    t0 = time.time()
    status, info = r.render_one(video=vi, output=OUT)
    el = time.time() - t0

    print()
    print('=' * 78)
    print(f'结果: {"✅ 成功" if status else "❌ 失败"}   耗时 {el/60:.1f} 分钟')
    print('=' * 78)

    if not status:
        print(f'  {str(info)[:600]}')
        return 1

    sz = os.path.getsize(OUT)
    od = dur(OUT)
    ratio = (od / src_dur * 100) if src_dur else 0
    print(f'  产物: {sz/1024**2:.1f} MB')
    print(f'  时长: {od:.0f}s / 源 {src_dur:.0f}s = {ratio:.1f}%')
    print(f'  {"✅ 完整" if ratio >= 90 else "⚠️ 偏短，需要检查"}')

    print()
    print(f'  上传到 {REMOTE} ...')
    up = subprocess.run([RCLONE, 'copy', OUT, REMOTE,
                         '--retries', '5', '--low-level-retries', '10',
                         '--transfers', '1', '--stats-one-line'],
                        capture_output=True, text=True, encoding='utf-8',
                        errors='replace', timeout=3600)
    if up.returncode == 0:
        chk = subprocess.run([RCLONE, 'lsf', REMOTE, '--files-only'],
                             capture_output=True, text=True, encoding='utf-8',
                             errors='replace', timeout=300)
        hit = os.path.basename(OUT) in (chk.stdout or '')
        print(f'  {"✅ 云端已确认" if hit else "⚠️ 上传成功但云端没找到"}')
    else:
        print(f'  ❌ rclone exit={up.returncode}  {(up.stderr or "")[:300]}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
