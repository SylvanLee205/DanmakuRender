"""两步渲染：先修时间轴，再烙字幕。

实测（2026-10-19）：
  · 同一文件 + 同一 ffmpeg，**不带 subtitles 滤镜** -> 3609s / 源 3602s ✅ 180 秒
  · 带 subtitles 滤镜 -> 输出时间轴被拉长到 1.67 倍，或直接崩
  结论：坏时间戳经过 libass 滤镜图时会把时间轴搞坏。

解法：分两步
  第一步：TS -> 干净 MP4（不烙字幕）。这一步修复时间轴，已实测成功。
  第二步：干净 MP4 -> 烙字幕（此时时间戳正常，滤镜图不会出问题）。
"""
import os
import subprocess
import sys
import time

os.chdir(r'F:\DanmakuRepo')

# 可从命令行传入 STEM（不传就用默认的那个）
STEM = (sys.argv[1] if len(sys.argv) > 1
        else '哭哭不嘻嘻-2026年10月19日03点39分')
SRC = f'直播回放/哭哭不嘻嘻/{STEM}.ts'
ASS = f'./直播回放/哭哭不嘻嘻/{STEM}.ass'
TMP = '.temp/_step1_clean.mp4'
FINAL = f'直播回放/哭哭不嘻嘻（弹幕版）/{STEM}（弹幕版）.mp4'


def run(cmd, label):
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=7200)
    el = time.time() - t0
    err = [l for l in (r.stderr or '').split('\n') if l.strip()]
    print(f'  {label}: exit={r.returncode}  {el:.0f}s')
    if r.returncode != 0:
        for l in err[:3]:
            print(f'     {l[:120]}')
    return r.returncode == 0


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
    src_d = dur(SRC)
    print('=' * 78)
    print('两步渲染（先修时间轴，再烙字幕）')
    print('=' * 78)
    print(f'  源: {src_d:.0f}s')
    print()

    # ── 第一步：修时间轴（不烙字幕，质量给高一点减少二次损失）──
    if os.path.exists(TMP):
        os.remove(TMP)
    print('  第一步：TS -> 干净 MP4（gq 22，为二次编码留余量）')
    ok = run(['ffmpeg', '-v', 'error', '-y',
              '-err_detect', 'ignore_err',
              '-i', SRC,
              '-c:v', 'hevc_qsv', '-preset', 'medium', '-global_quality:v', '22',
              '-tag:v', 'hvc1',
              '-c:a', 'libopus', '-b:a', '128k',
              '-movflags', '+faststart', TMP], '编码')
    if not ok:
        print('  ❌ 第一步失败')
        return 1
    d1 = dur(TMP)
    print(f'     产物 {os.path.getsize(TMP)/1024**2:.1f} MB  {d1:.0f}s  '
          f'({"✅ 时长正确" if abs(d1 - src_d) < 60 else "❌ 时长异常"})')
    if abs(d1 - src_d) > 60:
        print('  ❌ 第一步时长就不对，放弃')
        return 1

    # ── 第二步：烙字幕 ──
    print()
    print('  第二步：干净 MP4 -> 烙字幕（gq 28）')
    if os.path.exists(FINAL):
        os.remove(FINAL)
    ok = run(['ffmpeg', '-v', 'error', '-y',
              '-i', TMP,
              '-vf', f"subtitles='{ASS}'",
              '-noautoscale',
              '-c:v', 'hevc_qsv', '-preset', 'medium', '-global_quality:v', '28',
              '-tag:v', 'hvc1',
              '-c:a', 'copy',
              '-movflags', '+faststart', FINAL], '烙字幕')
    if not ok:
        print('  ❌ 第二步失败')
        return 1

    d2 = dur(FINAL)
    sz = os.path.getsize(FINAL) / 1024**2
    print()
    print('=' * 78)
    print(f'✅ 完成  {sz:.1f} MB  时长 {d2:.0f}s / 源 {src_d:.0f}s = {d2/src_d*100:.1f}%')
    print('=' * 78)

    # 完整性校验
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', FINAL, '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=3600)
    nerr = len([l for l in (r.stderr or '').split('\n') if l.strip()])
    print(f'  解码校验: exit={r.returncode} 错误 {nerr} 条  '
          f'{"✅ 可正常播放" if r.returncode == 0 else "❌"}')
    print(f'  音画: 视频 {dur(FINAL):.0f}s')

    if r.returncode == 0 and abs(d2 - src_d) < 60:
        os.remove(TMP)
        print(f'  已清理中间文件 {TMP}')
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
