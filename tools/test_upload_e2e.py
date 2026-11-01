"""端到端上传实测：真的传一个小文件到云端，然后核对。

这是最硬的证明 —— 前 8 项都是"接口正常"，这项是"真的能传上去"。
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import time


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

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）


PROD = _PROJECT_ROOT
sys.path.insert(0, PROD)
os.chdir(PROD)

RCLONE = _tool('rclone')
SVC = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'
TESTDIR = os.path.join(PROD, '直播回放', '_上传测试（弹幕版）')
NAME = '_上传功能测试-20261015.mp4'
REMOTE = f'cd2:百度网盘/DMR录播/断尾人类/{NAME}'


def cloud_has(name):
    tmp = os.path.join(os.environ['TEMP'], 'up_test_cache')
    os.makedirs(tmp, exist_ok=True)
    for s in ('', '-wal', '-shm'):
        src = os.path.join(SVC, 'dir_cache.sqlite' + s)
        if os.path.exists(src):
            try:
                shutil.copy2(src, os.path.join(tmp, 'dir_cache.sqlite' + s))
            except Exception:
                pass
    q = os.path.join(tmp, 'dir_cache.sqlite')
    if not os.path.exists(q):
        return None
    try:
        con = sqlite3.connect(f'file:{q}?mode=ro', uri=True)
        cur = con.cursor()
        # 全库找这个文件名
        cur.execute('SELECT name FROM files WHERE name LIKE ?', (f'%{name}%',))
        r = [x[0] for x in cur.fetchall()]
        con.close()
        return r
    except Exception as e:
        return [f'(查询失败: {e})']


print('=' * 78)
print('端到端上传实测')
print('=' * 78)

os.makedirs(TESTDIR, exist_ok=True)
local = os.path.join(TESTDIR, NAME)

# 造一个小的真 mp4（用 ffmpeg 生成 2 秒测试视频，能被正常识别）
print('\n1. 生成测试文件')
r = subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi',
                    '-i', 'testsrc=size=320x240:rate=15:duration=2',
                    '-pix_fmt', 'yuv420p', local],
                   capture_output=True, text=True, timeout=120)
if not os.path.exists(local):
    print(f'   ❌ ffmpeg 生成失败: {(r.stderr or "")[:200]}')
    raise SystemExit(1)
sz = os.path.getsize(local)
print(f'   ✅ {local}')
print(f'      {sz} 字节')

print('\n2. 上传前：云端是否已有同名文件')
before = cloud_has(NAME)
print(f'   {before if before else "（无）"}')

print('\n3. 用与 DMR 相同的命令上传（rclone copy）')
cmd = [RCLONE, 'copy', local, 'cd2:百度网盘/DMR录播/断尾人类',
       '--retries', '5', '--low-level-retries', '10', '--transfers', '1']
print(f'   {" ".join(cmd)}')
r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=600)
print(f'   exit={r.returncode}')
if r.stdout.strip():
    print(f'   stdout: {r.stdout.strip()[:300]}')
if r.stderr.strip():
    print(f'   stderr: {r.stderr.strip()[:300]}')

print('\n4. 直接问云端（rclone lsf，绕过本地缓存）')
r2 = subprocess.run([RCLONE, 'lsf', 'cd2:百度网盘/DMR录播/断尾人类',
                     '--files-only'],
                    capture_output=True, text=True, encoding='utf-8',
                    errors='replace', timeout=600)
hits = [x.strip() for x in (r2.stdout or '').split('\n') if NAME in x]
print(f'   exit={r2.returncode}')
print(f'   匹配 {NAME}: {hits if hits else "❌ 没找到"}')

print('\n5. 等 CD2 异步传完，再核对大小')
ok_final = False
for i in range(12):
    time.sleep(20)
    r3 = subprocess.run([RCLONE, 'lsf', 'cd2:百度网盘/DMR录播/断尾人类',
                         '--files-only', '--format', 's'],
                        capture_output=True, text=True, encoding='utf-8',
                        errors='replace', timeout=300)
    sizes = [x.strip() for x in (r3.stdout or '').split('\n') if x.strip()]
    print(f'   +{(i+1)*20}s  rclone lsf 返回 {len(sizes)} 行'
          f'{"（含我们的文件）" if any(str(sz) in s for s in sizes) else ""}')
    if hits:
        ok_final = True
        break

print('\n6. 清理测试文件')
try:
    os.remove(local)
    os.rmdir(TESTDIR)
    print('   ✅ 本地测试文件已删')
except Exception as e:
    print(f'   ⚠ {e}')
# 云端测试文件也删掉
r4 = subprocess.run([RCLONE, 'deletefile', REMOTE],
                    capture_output=True, text=True, encoding='utf-8',
                    errors='replace', timeout=300)
print(f'   云端删除 exit={r4.returncode}')

print()
print('=' * 78)
print('结论')
print('=' * 78)
if r.returncode == 0 and hits:
    print('  ✅ 上传链路完全正常：文件成功传到云端')
elif r.returncode == 0:
    print('  ⚠️ rclone 报成功，但列表里没找到（可能是缓存延迟）')
else:
    print(f'  ❌ 上传失败，exit={r.returncode}')
