"""注册 / 注销「开机自动启动」计划任务（无需手改 XML）。

为什么不用 tools/boot_task.xml 了
--------------------------------
那个 XML 里存的是**绝对路径**（`<Command>F:\\DanmakuRepo\\Run_DMR.bat`）和
**写死的账户名**。项目换盘、换机器、换用户名，它全都不对；而且 XML 是
UTF-16 带 BOM，手改容易把编码搞坏（`<URI>` 和 `-TaskName` 不一致时
schtasks 会直接失败）。

本脚本改成**运行时生成**：路径取 DMR.paths，账户取当前登录用户，
要什么参数就传什么，不依赖任何模板文件。

设计要点
--------
* **密码不落盘、不上屏**：Password 类型的任务需要账户密码。Windows 自动
  登录本来就把密码存在注册表 `Winlogon\\DefaultPassword` 里，优先从那儿读，
  读不到才提示用户输入（输入时不回显）。
* **设置对齐老的可用任务**：无运行时长限制（PT0S）、错过就尽快启动、
  已在跑就不开第二个。这三点缺一个都会导致"录制莫名中断"。
* **幂等**：重复运行只会覆盖同名任务。

用法（需要管理员）
------------------
    python tools\\install_boot_task.py            # 创建/更新
    python tools\\install_boot_task.py --remove   # 删除
    python tools\\install_boot_task.py --status   # 只看状态
    python tools\\install_boot_task.py --password  （强制重新输入密码）
"""
import argparse
import ctypes
import getpass
import os
import subprocess
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

# ⚠️ 一律用绝对路径调系统工具：venv 进程的 PATH 里常常没有 System32，
#    写 'schtasks' / 'powershell' 会 FileNotFoundError（2026-10-19 踩过）。
from DMR.paths import powershell_exe, system32  # noqa: E402

SCHTASKS = system32('schtasks.exe')

TASK = 'DMR_Boot'
ACTION = os.path.join(PROJ, 'Run_DMR.bat')
WORKDIR = PROJ
IS_WIN = sys.platform == 'win32'


def is_admin() -> bool:
    if not IS_WIN:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate():
    """不是管理员就弹 UAC 重新启动自己。"""
    if is_admin() or not IS_WIN:
        return False
    params = ' '.join(f'"{a}"' for a in [os.path.abspath(__file__)] + sys.argv[1:])
    try:
        r = ctypes.windll.shell32.ShellExecuteW(
            None, 'runas', sys.executable, params, None, 1)
        return r > 32
    except Exception:
        return False


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding='gbk', errors='replace',
                          stdin=subprocess.DEVNULL, **kw)


def read_autologon_password():
    """从注册表读自动登录密码（本机就是这么配的）。读不到返回 None。"""
    if not IS_WIN:
        return None
    try:
        import winreg
        key = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            pwd, _ = winreg.QueryValueEx(k, 'DefaultPassword')
            user, _ = winreg.QueryValueEx(k, 'DefaultUserName')
        if pwd:
            print(f'  从注册表读到自动登录账户: {user}')
            return user, pwd
    except Exception:
        pass
    return None


def ask_password():
    print()
    print('  需要账户密码才能创建 Password 类型的计划任务。')
    print('  （Windows 会把它存成 LSA 密钥，不会明文留在任务里）')
    try:
        u = input(f'  账户名 [{getpass.getuser()}]: ').strip() or getpass.getuser()
        import getpass as gp
        p = gp.getpass('  密码（输入时不显示）: ')
        if not p:
            return None
        return u, p
    except (EOFError, KeyboardInterrupt):
        return None


def status():
    r = run([SCHTASKS, '/query', '/tn', TASK, '/fo', 'LIST', '/v'])
    if r.returncode != 0:
        print(f'  任务 {TASK} 不存在。')
        return 1
    keep = ('任务名', '状态', '要运行的任务', '作为用户运行', '上次运行时间',
            '上次结果', 'TaskName', 'Status', 'Task To Run', 'Run As User',
            'Last Run Time', 'Last Result')
    for line in (r.stdout or '').splitlines():
        if any(k in line for k in keep):
            print('   ' + line.strip())
    return 0


def remove():
    r = run([SCHTASKS, '/delete', '/tn', TASK, '/f'])
    if r.returncode == 0:
        print(f'  ✅ 已删除任务 {TASK}')
        return 0
    print(f'  ❌ 删除失败: {(r.stderr or r.stdout).strip()}')
    return 1


def create():
    if not os.path.exists(ACTION):
        print(f'  ❌ 找不到 {ACTION}')
        return 1

    # 已经有任务就沿用它的账户，避免换成别的账户后录制环境不一致
    account = None
    r = run([SCHTASKS, '/query', '/tn', TASK, '/fo', 'LIST', '/v'])
    if r.returncode == 0:
        for line in (r.stdout or '').splitlines():
            if '作为用户运行' in line or 'Run As User' in line:
                account = line.split(':', 1)[-1].strip()
                break

    cred = None
    if not account:
        cred = read_autologon_password()
        if not cred:
            cred = ask_password()
        if not cred:
            print('  ❌ 没拿到账户凭据，无法创建 Password 类型任务。')
            print('     备选：用 管理员命令行的 schtasks 手动创建，或改用 SYSTEM 账户。')
            return 1
        account, password = cred
    else:
        print(f'  沿用已有任务的账户: {account}')
        cred = read_autologon_password()
        password = cred[1] if cred else None
        if not password:
            got = ask_password()
            if not got:
                return 1
            account, password = got

    print(f'  创建任务 {TASK}')
    print(f'    触发: 系统启动时（不需要任何人登录）')
    print(f'    账户: {account}（最高权限，Password 类型）')
    print(f'    动作: {ACTION}')

    cmd = [SCHTASKS, '/create', '/tn', TASK, '/tr', f'"{ACTION}"',
           '/sc', 'onstart', '/ru', account, '/rp', password,
           '/rl', 'highest', '/f']
    r = run(cmd)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip()
        print(f'  ❌ 创建失败: {msg}')
        if '1326' in msg or '登录失败' in msg:
            print('     密码不对，或该账户不允许作为批处理作业登录。')
        return 1
    print('  ✅ 任务已创建')

    # ── 设置：无时限 / 错过就启动 / 不重复开 ──
    ps = (
        f"$n='{TASK}';"
        f"$s=Get-ScheduledTask -TaskName $n -ErrorAction Stop;"
        f"$s.Settings.ExecutionTimeLimit='PT0S';"
        f"$s.Settings.StartWhenAvailable=$true;"
        f"$s.Settings.DisallowStartIfOnBatteries=$false;"
        f"$s.Settings.StopIfGoingOnBatteries=$false;"
        f"$s.Settings.MultipleInstances='IgnoreNew';"
        f"Set-ScheduledTask -TaskName $n -Settings $s.Settings | Out-Null;"
        f"$x=(Get-ScheduledTask -TaskName $n).Settings;"
        f"'  执行时限 : '+$x.ExecutionTimeLimit"
    )
    r = run([powershell_exe(), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps])
    if r.returncode == 0:
        print((r.stdout or '').strip())
        if 'PT0S' in (r.stdout or ''):
            print('  ✅ 已取消运行时长限制（无限制运行）')
        else:
            print('  ⚠️  执行时限没改成 PT0S，请把上面这行发给 AI')
    else:
        print(f'  ⚠️  设置调整失败: {(r.stderr or r.stdout).strip()[:200]}')

    print()
    print('  完成。现在开机会自动启动 DMR（session 0，无窗口）。')
    print('  验证: 双击 Check_After_Reboot.bat，第 7 节会显示任务状态。')
    print('  撤销: python tools\\install_boot_task.py --remove')
    return 0


def main():
    ap = argparse.ArgumentParser(description='注册/注销开机自动启动任务')
    ap.add_argument('--remove', action='store_true', help='删除任务')
    ap.add_argument('--status', action='store_true', help='只看状态')
    ap.add_argument('--no-elevate', action='store_true', help='不自动申请管理员')
    args = ap.parse_args()

    if not IS_WIN:
        print('  只支持 Windows。')
        return 1

    if args.status:
        return status()

    if not is_admin():
        if args.no_elevate:
            print('  ❌ 需要管理员权限。请右键 -> 以管理员身份运行。')
            return 1
        print('  需要管理员权限，正在申请（会弹 UAC，请点"是"）...')
        if elevate():
            return 0
        print('  ❌ 提权失败。请手动右键本文件所在终端 -> 以管理员身份运行。')
        return 1

    return remove() if args.remove else create()


if __name__ == '__main__':
    sys.exit(main())
