"""统计各录制引擎的历史使用次数与报错次数，用于比较稳定性。

只读日志，不修改任何文件。
"""
import glob
import re
from collections import Counter, defaultdict

LOGS = sorted(glob.glob(r'F:\DanmakuRender_AutoUp\logs\DMR-*.log'))

# 每种引擎的启动日志特征 -> 引擎名
START_PATTERNS = [
    (re.compile(r'\[streamgears\]\[debug\]: Stream-gears downloader args'), 'streamgears'),
    (re.compile(r'\[ffmpeg\]\[debug\]: (FFmpeg|ffmpeg) downloader args'), 'ffmpeg'),
    (re.compile(r'FFmpeg downloader args'), 'ffmpeg'),
    (re.compile(r'\[pyrequests\]\[debug\]'), 'pyrequests'),
    (re.compile(r'\[streamlink\]\[debug\]: Streamlink downloader args'), 'streamlink'),
]

# 每种引擎的失败特征
FAIL_PATTERNS = [
    (re.compile(r'Stream-gears 异常退出'), 'streamgears'),
    (re.compile(r'Streamlink 异常退出'), 'streamlink'),
    (re.compile(r'_(pyrequests|pyRequests)[^\n]*异常|pyrequests[^\n]*异常'), 'pyrequests'),
]

starts = Counter()
fails = Counter()
starts_by_day = defaultdict(Counter)
fails_by_day = defaultdict(Counter)
day_re = re.compile(r'^\[(\d{4}-\d{2}-\d{2})')

# streamgears 的详细失败原因分类
sg_reasons = Counter()
reason_pats = [
    (re.compile(r'overflow when subtracting durations'), 'Rust panic: 时间戳溢出'),
    (re.compile(r'Unexpected script tag'), 'FLV: Unexpected script tag'),
    (re.compile(r'Non-monotonous DTS'), 'FLV: 时间戳回退'),
    (re.compile(r'Different h264 sequence header'), 'FLV: h264 序列头变化'),
    (re.compile(r'Connection reset|connection reset'), '连接被重置'),
    (re.compile(r'Timed out|timeout|Timeout'), '超时'),
    (re.compile(r'Done\.\.\.'), '正常结束 Done'),
]

for path in LOGS:
    day = re.search(r'DMR-(\d{8})', path)
    day = day.group(1) if day else '?'
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            for pat, eng in START_PATTERNS:
                if pat.search(line):
                    starts[eng] += 1
                    starts_by_day[day][eng] += 1
                    break
            for pat, eng in FAIL_PATTERNS:
                if pat.search(line):
                    fails[eng] += 1
                    fails_by_day[day][eng] += 1
                    break
            if 'Stream-gears 异常退出' in line:
                for pat, label in reason_pats:
                    if pat.search(line):
                        sg_reasons[label] += 1
                        break
                else:
                    sg_reasons['(其他/无有效信息)'] += 1

print('=== 各引擎历史启动次数（= 跑了多少次录制）===')
tot = sum(starts.values())
for eng, c in starts.most_common():
    print(f'  {eng:<14} {c:>6} 次   ({c/tot*100:5.1f}%)')

print()
print('=== 各引擎失败次数（"异常退出"类）===')
for eng in starts:
    c = fails.get(eng, 0)
    s = starts[eng]
    rate = f'{c/s*100:.1f}%' if s else 'n/a'
    print(f'  {eng:<14} 失败 {c:>5} / 启动 {s:>5}  =  {rate}')

print()
print('=== Stream-gears 失败原因分类 ===')
for label, c in sg_reasons.most_common():
    print(f'  {c:>5}  {label}')

print()
print('=== 按月的引擎使用趋势 ===')
months = defaultdict(Counter)
for day, cnt in starts_by_day.items():
    months[day[:6]].update(cnt)
for m in sorted(months):
    row = ', '.join(f'{k}:{v}' for k, v in months[m].most_common())
    fr = sum(fails_by_day[d][e] for d in fails_by_day if d[:6] == m for e in fails_by_day[d])
    print(f'  {m}  启动 {sum(months[m].values()):>4}  失败 {fr:>4}   ({row})')
