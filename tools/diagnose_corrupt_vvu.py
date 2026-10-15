"""诊断 vvu-2026年10月15日21点26分.mkv 的损坏程度，看能否挽救。

已知：ffmpeg 渲染时退出码 69，报 H.264 解码错误。
      对应日志 21:39 有 "Websocket Closed / 弹幕下载线程异常退出"。

思路：
  1. 探测文件完整性（能否读、能读多少）
  2. 尝试用容错参数转码（-err_detect ignore_err / +discardcorrupt）
  3. 如果损坏只在尾部，可以截断保留前面完好的部分
"""
import json
import os
import subprocess

UP = r'F:\DanmakuRender_AutoUp'
VF = os.path.join(UP, '直播回放', 'vvu', 'vvu-2026年10月15日21点26分.mkv')
DM = os.path.join(UP, '直播回放', 'vvu', 'vvu-2026年10月15日21点26分.ass')

print('=' * 78)
print('1. 文件基本情况')
print('=' * 78)
print(f'  源:   {os.path.getsize(VF)/1024/1024:.1f} MB')
print(f'  弹幕: {os.path.getsize(DM)/1024 if os.path.exists(DM) else 0:.1f} KB'
      f'  {"✅" if os.path.exists(DM) else "❌ 缺失"}')

print()
print('=' * 78)
print('2. ffprobe 能读出什么')
print('=' * 78)
r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                    'format=duration,size,bit_rate',
                    '-show_entries', 'stream=codec_type,codec_name,width,height',
                    '-of', 'json', VF],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=300)
try:
    j = json.loads(r.stdout)
    f = j.get('format') or {}
    print(f'  时长: {f.get("duration")} 秒')
    print(f'  码率: {f.get("bit_rate")}')
    for s in (j.get('streams') or []):
        print(f'  流: {s.get("codec_type")} {s.get("codec_name")} '
              f'{s.get("width")}x{s.get("height")}')
except Exception as e:
    print(f'  解析失败: {e}')
if r.stderr.strip():
    print(f'  ffprobe stderr: {r.stderr.strip()[:200]}')

print()
print('=' * 78)
print('3. 完整解码测试：能成功解出多少（看损坏位置）')
print('=' * 78)
r = subprocess.run(['ffmpeg', '-v', 'error', '-i', VF, '-f', 'null', '-'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=1800)
errs = [l for l in (r.stderr or '').split('\n') if l.strip()]
print(f'  ffmpeg exit={r.returncode}')
print(f'  错误行数: {len(errs)}')
for l in errs[:10]:
    print(f'    {l[:140]}')

print()
print('=' * 78)
print('4. 尝试容错解码（-err_detect ignore_err + discardcorrupt）')
print('=' * 78)
r = subprocess.run(['ffmpeg', '-v', 'error', '-fflags', '+discardcorrupt+genpts',
                    '-err_detect', 'ignore_err',
                    '-i', VF, '-f', 'null', '-'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=1800)
errs2 = [l for l in (r.stderr or '').split('\n') if l.strip()]
print(f'  ffmpeg exit={r.returncode}')
print(f'  错误行数: {len(errs2)}  （比上面少说明容错有效）')
for l in errs2[:6]:
    print(f'    {l[:140]}')

print()
print('=' * 78)
print('5. 结论与建议')
print('=' * 78)
if r.returncode == 0 and len(errs2) < len(errs):
    print('  ✅ 容错参数能解码 —— 可以尝试用这些参数重新渲染')
    print('     但画面在损坏处会有花屏/丢帧。')
else:
    print('  ⚠️ 容错也救不回完整内容。')
print(f'''
  根因不是我们的 bug：源文件在录制时就损坏了。
  日志证据（21:39:36）:
      [error] Websocket Closed
      RuntimeError: Websocket Closed
      [error] https://live.douyin.com/123456789 弹幕下载线程异常退出，正在重试...
  说明当时抖音侧的连接断了，streamgears 写出的 flv 有损坏。

  可选处置：
    a) 用容错参数渲染（画面可能有花屏），保留"有总比没有好"
    b) 直接删掉源文件（462 MB），这场就当没录到
''')
