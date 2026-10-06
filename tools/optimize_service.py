"""服务版最终优化 + 端到端验证。

1. 日志级别改成 Info（Error 级别会隐藏关键诊断信息 —— 
   2026-10-05 那次 8427 次 errno -7 疯狂重试只留下寥寥几条日志，
   就是 Error 级别造成的）
2. 清掉无效的 max_upload_speed_kbyps（对 WebDAV 上传无效，已实测）
3. 端到端验证：上传一个小文件，确认真的到百度
"""
import json
import os
import shutil
import sqlite3
import subprocess
import time

RCLONE = r'C:\User Program Files\rclone-v1.75.1\rclone.exe'
SVC_ROOT = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 服务版配置优化')
print('=' * 78)
p = os.path.join(SVC_ROOT, 'systemsettings.json')
if os.path.exists(p):
    d = json.loads(open(p, encoding='utf-8', errors='replace').read())
    print('  改前:')
    for k in ('file_log_level', 'max_upload_speed_kbyps', 'upload_delay_secs',
              'max_process_tasks', 'max_upload_threads'):
        if k in d:
            print(f'      {k} = {d[k]}')

    changed = []
    if d.get('file_log_level') != 'Info':
        d['file_log_level'] = 'Info'
        changed.append('file_log_level -> Info')
    if d.get('max_upload_speed_kbyps'):
        d['max_upload_speed_kbyps'] = 0.0
        changed.append('max_upload_speed_kbyps -> 0 (不限速，对 WebDAV 本来就无效)')

    if changed:
        bk = os.path.join(r'F:\_CD2配置备份_20261005',
                          'svc_before_opt_' + time.strftime('%H%M%S'))
        os.makedirs(bk, exist_ok=True)
        shutil.copy2(p, bk)
        # 用临时文件+替换，避免写坏
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        print('  改动:')
        for c in changed:
            print(f'      ✓ {c}')
        print(f'  已备份到 {bk}')
        print('  需要重启服务生效...')
        ps("Restart-Service CloudDrive2 -Force")
        for i in range(12):
            time.sleep(5)
            st = ps("(Get-Service CloudDrive2).Status.ToString()")
            n = ps("(Get-NetTCPConnection -LocalPort 19798 -State Listen "
                   "-ErrorAction SilentlyContinue | Measure-Object).Count")
            print(f'    +{(i+1)*5:>3}s  服务={st}  19798={n} 监听')
            if st == 'Running' and n not in ('', '0'):
                break
    else:
        print('  无需改动')
else:
    print(f'  ⚠ 找不到 {p}')

print()
print('=' * 78)
print('2. 端到端验证：上传一个小文件')
print('=' * 78)
testf = os.path.join(os.environ['TEMP'], 'e2e_test.bin')
with open(testf, 'wb') as f:
    f.write(os.urandom(1024 * 1024))
name = 'e2e_' + time.strftime('%H%M%S') + '.bin'
dest = f'cd2:百度网盘/DMR录播/__e2e__/{name}'
print(f'  上传 {name} (1MB) 到 /DMR录播/__e2e__/')
r = subprocess.run([RCLONE, 'copyto', testf, dest, '--retries', '1'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=300)
print(f'  rclone exit={r.returncode}')
print('  等 45 秒...')
time.sleep(45)


def svc_cache(pattern):
    dst = os.path.join(os.environ['TEMP'], 'svcfin')
    os.makedirs(dst, exist_ok=True)
    for root, dirs, files in os.walk(SVC_ROOT):
        for f in files:
            if f.startswith('dir_cache.sqlite'):
                try:
                    shutil.copy2(os.path.join(root, f), os.path.join(dst, f))
                except Exception:
                    pass
    out = set()
    q = os.path.join(dst, 'dir_cache.sqlite')
    if os.path.exists(q):
        try:
            con = sqlite3.connect(f'file:{q}?mode=ro', uri=True)
            cur = con.cursor()
            cur.execute("SELECT id FROM cached_item WHERE path LIKE ?", (pattern,))
            for (did,) in cur.fetchall():
                cur.execute('SELECT name FROM files WHERE parent_id=?', (did,))
                out |= set(x[0] for x in cur.fetchall())
            con.close()
        except Exception as e:
            return {f'err {e}'}
    return out


cached = svc_cache('%__e2e__%')
print(f'  服务版缓存: {cached if cached else "(空)"}')
if name in cached:
    print('  ✅✅ 端到端成功！文件真的到百度了')
else:
    print('  ⚠ 缓存里没找到，再看服务版日志:')

# 看日志有没有 PermissionDenied
lg = os.path.join(SVC_ROOT, 'log', time.strftime('%Y-%m-%d') + '.log')
if os.path.exists(lg):
    t = open(lg, encoding='utf-8', errors='replace').read()
    hits = [l for l in t.split('\n') if name in l or '__e2e__' in l]
    pd = [l for l in hits if 'PermissionDenied' in l]
    print(f'    日志含该文件的行: {len(hits)}，其中 PermissionDenied: {len(pd)}')
    for l in hits[-5:]:
        print(f'      {l[:170]}')
    if not hits:
        print(f'    （日志里没提到，可能日志级别刚改还没写）')

print()
print('  清理测试文件...')
subprocess.run([RCLONE, 'purge', 'cd2:百度网盘/DMR录播/__e2e__'],
               capture_output=True, text=True, encoding='utf-8',
               errors='replace', timeout=300)
try:
    os.remove(testf)
except Exception:
    pass
print('  完成')

print()
print('=' * 78)
print('3. 最终状态汇总')
print('=' * 78)
svc = ps("(Get-Service CloudDrive2).Status.ToString() + ' / ' + "
         "(Get-Service CloudDrive2).StartType.ToString()")
print(f'  服务版: {svc}')
print(f'  19798: {ps("(Get-NetTCPConnection -LocalPort 19798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")} 个监听')
print(f'  应用版进程: ' + (ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | "
                     "ForEach-Object { 'PID ' + $_.Id }") or '✅ 未运行'))
print(f'  应用版自启: ' + (ps("(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' "
                       "-ErrorAction SilentlyContinue).CloudDrive") or '✅ 已移除'))
print(f'  看门狗任务: ' + (ps("Get-ScheduledTask -TaskName 'DanmakuRender_CD2守护' "
                        "-ErrorAction SilentlyContinue | ForEach-Object { $_.TaskName }")
                      or '✅ 已删除'))
r = subprocess.run([RCLONE, 'lsf', 'cd2:百度网盘/DMR录播', '--max-depth', '1'],
                   capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=300)
print(f'  rclone 读云端: exit={r.returncode}  '
      f'{len([x for x in r.stdout.split(chr(10)) if x.strip()])} 个目录')
