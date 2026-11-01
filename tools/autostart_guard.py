"""开机自启用的小守卫：DMR 已在运行时什么都不做，避免双开。

为什么需要它
------------
`Start_Render.bat` 本身是"守护循环"（程序退出后 10 秒重拉），但它**不判断**是否
已经有一个实例在跑。开机自启如果无条件拉它，遇到"已经手动启动过"的情况就会变成
**两个 DMR 实例**——而本项目明确写着"不要启动第二个实例，状态库是单例，会互相踩"。

设计取舍（重要）
----------------
检测进程失败时**选择跳过启动**（exit 0），而不是冒险启动。
理由：漏启一次 = 手工双击一下就能补；双开 = 同一主播两路录制 + 状态库互相覆盖，
修复成本高得多。判断结果一律写 `logs/autostart.log`，不会静默。

退出码
------
    0 = 已有实例在跑（或检测失败，按"在跑"处理），不要启动
    2 = 确认没有实例，可以启动
"""
import os
import subprocess
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）


UP = _PROJECT_ROOT
LOG = os.path.join(UP, 'logs', 'autostart.log')

DMR_Q = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*main.py*' } | "
         "ForEach-Object { $_.ProcessId }")


def _log(msg: str) -> None:
    line = f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}\n'
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line)
    except OSError:
        pass
    try:
        print(line.rstrip())
    except Exception:
        pass


def running_pids() -> list:
    r = subprocess.run(['powershell', '-NoProfile', '-Command', DMR_Q],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=60)
    out = (r.stdout or '').strip()
    return [x for x in out.split() if x.isdigit()]


def main() -> int:
    try:
        pids = running_pids()
    except Exception as e:
        # 检测失败 → 保守跳过（见文件头"设计取舍"）
        _log(f'跳过启动：进程检测失败（{type(e).__name__}: {e}）。'
             f'如确认没在跑，请手动双击 Start_Render.bat。')
        return 0

    if pids:
        _log(f'跳过启动：已有 DMR 实例在运行（PID {", ".join(pids)}）。')
        return 0

    _log('确认没有 DMR 实例，准备启动。')
    return 2


if __name__ == '__main__':
    sys.exit(main())
