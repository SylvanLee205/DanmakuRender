"""诊断"连接着但收不到视频数据"的卡住状态。

现象：
    荞麦拌面 19:40:38 起 streamgears 进程存活、CPU 有消耗，
    但 .flv.part 一直是 0 字节，只有 .ass 在增长。
    → 弹幕通道正常，视频通道没有数据。

要查：
    1. 直接用 ffprobe 拉这个流，看抖音侧到底有没有视频数据
    2. 对比同时在录的其它任务是否正常（区分"个别主播"vs"系统问题"）
    3. 检查 biliup/streamgears 的日志尾部有没有线索
"""
import glob
import json
import os
import re
import subprocess
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）


UP = _PROJECT_ROOT
D = os.path.join(UP, '直播回放', '荞麦拌面')


def run(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=timeout)
        return r.returncode, (r.stdout or ''), (r.stderr or '')
    except subprocess.TimeoutExpired:
        return -1, '', '(超时)'


print('=' * 78)
print('1. 其它任务的 .part 是否正常增长（区分个别 vs 系统）')
print('=' * 78)
parts = []
for p in glob.glob(os.path.join(UP, '直播回放', '**', '*.flv.part'),
                   recursive=True):
    try:
        st = os.stat(p)
        parts.append((p, st.st_size, st.st_mtime))
    except Exception:
        pass
for p, sz, mt in sorted(parts, key=lambda x: -x[1]):
    task = os.path.basename(os.path.dirname(p))
    age = (time.time() - mt) / 60
    flag = '⚠️ 0字节' if sz == 0 else '✅'
    print(f'  {flag} {sz/1024/1024:>8.2f} MB  {age:>5.1f}分钟前  [{task}]')
    print(f'        {os.path.basename(p)[:70]}')

print()
print('=' * 78)
print('2. 荞麦拌面 的 .ass 在增长吗（弹幕通道）')
print('=' * 78)
ass = glob.glob(os.path.join(D, '*.ass'))
for a in ass:
    s1 = os.path.getsize(a)
    time.sleep(6)
    s2 = os.path.getsize(a) if os.path.exists(a) else 0
    print(f'  {os.path.basename(a)}')
    print(f'      {s1} → {s2} 字节  '
          f'{"✅ 弹幕在写入" if s2 > s1 else "⚠️ 无变化"}')

print()
print('=' * 78)
print('3. 从日志提取该主播的流地址，用 ffprobe 直接测有没有视频数据')
print('=' * 78)
logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
              key=os.path.getmtime, reverse=True)
url = None
for lg in logs[:2]:
    txt = open(lg, encoding='utf-8', errors='replace').read()
    txt = re.sub(r'\x1b\[[0-9;]*m', '', txt)
    for m in re.finditer(r'(http://pull-[^\s"\']+\.flv\?[^\s"\']+)', txt):
        url = m.group(1)
    if url:
        break
if url:
    print(f'  提取到流地址（前 100 字符）: {url[:100]}...')
    print()
    print('  用 ffprobe 探测（10 秒超时）:')
    rc, so, se = run(['ffprobe', '-v', 'error', '-show_entries',
                      'stream=codec_type,codec_name', '-of', 'json',
                      '-timeout', '10000000', url], timeout=40)
    print(f'      exit={rc}')
    if so.strip():
        try:
            j = json.loads(so)
            for s in (j.get('streams') or []):
                print(f'      流: {s.get("codec_type")} {s.get("codec_name")}')
        except Exception:
            print(f'      {so[:200]}')
    if se.strip():
        print(f'      stderr: {se.strip()[:250]}')
    print()
    print('  用 ffmpeg 试拉 3 秒看能收到多少:')
    rc, so, se = run(['ffmpeg', '-v', 'warning', '-i', url, '-t', '3',
                      '-f', 'null', '-'], timeout=60)
    print(f'      exit={rc}')
    if se.strip():
        for l in se.strip().split('\n')[:6]:
            print(f'      {l[:130]}')
    else:
        print('      ✅ 能正常拉流（说明流是活的）')
else:
    print('  ❌ 日志里没找到该主播的流地址')

print()
print('=' * 78)
print('4. 该主播今天的历史失败模式')
print('=' * 78)
txt = ''
for lg in logs[:1]:
    txt = re.sub(r'\x1b\[[0-9;]*m', '',
                 open(lg, encoding='utf-8', errors='replace').read())
events = []
for m in re.finditer(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})[^\]]*\]\[[^\]]*\]:\s*'
                     r'荞麦拌面[^\n]{0,80}', txt):
    events.append(m.group(0)[:120])
print(f'  该主播相关日志 {len(events)} 条，最后 12 条:')
for e in events[-12:]:
    print(f'    {e}')

print()
print('=' * 78)
print('5. 结论')
print('=' * 78)
zero = [p for p, sz, _ in parts if sz == 0]
if url and rc != 0:
    print('  ⚠️ ffmpeg 也拉不到流 → 抖音侧确实没在推视频数据')
    print('     （主播可能只推了弹幕/刚开播还没推流）')
elif zero:
    print(f'  ⚠️ 有 {len(zero)} 个 0 字节 .part —— 连接着但收不到数据')
    print('     这是"假连接"：进程活着、TCP 通，但 CDN 不送数据。')
else:
    print('  ✅ 无异常')
