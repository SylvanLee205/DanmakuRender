"""修正通知文案 + 清理完成消息 + 用 Start_Render.bat 正确拉起 DMR（恢复守护）。

用户反馈：
1. 收到 "test" 消息 —— 那是我测 curl 时发的，配置里还是旧文案
   要改成："DanmakuRender已成功复活。"
2. 清理完成消息也要带"（含弹幕文件）"
3. DMR 没有守护进程 —— 我绕过 Start_Render.bat 直接跑 main.py 了，
   所以崩溃后不会自动重启
"""
import os
import re
import shutil
import subprocess
import time

UP = r'F:\DanmakuRender_AutoUp'
BAT = os.path.join(UP, 'Start_Render.bat')
CLEANER = os.path.join(UP, 'DMR', 'Cleaner', '__init__.py')


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


print('=' * 78)
print('1. 改通知文案')
print('=' * 78)
src = open(BAT, encoding='utf-8').read()
print('  改前:')
for l in src.splitlines():
    if 'TITLE=' in l or 'CONTENT=' in l:
        print(f'    {l.strip()}')

# 新文案：只说复活，后面的驱动细节去掉
old_content = 'set "CONTENT=渲染服务器已成功复活。Intel A380 驱动正常，AV1 录制环境准备就绪。"'
new_content = 'set "CONTENT=DanmakuRender已成功复活。"'
if old_content in src:
    src = src.replace(old_content, new_content)
    print(f'\n  ✅ CONTENT 已改')
elif 'DanmakuRender已成功复活' in src:
    print(f'\n  已经是新文案了')
else:
    # 兜底：正则替换
    src2 = re.sub(r'set "CONTENT=.*?"', new_content, src, count=1)
    if src2 != src:
        src = src2
        print(f'\n  ✅ CONTENT 已改（正则）')
    else:
        print(f'\n  ⚠ 找不到 CONTENT 行，手动检查')

# TITLE 也顺便改成更清晰的（保留原有含义，用户没要求改但可以更明确）
old_title = 'set "TITLE=DMR服务器状态报告"'
new_title = 'set "TITLE=DanmakuRender 状态"'
if old_title in src:
    src = src.replace(old_title, new_title)
    print('  ✅ TITLE 改为 "DanmakuRender 状态"')

shutil.copy2(BAT, BAT + '.bak-content-' + time.strftime('%H%M%S'))
open(BAT, 'w', encoding='utf-8', newline='').write(src)
print('\n  改后:')
for l in open(BAT, encoding='utf-8').read().splitlines():
    if 'TITLE=' in l or 'CONTENT=' in l or 'main.py' in l or 'curl' in l:
        print(f'    {l.strip()}')

print()
print('=' * 78)
print('2. 清理完成消息也带上"（含弹幕文件）"')
print('=' * 78)
c = open(CLEANER, encoding='utf-8').read()

# 2a. cleaned_files 现在只存路径；需要同时记住是否含弹幕
#     改成存 (路径, 是否含弹幕) 或者用两个列表
old_collect = """                files = [src]
                if _has_dm:
                    files.append(dm_file)
                cleaned_files.extend(files)
"""
new_collect = """                files = [src]
                if _has_dm:
                    files.append(dm_file)
                # 记录 (原文件路径, 是否含弹幕文件)，供完成事件拼文案用
                cleaned_files.append((src, _has_dm))
"""
if old_collect not in c:
    print('  ⚠ 找不到 collected 代码块，当前内容:')
    i = c.find('cleaned_files.extend')
    print('   ', c[i - 300:i + 100].replace('\n', '\n    '))
    raise SystemExit(1)
c = c.replace(old_collect, new_collect)
print('  ✅ cleaned_files 改为记录 (路径, 含弹幕标志)')

# 2b. 完成事件拼文案
old_send = """            self._pipeSend('end', f'清理完成: {", ".join(basename(f) for f in cleaned_files)}', target=task['source'], request_id=task['request_id'])"""
new_send = """            # 完成文案与"正在清理原文件"保持一致：只留文件名，
            # 有弹幕的标注（含弹幕文件）
            _parts = []
            for _p, _dm in cleaned_files:
                # 弹幕文件不在 cleaned_files 里单独列（它归入原文件）
                _parts.append(basename(_p) + ('（含弹幕文件）' if _dm else ''))
            self._pipeSend('end', f'清理完成: {", ".join(_parts)}', target=task['source'], request_id=task['request_id'])"""
if old_send not in c:
    print('  ⚠ 找不到 _pipeSend(clean) 行')
    i = c.find("清理完成")
    print('   ', c[i - 200:i + 200].replace('\n', '\n    '))
    raise SystemExit(1)
c = c.replace(old_send, new_send)
print('  ✅ 清理完成文案已改')

open(CLEANER, 'w', encoding='utf-8', newline='').write(c)

# 语法检查
r = subprocess.run([os.path.join(UP, '.venv', 'Scripts', 'python.exe'), '-m', 'py_compile', CLEANER],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')
print(f'\n  cleaner 语法: {"✅ 通过" if r.returncode == 0 else "❌ " + (r.stderr or "")[:300]}')

print()
print('=' * 78)
print('3. 停掉当前 DMR，改用 Start_Render.bat 拉起（恢复守护 + 走通知）')
print('=' * 78)
DMR_Q = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*main.py*' }")
CMD_Q = ("Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
         "Where-Object { $_.CommandLine -like '*Start_Render*' }")
ps(DMR_Q + " | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
time.sleep(5)
left = ps("(" + DMR_Q + " | Measure-Object).Count")
print(f'  已停: {left} 个残留')

print()
print('  用 explorer.exe 拉起 Start_Render.bat（脱离本会话）')
subprocess.Popen(['explorer.exe', BAT],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print('  已发起')

for i in range(24):
    time.sleep(5)
    n_py = ps("(" + DMR_Q + " | Measure-Object).Count")
    n_cmd = ps("(" + CMD_Q + " | Measure-Object).Count")
    if n_py not in ('', '0'):
        print(f'    +{(i+1)*5}s  DMR 进程={n_py}  守护 cmd={n_cmd}')
        if n_cmd not in ('', '0'):
            break
    elif i % 3 == 0:
        print(f'    +{(i+1)*5}s  DMR 进程={n_py}  守护 cmd={n_cmd}')

print()
print('=' * 78)
print('4. 最终状态')
print('=' * 78)
print('  DMR:')
dmr_list = ps(DMR_Q + " | ForEach-Object { 'PID ' + $_.ProcessId + "
             "'  父=' + $_.ParentProcessId }")
print('  ' + (dmr_list.replace('\n', '\n  ') or '无'))
print('  守护进程:')
cmd_list = ps(CMD_Q + " | ForEach-Object { 'PID ' + $_.ProcessId }")
print('  ' + (cmd_list.replace('\n', '\n  ') or '⚠ 没有守护进程'))
qflag = ps(DMR_Q + " | ForEach-Object { $_.CommandLine }")
print(f'  --quiet 生效: {"✅" if "--quiet" in qflag else "❌"}')
