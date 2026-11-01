"""查清 哭哭不嘻嘻 三个 [正在录制] 文件的关系。

要回答的问题：
  1. 这三个文件分别属于哪个分段？
  2. 为什么 .ass 的名字是 20261007-232039（Part000 格式），
     而 .part 是 20261007232039（时间戳+hash 格式）？两者是一对吗？
  3. 有没有"孤儿"文件（没有配对 .part 的 .ass）？
  4. 当前录制的分段到底是哪个？
"""
import os
import time

D = r'F:\DanmakuRepo\直播回放\哭哭不嘻嘻'


def snap():
    rows = []
    for f in sorted(os.listdir(D)):
        p = os.path.join(D, f)
        if not os.path.isfile(p):
            continue
        st = os.stat(p)
        rows.append((f, st.st_size, st.st_mtime))
    return rows


print('=' * 78)
print('1. 目录全部文件')
print('=' * 78)
for f, sz, mt in snap():
    print(f'  {sz/1024/1024:>10.2f} MB  {time.strftime("%m-%d %H:%M:%S", time.localtime(mt))}  {f}')

print()
print('=' * 78)
print('2. 文件名解析：找出"配对关系"')
print('=' * 78)
import re
files = [f for f, _, _ in snap()]
parts = {}   # 代号 -> {part: , ass: }
for f in files:
    # .part 形如 [正在录制]哭哭不嘻嘻-20261007223036-a9470204c25b11f1.flv.part
    m = re.match(r'\[正在录制\]哭哭不嘻嘻-(\d{14})-([0-9a-f]+)\.flv\.part$', f)
    if m:
        parts.setdefault(m.group(1), {})['part'] = f
        continue
    # .ass 形如 [正在录制]哭哭不嘻嘻-20261007-232039-Part000.ass
    m = re.match(r'\[正在录制\]哭哭不嘻嘻-(\d{8})-(\d{6})-Part(\d+)\.ass$', f)
    if m:
        key = m.group(1) + m.group(2)
        parts.setdefault(key, {})['ass'] = f
        continue

for key in sorted(parts):
    d = parts[key]
    t = time.strftime('%Y-%m-%d %H:%M:%S',
                      time.strptime(key, '%Y%m%d%H%M%S')) if len(key) == 14 else key
    have = []
    if 'part' in d: have.append('.flv.part')
    if 'ass' in d: have.append('.ass')
    print(f'  分段 {key}  ({t})  有: {", ".join(have)}')
    for k, v in d.items():
        p = os.path.join(D, v)
        print(f'      {k:6} {os.path.getsize(p):>12} 字节  {v}')

print()
print('=' * 78)
print('3. 当前 streamgears 进程对应的分段')
print('=' * 78)
import subprocess


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


out = ps("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*streamgears_wrapper*' -and "
         "$_.CommandLine -like '*哭哭*' } | "
         "ForEach-Object { $_.ProcessId.ToString() + '@@' + $_.CommandLine }")
for block in out.split('\n'):
    if '@@' not in block:
        continue
    pid, cl = block.split('@@', 1)
    # 提取 -o 参数（输出模板）
    m = re.search(r'-o\s+(\S+)', cl)
    if m:
        print(f'  PID {pid}:  输出模板 = {m.group(1)}')

print()
print('=' * 78)
print('4. 关键：.ass 还在被写入吗（等 25 秒）')
print('=' * 78)
ass = [f for f in files if f.endswith('.ass') and '正在录制' in f]
for f in ass:
    p = os.path.join(D, f)
    s1, m1 = os.path.getsize(p), os.path.getmtime(p)
    time.sleep(12)
    s2, m2 = os.path.getsize(p), os.path.getmtime(p)
    active = (s2 > s1) or (m2 > m1)
    print(f'  {f}')
    print(f'      {s1} -> {s2} 字节   '
          f'{time.strftime("%H:%M:%S", time.localtime(m1))} -> '
          f'{time.strftime("%H:%M:%S", time.localtime(m2))}')
    print(f'      {"✅ 正在写入（属于当前录制）" if active else "⚠️ 无写入（可能是孤儿）"}')

print()
print('=' * 78)
print('5. .part 还在增长吗')
print('=' * 78)
for f in files:
    if f.endswith('.flv.part'):
        p = os.path.join(D, f)
        s1 = os.path.getsize(p)
        time.sleep(12)
        s2 = os.path.getsize(p)
        print(f'  {f[:60]}')
        print(f'      {s1/1024/1024:.2f} -> {s2/1024/1024:.2f} MB  '
              f'({(s2-s1)/1024:.0f} KB)  '
              f'{"✅ 增长" if s2 > s1 else "⚠️ 未增长"}')
