"""补传 相扑猫 的 5 个 emoji 文件（走修复后的 SubprocessUploader）。

特点：
  - 用真实的 SubprocessUploader，所以走的是修复后的 copyto + 改名逻辑
  - 每个文件传完都等 CD2 异步上传，然后核对云端真实列表
  - 全程记录 CD2 日志，确认没有 errno -7
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）

sys.path.insert(0, _PROJECT_ROOT)
import logging
logging.basicConfig(level=logging.WARNING, format='    [%(levelname)s] %(message)s')

from DMR.Uploader.subprocess_uploader import SubprocessUploader, safe_remote_name, has_bad_remote_chars
from DMR.utils import VideoInfo, StreamerInfo


def _tool(name):
    """定位外部工具：环境变量 -> tools/ -> PATH -> 注册表 PATH -> 安装目录。

    见 DMR/utils/toolsmgr.py。不写死版本号和安装位置 ——
    换个 rclone 版本、换台电脑都不用改代码。
    """
    import os as _o
    import sys as _s
    _root = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
    if _root not in _s.path:
        _s.path.insert(0, _root)
    from DMR.utils.toolsmgr import find_tool
    return find_tool(name) or name


RCLONE = _tool('rclone')
UP = _PROJECT_ROOT
TASK = '相扑猫'
LOCAL_DIR = os.path.join(UP, '直播回放', f'{TASK}（弹幕版）')
REMOTE_DIR = f'cd2:百度网盘/DMR录播/{TASK}'
CD2_LOG_DIR = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2\log'
CD2_DATA = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'
TMP = os.environ['TEMP']


def log_size():
    p = os.path.join(CD2_LOG_DIR, time.strftime('%Y-%m-%d') + '.log')
    return os.path.getsize(p) if os.path.exists(p) else 0


def log_tail(n):
    p = os.path.join(CD2_LOG_DIR, time.strftime('%Y-%m-%d') + '.log')
    if not os.path.exists(p):
        return ''
    with open(p, 'rb') as f:
        f.seek(n)
        return f.read().decode('utf-8', 'replace')


def cloud_list():
    """从 CD2 缓存读云端真实条目（绕过 WebDAV 幻影层）。"""
    dst = os.path.join(TMP, 'cd2cache_reup')
    os.makedirs(dst, exist_ok=True)
    for s in ('', '-wal', '-shm'):
        src = os.path.join(CD2_DATA, 'dir_cache.sqlite' + s)
        if os.path.exists(src):
            try:
                shutil.copy2(src, os.path.join(dst, 'dir_cache.sqlite' + s))
            except Exception:
                pass
    try:
        con = sqlite3.connect(f'file:{os.path.join(dst, "dir_cache.sqlite")}?mode=ro', uri=True)
        cur = con.cursor()
        cur.execute("SELECT id FROM files WHERE name=?", (TASK,))
        row = cur.fetchone()
        if not row:
            con.close()
            return set()
        cur.execute("SELECT name FROM files WHERE parent_id=?", (row[0],))
        r = set(x[0] for x in cur.fetchall())
        con.close()
        return r
    except Exception as e:
        print(f'    (查缓存失败: {e})')
        return set()


files = sorted(os.path.join(LOCAL_DIR, f) for f in os.listdir(LOCAL_DIR) if f.endswith('.mp4'))
print('=' * 78)
print(f'补传 {TASK} 的 {len(files)} 个文件')
print('=' * 78)
print(f'\n上传前云端真实条目: {sorted(cloud_list()) or "(无)"}\n')

up = SubprocessUploader()
CMD = [RCLONE, 'copy', '{PATH}', REMOTE_DIR + '/{TASKNAME}', '--retries', '3']

ok_n = 0
for path in files:
    name = os.path.basename(path)
    mb = os.path.getsize(path) / 1024 / 1024
    expect = safe_remote_name(name)
    mark = log_size()

    print(f'--- {name}')
    print(f'    {mb:.1f} MB')
    print(f'    预期远程名: {expect}')
    print(f'    含 emoji: {has_bad_remote_chars(name)}')

    vi = VideoInfo(path=path, taskname=TASK, dtype='dm_video',
                   streamer=StreamerInfo(name=TASK))
    status, message = up.call_subprocess(vi, command=CMD)
    print(f'    上传: status={status}')

    if not status:
        print(f'    ❌ 失败: {message[:200]}')
        continue

    # 等 CD2 异步上传完成
    time.sleep(60)

    newlog = log_tail(mark)
    errs = [l for l in newlog.split('\n') if 'upload error' in l and '相扑猫' in l]
    cloud = cloud_list()
    landed = expect in cloud

    if errs:
        print(f'    ❌ CD2 报错:')
        for l in errs[:2]:
            print(f'        {l[:160]}')
    if landed:
        print(f'    ✅ 云端已确认存在: {expect}')
        ok_n += 1
    else:
        print(f'    ⚠ 云端还没看到（当前云端 {len(cloud)} 条）')

print()
print('=' * 78)
print(f'补传完成: {ok_n}/{len(files)} 个已确认到云端')
print('=' * 78)
print('\n最终云端真实条目:')
for f in sorted(cloud_list()):
    emo = ' [emoji]' if has_bad_remote_chars(f) else ''
    print(f'    {f}{emo}')
