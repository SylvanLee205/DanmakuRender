"""精准清除测试任务 _引擎测试 的状态库记录。

只删该 session 的行，不动其它任务。先备份整个库。
"""
import os
import shutil
import sqlite3
import time

DB = r'F:\DanmakuRender_AutoUp\logs\dmr_state.db'
TASK = '_引擎测试'

bak = DB + '.bak-purge-' + time.strftime('%Y%m%d-%H%M%S')
shutil.copy2(DB, bak)
print(f'  已备份 -> {os.path.basename(bak)}  ({os.path.getsize(bak)/1024:.0f} KB)')

conn = sqlite3.connect(DB, timeout=60)
cur = conn.cursor()

# 1) 找出该任务的 session
cur.execute('SELECT session_id, taskname, streamer_name FROM sessions WHERE taskname=?', (TASK,))
rows = cur.fetchall()
print(f'  找到 {len(rows)} 个 session:')
for sid, tn, sn in rows:
    print(f'    {sid}  {tn}  {sn}')

session_ids = [r[0] for r in rows]
if not session_ids:
    print('  没有需要清除的 session')
    conn.close()
    raise SystemExit(0)

# 2) 逐个删除 artifacts / sessions / upload_groups
total_art = 0
for sid in session_ids:
    cur.execute('SELECT COUNT(*) FROM artifacts WHERE session_id=?', (sid,))
    n = cur.fetchone()[0]
    cur.execute('DELETE FROM artifacts WHERE session_id=?', (sid,))
    total_art += n
    print(f'    删除 artifacts(session={sid}): {n} 行')

cur.execute('DELETE FROM sessions WHERE taskname=?', (TASK,))
print(f'    删除 sessions(taskname={TASK}): {cur.rowcount} 行')

cur.execute('DELETE FROM upload_groups WHERE taskname=?', (TASK,))
print(f'    删除 upload_groups(taskname={TASK}): {cur.rowcount} 行')

conn.commit()

# 3) 校验
print()
print('  校验:')
cur.execute('SELECT COUNT(*) FROM sessions WHERE taskname=?', (TASK,))
print(f'    仍存在的 {TASK} session: {cur.fetchone()[0]}（应为 0）')
cur.execute('SELECT taskname, COUNT(*) FROM sessions GROUP BY taskname ORDER BY taskname')
rows = cur.fetchall()
print(f'    剩余任务数: {len(rows)}')
for tn, n in rows:
    print(f'      {tn:14} {n} 个 session')
cur.execute('PRAGMA integrity_check')
print(f'    库完整性: {cur.fetchone()[0]}')
conn.close()
print()
print('  完成。')
