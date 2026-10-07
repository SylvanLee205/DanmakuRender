"""回滚 HTTPS 到 HTTP，并让 --quiet 默认显示"进度级"消息（解决"像卡死"）。

诊断结论：
【问题1 像卡死】
  DMR 运行正常（PID 4324，CPU 7.5 秒，Responding=True），
  启动于 14:01:58，现在 14:11 —— 只是这 10 分钟没有任何事件。
  真正原因是 --quiet 把控制台降到 WARNING，**连"直播开始"这种基本消息都不显示**，
  所以看起来像卡死。

  修法：--quiet 的默认级别从 WARNING 改成自定义的 PROGRESS(25)，
  位于 INFO(20) 和 WARNING(30) 之间。规则：
      比 INFO 更啰嗦的细节（GOP、engine 消息字典、各任务的"直播已结束"）
          -> 保持 DEBUG，控制台不显示
      关键进度（直播开始/渲染完成/上传完成...）
          -> 用 PROGRESS，控制台显示
      原有 WARNING/ERROR
          -> 照样显示

【问题2 HTTPS 19799 手机没反应】
  本机实测 HTTPS **完全正常**：HTTP 200，TLSv1.3，AES256-GCM。
  但证书是**自签名**的，rclone 不跳过校验时直接报：
      x509: certificate signed by unknown authority
  手机浏览器遇到不受信任证书会**静默拦截**（尤其 Android Chrome），
  所以"没反应"。

  这是自签名证书的固有限制，不是我配置错了。
  另外查到 Tailscale 域名是 win-e462mto1sb0.tail506a91.ts.net，
  但 CertDomains 为空 —— 没申请 Tailscale 的证书。

  处置：回滚到 HTTP（你手机本来能用），避免半坏状态。
  真要 HTTPS，建议走 Tailscale 的证书（trusted，无警告），那是另一件事。

【问题3 WebDAV】
  实测都正常：
    HTTP  127.0.0.1:19798/dav  -> 401（需认证）✅
    HTTPS 127.0.0.1:19799/dav  -> rclone --no-check-certificate 能读 16 个项目 ✅
    HTTP  rclone 读云端         -> 16 个目录 ✅
  所以 WebDAV 本身没问题，可能是手机客户端的问题（用错端口/证书报错）。
"""
import os
import shutil
import subprocess
import time

SVC_ROOT = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2'
CFG = os.path.join(SVC_ROOT, 'config.toml')
SVC = 'CloudDrive2'
MAIN = r'F:\DanmakuRender_AutoUp\main.py'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 回滚 HTTPS -> HTTP（恢复你手机能用的状态）')
print('=' * 78)
raw = open(CFG, 'rb').read()
if b'enable_https = true' in raw:
    shutil.copy2(CFG, CFG + '.bak-revert-' + time.strftime('%H%M%S'))
    raw = raw.replace(b'enable_https = true', b'enable_https = false', 1)
    open(CFG, 'wb').write(raw)
    print('  ✅ enable_https 改回 false')
else:
    print('  当前已经是 false，无需回滚')
print(f'  校验: true 出现 {open(CFG, "rb").read().count(b"enable_https = true")} 次')

ps(f"Restart-Service {SVC} -Force")
for i in range(15):
    time.sleep(5)
    st = ps(f"(Get-Service {SVC}).Status.ToString()")
    n98 = ps("(Get-NetTCPConnection -LocalPort 19798 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")
    n99 = ps("(Get-NetTCPConnection -LocalPort 19799 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count")
    if st == 'Running':
        print(f'  服务={st}  19798={n98}  19799={n99}')
        break

print()
print('=' * 78)
print('2. 让 --quiet 默认显示进度消息（解决"像卡死"）')
print('=' * 78)
src = open(MAIN, encoding='utf-8').read()

if 'PROGRESS' in src:
    print('  已经改过了')
else:
    # 2a. 加自定义级别（放在 logging 导入之后、函数定义之前）
    anchor = "VERSION = "
    if anchor not in src:
        # 找文件开头合适位置
        anchor = "def _startup_recover"
    progress_def = '''# ── 自定义日志级别：PROGRESS ──────────────────────────────────────
# 目的：控制台既要"安静"（不显示 GOP/engine 字典/每个任务的状态流转），
#       又要能看出程序在干活（不然像卡死）。
# 数值取 25，落在 INFO(20) 和 WARNING(30) 之间：
#     --quiet          -> PROGRESS（只显示关键进度 + 警告错误）
#     --quiet=info     -> INFO（详细，原行为）
#     --quiet=error    -> ERROR（只留错误）
#     --quiet=debug    -> DEBUG（很吵）
PROGRESS = 25
logging.addLevelName(PROGRESS, 'PROGRESS')

'''
    # 插到 'import logging' 那一行所在块之后
    lines = src.split('\n')
    idx = None
    for i, l in enumerate(lines):
        if l.startswith('import logging.handlers'):
            idx = i
            break
    if idx is None:
        for i, l in enumerate(lines):
            if l.startswith('import logging'):
                idx = i
                break
    if idx is None:
        print('  ⚠ 找不到 import logging，手动处理')
        raise SystemExit(1)
    lines.insert(idx + 1, progress_def)
    src = '\n'.join(lines)
    print(f'  已插入 PROGRESS 定义（import logging 之后）')

    # 2b. --quiet 默认级别改成 PROGRESS
    old_map = """    _lvl_name = (args.quiet or 'info').lower()
    _console_level = {
        'debug': logging.DEBUG,
        'info': logging.INFO,
        'warning': logging.WARNING,
        'warn': logging.WARNING,
        'error': logging.ERROR,
        'critical': logging.CRITICAL,
    }.get(_lvl_name, logging.WARNING)"""
    new_map = """    # 默认（不带 --quiet）保持 INFO，兼容原行为；
    # 带 --quiet 不带值时用 PROGRESS（关键进度 + 警告错误）
    _lvl_name = (args.quiet or 'info').lower()
    if _lvl_name in ('quiet', ''):
        _lvl_name = 'progress'
    _console_level = {
        'debug': logging.DEBUG,
        'info': logging.INFO,
        'progress': PROGRESS,
        'warning': logging.WARNING,
        'warn': logging.WARNING,
        'error': logging.ERROR,
        'critical': logging.CRITICAL,
    }.get(_lvl_name, PROGRESS)"""
    if old_map not in src:
        print('  ⚠ 找不到级别映射块，需要手动改')
        print('    实际内容：')
        i = src.find('_lvl_name')
        print('   ', src[i - 100:i + 400].replace('\n', '\n    '))
        raise SystemExit(1)
    src = src.replace(old_map, new_map)
    print('  已改 --quiet 默认级别为 PROGRESS')

    # 2c. 横幅文案更新
    src = src.replace(
        "logging.WARNING: 'WARNING(安静)',",
        "logging.WARNING: 'WARNING(只有警告)', "
        "PROGRESS: 'PROGRESS(关键进度)',")
    src = src.replace(
        "if _console_level >= logging.WARNING:\n            print('  （控制台已静默，只显示警告/错误；'\n                  '想恢复详细输出去掉 --quiet）')",
        "if _console_level >= PROGRESS:\n            print('  （控制台只显示关键进度和警告/错误；'\n                  '想看详细输出用 --quiet=info）')")

    open(MAIN, 'w', encoding='utf-8', newline='').write(src)
    print('  已写回 main.py')

# 语法检查
r = subprocess.run([r'F:\DanmakuRender_AutoUp\.venv\Scripts\python.exe', '-m', 'py_compile', MAIN],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')
print(f'  语法检查: {"✅ 通过" if r.returncode == 0 else "❌ 失败"}')
if r.returncode != 0:
    print(f'    {(r.stderr or "")[:400]}')

print()
print('=' * 78)
print('3. 验证级别解析')
print('=' * 78)
r = subprocess.run([r'F:\DanmakuRender_AutoUp\.venv\Scripts\python.exe', MAIN, '--help'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace',
                   cwd=r'F:\DanmakuRender_AutoUp')
for l in (r.stdout or '').split('\n'):
    if 'quiet' in l:
        print(f'  {l.strip()}')
