"""立即停止上传活动 + 清理测试残留 —— 让百度账号冷却。

诊断结论：百度返回 PermissionDenied（账号级限制），不是 CD2 的问题。
我过去几小时做了大量上传/重试/测试（加上看门狗 4 小时的反复尝试），
很可能触发了百度的临时限流。

现在要做的：
  1. 清空 CD2 上传队列（停止一切上传）
  2. 清掉我造的测试残留
  3. 记录状态，等冷却
"""
import json
import os
import shutil
import sqlite3
import subprocess
import time

NEW = os.path.join(os.environ['LOCALAPPDATA'], 'CloudDrive.WinUI')
APP = r'C:\Program Files\CloudDrive\CloudDrive.exe'
RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
TMP = os.environ['TEMP']
BK = os.path.join(r'F:\_CD2配置备份_20261005',
                  'before_queue_clear_' + time.strftime('%H%M%S'))


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 停 CD2 并备份')
print('=' * 78)
os.makedirs(BK, exist_ok=True)
for f in ('clouddrive_data.sqlite', 'clouddrive_data.sqlite-wal',
          'clouddrive_data.sqlite-shm'):
    src = os.path.join(NEW, f)
    if os.path.exists(src):
        try:
            shutil.copy2(src, BK)
        except Exception:
            pass
print(f'  已备份到 {BK}')
ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue")
time.sleep(8)
print(f'  CD2 已停')

print()
print('=' * 78)
print('2. 清空上传队列（停止一切上传）')
print('=' * 78)
db = os.path.join(NEW, 'clouddrive_data.sqlite')
try:
    con = sqlite3.connect(db, timeout=30)
    cur = con.cursor()
    cur.execute('SELECT COUNT(*) FROM transfer_tasks')
    n = cur.fetchone()[0]
    print(f'  清空前 {n} 条')
    cur.execute('SELECT filename FROM transfer_tasks')
    for (fn,) in cur.fetchall():
        print(f'    {fn}')
    cur.execute('DELETE FROM transfer_tasks')
    con.commit()
    cur.execute('SELECT COUNT(*) FROM transfer_tasks')
    print(f'  清空后 {cur.fetchone()[0]} 条')
    con.close()
except Exception as e:
    print(f'  ❌ {type(e).__name__}: {e}')

print()
print('=' * 78)
print('3. 重启 CD2（队列已空）')
print('=' * 78)
subprocess.Popen([APP, '--autostart'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for i in range(12):
    time.sleep(5)
    n = ps("(Get-NetTCPConnection -LocalPort 29798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count").strip()
    if n and n != '0':
        print(f'  ✅ CD2 就绪（{(i+1)*5} 秒）')
        break

print()
print('=' * 78)
print('4. 清理测试残留（云端 + 本地 CD2 幻影）')
print('=' * 78)
# 云端测试目录
for d in ('__torture_test__', '__speedtest__', '__limittest__', '__bwtest__',
          '__bw512__', '__cmp2__', '__probe__', '__dmr_selftest__'):
    r = subprocess.run([RCLONE, 'purge', f'cd2:百度网盘/DMR录播/{d}'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=300)
    if r.returncode == 0:
        print(f'  清理 DMR录播/{d}')
    # 也清 DMR录播 根下的（有些测试用了别的路径）
for d in ('__torture_test__', '__speedtest__'):
    subprocess.run([RCLONE, 'purge', f'cd2:百度网盘/{d}'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=300)

# 那 3 个 tmpupload / replay 幻影条目
for n in ('掉了颗兔牙-2026年10月05日21点15分（弹幕版）.tmpupload.mp4',
          '掉了颗兔牙-2026年10月05日22点15分（弹幕版）.tmpupload.mp4',
          '掉了颗兔牙-2026年10月05日22点15分（弹幕版）.replay.mp4'):
    r = subprocess.run([RCLONE, 'deletefile', f'cd2:百度网盘/DMR录播/掉了颗兔牙/{n}'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=300)
    print(f'  删除幻影条目: {n}  (exit={r.returncode})')

print()
print('=' * 78)
print('5. 最终状态')
print('=' * 78)
time.sleep(20)
print('  CD2 进程: ' + (ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | "
                    "ForEach-Object { 'PID ' + $_.Id }") or '未运行'))
try:
    con = sqlite3.connect(f'file:{os.path.join(NEW, "clouddrive_data.sqlite")}?mode=ro', uri=True)
    cur = con.cursor()
    cur.execute('SELECT COUNT(*) FROM transfer_tasks')
    print(f'  CD2 队列: {cur.fetchone()[0]} 条')
    con.close()
except Exception as e:
    print(f'  CD2 队列查询失败: {e}')

# 记录到文件供后续查询
state = {
    'time': time.strftime('%Y-%m-%d %H:%M:%S'),
    'issue': 'Baidu PermissionDenied（账号级上传限制）',
    'first_seen': '2026-10-06 13:45',
    'action': '清空上传队列，停止上传，等待冷却',
    'cooldown_until': time.strftime('%Y-%m-%d %H:%M:%S',
                                    time.localtime(time.time() + 6 * 3600)),
}
sp = r'F:\DanmakuRender_AutoUp\.temp\baidu_cooldown.json'
os.makedirs(os.path.dirname(sp), exist_ok=True)
json.dump(state, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f'\n  冷却记录已写入 {sp}')
for k, v in state.items():
    print(f'    {k} = {v}')
