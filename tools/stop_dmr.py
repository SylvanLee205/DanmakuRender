"""干净地停止 DMR（含守护进程与所有录制子进程）。

为什么需要单独一个"停止"脚本
--------------------------
`Start_Render.bat` 是**守护循环**：程序退出后 10 秒会自己再拉起来。
所以"停"不能只关掉窗口或按 Ctrl+C —— 那只会让守护脚本把程序重新拉起。

正确顺序（少一步就会留孤儿）：
    1. 先停守护 cmd      —— 否则它会立刻重新拉起 DMR
    2. 再停 DMR python   —— 从子到父（venv 启动器 → 真正的 C:\\Python311 进程）
    3. 最后停录制子进程  —— streamgears_wrapper 与录制用 ffmpeg（判据 -segment_time）
       这两类是 DMR 的子进程，只杀 python 会让它们继续写文件，产生
       重复录制和孤儿 `[正在录制]` 分段（2026-10-07 踩过）。

用法：
    .venv\\Scripts\\python.exe tools\\stop_dmr.py --dry-run   # 只看会停什么
    .venv\\Scripts\\python.exe tools\\stop_dmr.py             # 真停（不重启）
"""
import os
import subprocess
import sys
import time

UP = r'F:\DanmakuRender_AutoUp'
DRY_RUN = '--dry-run' in sys.argv

# stdout/stderr 可能是管道（被别的程序捕获）或 GBK 控制台：
# 下面的 ⚠️/❌/✅ 不在 GBK 字符集里，print 会直接 UnicodeEncodeError 崩掉。
# 2026-10-20 实测：迁移时 stop_dmr 在"停止前"之后神秘消失、进程一个没停，
# 就是这句炸的 —— 无人值守场景必须容忍编码问题。
try:
    sys.stdout.reconfigure(errors='replace')
    sys.stderr.reconfigure(errors='replace')
except Exception:
    pass


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=90)
    return ((r.stdout or '') + (r.stderr or '')).strip()


def pids(query):
    return [x for x in ps(query).split() if x.isdigit()]


CMD_Q = ("Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
         "Where-Object { $_.CommandLine -like '*Start_Render*' } | "
         "ForEach-Object { $_.ProcessId }")
DMR_Q = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*main.py*' } | "
         "ForEach-Object { $_.ProcessId }")
SG_Q = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*streamgears_wrapper*' } | "
        "ForEach-Object { $_.ProcessId }")
FF_Q = ("Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe'\" | "
        "Where-Object { $_.CommandLine -like '*-segment_time*' } | "
        "ForEach-Object { $_.ProcessId }")


def recording_files():
    base = os.path.join(UP, '直播回放')
    out = []
    for root, dirs, files in os.walk(base):
        for f in files:
            if f.startswith('[正在录制]'):
                p = os.path.join(root, f)
                try:
                    out.append((p, os.path.getsize(p)))
                except OSError:
                    continue
    return out


def show_state(tag):
    print(f'  {tag}: 守护={pids(CMD_Q) or "无"}  DMR={pids(DMR_Q) or "无"}  '
          f'streamgears={pids(SG_Q) or "无"}  ffmpeg={pids(FF_Q) or "无"}')


def kill(pid_list, label):
    for pid in pid_list:
        ps(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue")
        print(f'    停 {label} {pid}')


def main() -> int:
    print('=' * 78)
    print('停止 DMR' + ('（DRY-RUN，不会动任何进程）' if DRY_RUN else ''))
    print('=' * 78)
    show_state('停止前')

    parts = recording_files()
    if parts:
        print(f'\n  ⚠️ 发现 {len(parts)} 个 [正在录制] 文件：')
        for p, sz in sorted(parts, key=lambda x: -x[1])[:10]:
            print(f'     {sz/1024/1024:>8.1f} MB  {os.path.basename(p)[:70]}')
        print('     这些是正在写入/刚中断的分段；停止后它们会被保留，')
        print('     下次启动时 recover 流程会按规则接管（不是丢失）。')

    if DRY_RUN:
        print('\n  DRY-RUN 结束：以上就是要停的进程。')
        return 0

    print('\n  [1/3] 停止守护（防止它重新拉起 DMR）')
    kill(pids(CMD_Q), '守护')
    time.sleep(2)

    print('  [2/3] 停止 DMR 主进程（从子到父）')
    kill(list(reversed(pids(DMR_Q))), 'DMR')
    time.sleep(3)

    print('  [3/3] 停止录制子进程')
    kill(pids(SG_Q), 'streamgears')
    kill(pids(FF_Q), 'ffmpeg')
    time.sleep(2)

    print()
    show_state('停止后')

    left = pids(CMD_Q) + pids(DMR_Q) + pids(SG_Q) + pids(FF_Q)
    if left:
        print('\n  ❌ 仍有进程未退出，请再跑一次本脚本，或检查是否有权限问题。')
        return 1
    print('\n  ✅ 已全部停止。要重新启动请双击 Start_DMR.bat。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
