"""验证 P0-1：延迟清理落盘 + 重启重 arm。

模拟真实场景：
  1. 建 3 个临时文件
  2. 用 Cleaner.add_task 派发 3 条延迟删除（delay 分别 -10s / +2s / +3600s）
  3. 检查 logs/pending_clean.json 有 3 条
  4. **模拟进程重启**：丢弃 Cleaner 实例，新建一个 → _rearm_pending 应该：
       · 已到期的 2 条立刻删除
       · 未来 1 条重新 arm 且保留在清单里
  5. 校验磁盘与清单
"""
import json
import logging
import os
import queue
import shutil
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）

sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)
logging.basicConfig(level=logging.INFO,
                    format='%(levelname)s %(message)s')

from DMR.Cleaner import Cleaner
from DMR.utils import PipeMessage, FileInfo


TMP = os.path.join('.temp', '_journal_test')
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)

JOURNAL = os.path.join(_PROJECT_ROOT + r'\logs', 'pending_clean.json')
if os.path.exists(JOURNAL):
    os.replace(JOURNAL, JOURNAL + '.bak-test')
    print(f'  备份已有清单 -> {JOURNAL}.bak-test')

names = ['a.mkv', 'b.mkv', 'c_keep.mkv']
paths = []
for n in names:
    p = os.path.abspath(os.path.join(TMP, n))
    with open(p, 'wb') as f:
        f.write(b'x' * 1024)
    paths.append(p)
print(f'  建了 {len(paths)} 个文件')

sq, rq = queue.Queue(), queue.Queue()
logger = logging.getLogger('DMR.Cleaner')

print()
print('=' * 74)
print('阶段 1：派发 3 条延迟删除')
print('=' * 74)
c1 = Cleaner(pipe=(sq, rq))
# delay: -10（已过期）/ 2（马上）/ 3600（未来）
delays = [-10, 2, 3600]
for p, d in zip(paths, delays):
    fi = FileInfo(p)
    msg = PipeMessage(source='replay/test', target='cleaner', event='newtask',
                      request_id=None,
                      data={'method': 'delete', 'delay': d,
                            'args': {'dest': None}, 'files': [fi]})
    c1.add_task(msg)
    print(f'  派发 {os.path.basename(p):12} delay={d:>6}s')

entries = json.load(open(JOURNAL, encoding='utf-8'))
print(f'  清单条数: {len(entries)}（应为 3）')
for e in entries:
    left = e['due_ts'] - time.time()
    print(f'    {os.path.basename(e["pairs"][0][0]):12} 还剩 {left:>8.1f}s')

print()
print('=' * 74)
print('阶段 2：模拟进程重启（丢弃 c1，新建 c2）')
print('=' * 74)
c1.stoped = True
del c1
time.sleep(0.1)

c2 = Cleaner(pipe=(queue.Queue(), queue.Queue()))
time.sleep(3.5)   # 等 2 秒那条到点

print()
print('=' * 74)
print('阶段 3：校验磁盘')
print('=' * 74)
for p in paths:
    exists = os.path.exists(p)
    tag = '❌ 还在' if exists else '✅ 已删'
    expect_del = 'a.mkv' != os.path.basename(p) and 'c_keep' not in os.path.basename(p)
    ok = (not exists) == expect_del
    print(f'  {tag}  {os.path.basename(p):14} {"（应删）" if expect_del else "（应保留）"} '
          f'{"← 符合" if ok else "← 不符！"}')

entries = json.load(open(JOURNAL, encoding='utf-8')) if os.path.exists(JOURNAL) else []
print(f'  清单剩余: {len(entries)} 条（应为 1，即 c_keep）')
for e in entries:
    print(f'    {os.path.basename(e["pairs"][0][0])}  还剩 {e["due_ts"]-time.time():.1f}s')

print()
print('=' * 74)
print('结论')
print('=' * 74)
a_gone = not os.path.exists(paths[0])
b_gone = not os.path.exists(paths[1])
c_kept = os.path.exists(paths[2])
c_in_journal = len(entries) == 1 and 'c_keep' in entries[0]['pairs'][0][0]
checks = [
    ('已过期的 a.mkv 被补删', a_gone),
    ('重启后到期的 b.mkv 被删', b_gone),
    ('未到期的 c_keep.mkv 保留', c_kept),
    ('c_keep 仍在清单里等待', c_in_journal),
]
for label, ok in checks:
    print(f'  {"✅" if ok else "❌"} {label}')
print()
print('  ' + ('🎉 P0-1 全部通过：重启不再丢延迟清理' if all(x[1] for x in checks)
              else '⚠️ 有未通过项，见上'))

# 清理
shutil.rmtree(TMP, ignore_errors=True)
if os.path.exists(JOURNAL):
    os.remove(JOURNAL)
if os.path.exists(JOURNAL + '.bak-test'):
    os.replace(JOURNAL + '.bak-test', JOURNAL)
    print('  已还原原清单')
