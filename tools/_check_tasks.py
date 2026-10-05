"""查 CD2 的 transfer_tasks 表，看是否有卡死任务占住上传槽。"""
import os
import shutil
import sqlite3

CD2 = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'
TMP = os.environ['TEMP']
dst = os.path.join(TMP, 'cd2_data_probe')
os.makedirs(dst, exist_ok=True)
for s in ('', '-wal', '-shm'):
    src = os.path.join(CD2, 'clouddrive_data.sqlite' + s)
    if os.path.exists(src):
        try:
            shutil.copy2(src, os.path.join(dst, 'clouddrive_data.sqlite' + s))
        except Exception as e:
            print(f'  复制 {s} 失败: {e}')

db = os.path.join(dst, 'clouddrive_data.sqlite')
con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
cur = con.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('表:', [r[0] for r in cur.fetchall()])
print()

cur.execute('PRAGMA table_info(transfer_tasks)')
cols = [r[1] for r in cur.fetchall()]
print('transfer_tasks 列:', cols)
print()

cur.execute('SELECT COUNT(*) FROM transfer_tasks')
print(f'总任务数: {cur.fetchone()[0]}')
print()

# 尽量挑有用的列显示
want = [c for c in ('id', 'task_type', 'status', 'dest_path', 'dest_file_name',
                    'file_name', 'size', 'created_at', 'updated_at',
                    'error_message', 'retry_count', 'progress') if c in cols]
sel = ', '.join(want) if want else '*'
cur.execute(f'SELECT {sel} FROM transfer_tasks')
rows = cur.fetchall()
print(f'=== 所有上传任务（{len(rows)} 条）===')
for r in rows:
    d = dict(zip(want, r))
    print('  ---')
    for k, v in d.items():
        if isinstance(v, str) and len(v) > 90:
            v = v[:90] + '...'
        print(f'      {k}: {v}')

con.close()
