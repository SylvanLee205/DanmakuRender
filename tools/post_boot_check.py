"""重启后一键自检：确认开机自启真的把 DMR 拉起来了。

用法（登录系统后双击桌面 `DMR-重启后检查.bat`，或命令行）：
    .venv\\Scripts\\python.exe tools\\post_boot_check.py

它只读，不改任何东西。检查项：
    1. 当前登录会话（确认是自动登录还是人工登录）
    2. 自启日志 logs/autostart.log 的最新记录
    3. 进程链：守护 cmd → .venv python → 真正的 python
    4. 最新日志里的「代码版本」行（确认新代码已加载）
    5. 加载的任务数 / ERROR / WARNING
    6. 状态库是否有卡住的非终态产物
    7. 待删清单条数
"""
import glob
import os
import re
import sqlite3
import subprocess
import sys
import time

UP = r'F:\DanmakuRender_AutoUp'


def ps(cmd):
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=60)
        return ((r.stdout or '') + (r.stderr or '')).strip()
    except Exception as e:
        return f'<失败: {type(e).__name__}: {e}>'


def head(t):
    print()
    print('=' * 70)
    print(t)
    print('=' * 70)


def main():
    problems = []
    print(f'DMR 重启后自检   {time.strftime("%Y-%m-%d %H:%M:%S")}')

    # 1. 登录会话
    head('1. 当前登录会话')
    # ⚠️ Win32_ComputerSystem.UserName 在 RDP 会话里经常为空，改用 explorer.exe 的
    #    属主（每个交互会话都有一个 explorer），再退回 quser。
    who = ps("Get-Process explorer -IncludeUserName -ErrorAction SilentlyContinue | "
             "Select-Object -First 1 -ExpandProperty UserName")
    if not who or who.startswith('<'):
        who = ps("(quser 2>$null | Select-Object -Skip 1 | "
                 "ForEach-Object { ($_ -split '\\s+')[1] } | "
                 "Select-Object -First 1)")
    # 开机时间用 ISO 格式：PowerShell 默认输出的日期是本地化文本，
    # 经管道读回来会变成乱码（实测 "2026��10��16��"）。
    boot = ps("(Get-CimInstance Win32_OperatingSystem)."
              "LastBootUpTime.ToString('yyyy-MM-dd HH:mm:ss')")
    print(f'  用户: {who or "（无，说明没人登录）"}')
    print(f'  开机时间: {boot}')
    if not who:
        problems.append('没有检测到登录用户 —— 自动登录可能失败了')

    # 2. 自启日志
    head('2. 自启日志 logs/autostart.log（最后 6 条）')
    lg = os.path.join(UP, 'logs', 'autostart.log')
    lines = []
    if os.path.exists(lg):
        with open(lg, encoding='utf-8', errors='replace') as f:
            lines = [l.rstrip() for l in f if l.strip()][-6:]
    if lines:
        for l in lines:
            print('  ' + l)
    else:
        print('  （空 —— 启动项没有执行过）')
        problems.append('autostart.log 为空，开机自启没有执行')
    if lines and not any('准备启动' in l for l in lines[-3:]):
        problems.append('最近的记录不是「准备启动」，可能是被判定为"已在运行"')

    # 3. 进程链
    head('3. 进程链')
    CMD_Q = ("Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
             "Where-Object { $_.CommandLine -like '*Start_Render*' } | "
             "ForEach-Object { $_.ProcessId }")
    DMR_Q = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*main.py*' } | "
             "ForEach-Object { $_.ProcessId }")
    guards = [x for x in ps(CMD_Q).split() if x.isdigit()]
    dmrs = [x for x in ps(DMR_Q).split() if x.isdigit()]
    print(f'  守护 cmd : {guards or "❌ 不在"}')
    print(f'  DMR 进程 : {dmrs or "❌ 不在"}')
    if not dmrs:
        problems.append('DMR 进程没起来')
    elif len(dmrs) > 2:
        problems.append(f'DMR 进程数异常（{len(dmrs)} 个，正常是 2 个：venv 启动器 + 真身）')
    if dmrs and not guards:
        problems.append('DMR 在跑但守护不在 —— 崩溃后不会自动重启')

    # 4. 最新日志
    head('4. 最新日志')
    logs = sorted(glob.glob(os.path.join(UP, 'logs', 'DMR-2026*.log')),
                  key=os.path.getmtime, reverse=True)
    if not logs:
        print('  ❌ 找不到日志')
        problems.append('找不到 DMR 日志')
    else:
        cur = logs[0]
        print(f'  文件: {os.path.basename(cur)}')
        try:
            txt = open(cur, encoding='utf-8', errors='replace').read()
        except OSError as e:
            txt = ''
            print(f'  读取失败: {e}')
        m = re.search(r'代码版本: (\S+) @ (\w+)', txt)
        if m:
            print(f'  代码版本: {m.group(1)} @ {m.group(2)}')
        else:
            print('  ⚠️ 没有「代码版本」行 —— 可能是旧代码在跑（14:00 之前启动的进程）')
            problems.append('日志里没有代码版本行')
        n_task = len(re.findall(r'下载任务 .+ 已启动', txt))
        n_err = txt.count('[error]')
        n_warn = txt.count('[warning]')
        print(f'  已加载任务: {n_task}    ERROR: {n_err}    WARNING: {n_warn}')
        if n_task < 30:
            problems.append(f'只加载了 {n_task} 个任务（正常 33）')
        if n_err:
            problems.append(f'日志里有 {n_err} 条 ERROR')
        hb = txt.count('[心跳]')
        print(f'  心跳行: {hb} 条' + ('  ← 还没到第一次心跳（启动后 30 分钟）' if hb == 0 else ''))

    # 5. 状态库非终态
    head('5. 状态库非终态产物')
    db = os.path.join(UP, 'logs', 'dmr_state.db')
    try:
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        rows = list(con.execute(
            "select kind, state, count(*) c from artifacts "
            "where state not in ('cleaned','uploaded','skipped','failed','missing') "
            "group by kind, state"))
        con.close()
        if rows:
            for kind, state, c in rows:
                print(f'  {kind} / {state}: {c} 个')
        else:
            print('  ✅ 没有卡住的产物')
    except Exception as e:
        print(f'  （读取失败: {type(e).__name__}: {e}）')

    # 6. 待删清单
    head('6. 待删清单')
    jp = os.path.join(UP, 'logs', 'pending_clean.json')
    try:
        if os.path.exists(jp):
            import json
            with open(jp, encoding='utf-8') as f:
                data = json.load(f)
            print(f'  {len(data)} 条待删（48 小时后执行）')
        else:
            print('  （还没有待删清单文件）')
    except Exception as e:
        print(f'  （读取失败: {type(e).__name__}: {e}）')

    # 7. 开机计划任务 + 自动登录状态
    head('7. 开机自启方式')
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon') as k:
            auto = winreg.QueryValueEx(k, 'AutoAdminLogon')[0]
    except Exception:
        auto = '?'
    print(f'  AutoAdminLogon = {auto}'
          + ('（已关：重启后不会自动登录，必须靠计划任务）' if str(auto) == '0' else ''))
    state = ps("try { (Get-ScheduledTask -TaskName 'DanmakuRender_Boot' "
               "-ErrorAction Stop).State } catch { 'NOT_FOUND' }")
    if 'NOT_FOUND' in state or not state:
        print('  开机任务 DanmakuRender_Boot: ❌ 未安装')
        if str(auto) == '0':
            problems.append('自动登录已关且没有开机任务 —— 重启后 DMR 不会自己起来')
    else:
        print(f'  开机任务 DanmakuRender_Boot: ✅ {state}')

    # 结论
    head('结论')
    if problems:
        print('  ⚠️ 发现问题：')
        for p in problems:
            print(f'    - {p}')
        print()
        print('  兜底：双击桌面 DMR-启动.bat 手动启动，然后重新跑本检查。')
        return 1
    print('  ✅ 一切正常：自启生效、进程链完整、新代码已加载、无错误')
    return 0


if __name__ == '__main__':
    sys.exit(main())
