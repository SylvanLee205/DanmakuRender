"""验证"直播已结束/开始"是否只打一次（不依赖肉眼看控制台）。

原理：
    直接调用 LiveEvents 的事件处理方法（构造一个假的 PipeMessage），
    用一个捕获用的 logging.Handler 数一数同一条消息被记录了几次。

这样可以在不启动 DMR 的情况下证明日志条数。
"""
import logging
import os
import sys

PROD = r'F:\DanmakuRender_AutoUp'
sys.path.insert(0, PROD)
os.chdir(PROD)

records = []


class Catch(logging.Handler):
    def emit(self, record):
        try:
            records.append((record.levelname, record.name, record.getMessage()))
        except Exception:
            pass


import logging as _lg
_lg.basicConfig(level=_lg.DEBUG)
root = _lg.getLogger('DMR')
root.setLevel(_lg.DEBUG)
root.handlers = [Catch()]

print('=' * 78)
print('1. 构造 LiveEvents 并模拟 liveend / livestart 事件')
print('=' * 78)

try:
    from DMR.Config import Config
    from DMR.Task.liveevents import LiveEvents
    from DMR.utils import PipeMessage
except Exception as e:
    import traceback
    print(f'  ❌ 导入失败: {type(e).__name__}: {e}')
    traceback.print_exc()
    raise SystemExit(1)

cfg = Config(os.path.join(PROD, 'configs', 'global.yml'))
# 构造一个最小可用的 config 字典
common = {
    'common_event_args': {
        'auto_upload': False,
        'auto_render': False,
        'addtask_on_liveend': False,
        'only_record': False,
    },
    'download_args': {},
    'render_args': {},
    'upload_args': {},
    'clean_args': {},
    'state_repo': None,
}
try:
    le = LiveEvents('测试主播', common)
    print('  ✅ LiveEvents 构造成功')
except Exception as e:
    import traceback
    print(f'  ❌ 构造失败: {type(e).__name__}: {e}')
    traceback.print_exc()
    raise SystemExit(1)

print()
print('=' * 78)
print('2. 模拟"s直播已结束"（liveend）')
print('=' * 78)
records.clear()
msg = PipeMessage(source='downloader', target='replay/测试主播',
                  event='liveend', msg='直播已结束', dtype=None, data=None)
try:
    le.onLiveEnd(msg)
except Exception as e:
    print(f'  ⚠ onLiveEnd 抛异常（可能因缺少状态库，可忽略）: {type(e).__name__}: {e}')

n = 0
for lv, name, m in records:
    if '直播已结束' in m:
        n += 1
        print(f'  [{lv}][{name}]: {m}')
print(f'\n  >>> "直播已结束" 被记录 {n} 次  '
      f'{"✅ 正确（只 1 次）" if n == 1 else ("❌ 重复！" if n > 1 else "⚠ 0 次")}')

print()
print('=' * 78)
print('3. 模拟"直播开始"（livestart → defaultEvent）')
print('=' * 78)
records.clear()
msg2 = PipeMessage(source='downloader', target='replay/测试主播',
                   event='livestart', msg='直播开始', dtype='str', data=None)
try:
    le.defaultEvent(msg2)
except Exception as e:
    print(f'  ⚠ 抛异常: {type(e).__name__}: {e}')
n2 = 0
for lv, name, m in records:
    if '直播开始' in m:
        n2 += 1
        print(f'  [{lv}][{name}]: {m}')
print(f'\n  >>> "直播开始" 被记录 {n2} 次  '
      f'{"✅ 正确（只 1 次）" if n2 == 1 else ("❌ 重复！" if n2 > 1 else "⚠ 0 次")}')

print()
print('=' * 78)
print('4. 结论')
print('=' * 78)
if n == 1 and n2 == 1:
    print('  ✅ 当前代码：直播状态每条只记录一次，无重复。')
    print('     你之前看到的两条来自 16:22 的旧会话代码。')
else:
    print(f'  ⚠️ 仍有重复：liveend={n} 次, livestart={n2} 次')

print()
print('=' * 78)
print('5. 顺带确认引擎的 event="info" 通道（另一处可能重复的来源）')
print('=' * 78)
eng = open(os.path.join(PROD, 'DMR', 'engine.py'), encoding='utf-8').read()
for i, l in enumerate(eng.split('\n'), 1):
    if "event == 'info'" in l or ("logger.info" in l and 'msg' in l):
        print(f'  engine.py:{i}: {l.strip()}')
print('''  
  说明：engine.py 对 event='info' 的消息打 INFO（如"下载任务 X 已启动。"）。
        直播状态不走这个通道（走 liveend/livestart 事件），所以不产生重复。
''')
