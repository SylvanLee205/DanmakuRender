"""彻底清理重复的 streamgears 进程 + 让孤儿分段被正确恢复。

问题复盘（我的重启方式有缺陷）：
    我只 Stop-Process 了 main.py 的 python 进程，但 streamgears_wrapper
    是它们的**子进程**，没被一起杀掉。结果：
      · 老 streamgears 继续写 [正在录制]xxx.flv.part
      · 新 DMR 又起了一对新的 streamgears
      · 同一个主播有两对进程在录同一个流 → 孤儿分段

正确做法：
    1. 停守护（防止它拉起新的）
    2. 停 DMR 主进程
    3. **停所有 streamgears_wrapper 子进程**   <- 之前漏了这步
   **停所有录制用的 ffmpeg**（命令含「直播回放」）<- 2026-10-19 补上
    4. 等孤儿 .part 沉淀（> 2 分钟，让 DMR 的恢复阈值能识别）
    5. 重新启动 → DMR 的 recover_part 会把孤儿 .part 改名成正式分段落库
"""
import os
import subprocess
import sys
import time

UP = r'F:\DanmakuRender_AutoUp'


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace')
    return ((r.stdout or '') + (r.stderr or '')).strip()


CMD_Q = ("Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
         "Where-Object { $_.CommandLine -like '*Start_Render*' } | "
         "ForEach-Object { $_.ProcessId }")
DMR_Q = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*main.py*' } | "
         "ForEach-Object { $_.ProcessId }")
SG_Q = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*streamgears_wrapper*' } | "
        "ForEach-Object { $_.ProcessId }")
# ⚠️ 2026-10-19 新增：录制用的 ffmpeg。
#    判据用 -segment_time（只有 DMR 录制命令有，批量转码没有）——
#    不要用中文路径做判据：中文经 Python -> powershell -Command 传递会乱码。
FF_Q = ("Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe'\" | "
        "Where-Object { $_.CommandLine -like '*-segment_time*' } | "
        "ForEach-Object { $_.ProcessId }")