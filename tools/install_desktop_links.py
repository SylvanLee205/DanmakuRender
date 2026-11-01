"""在桌面创建**真正的快捷方式**（.lnk），指向项目里的启动脚本。

为什么不用把 .bat 复制到桌面
--------------------------
以前桌面上的 `DMR-启动.bat` 之类都是**副本**。项目一改、路径一挪，
桌面那份就变成孤儿；而且改一次要重新拷一次。

现在改成 .lnk：
    * 指向项目里的真实文件，改代码不用重拷
    * 项目换目录只要重跑一次本脚本
    * 双击行为和直接双击项目里的 bat 完全一样

顺带做一件清理：桌面上那些**旧的同名 .bat 副本**会被移到
`backups/desktop-shortcuts-<日期>/`（不是删除，随时能拿回来）。
用户自己的 yml 模板（比如 DMR-某某.yml）绝对不会被碰。

用法：
    python tools\\install_desktop_links.py             # 创建/更新快捷方式
    python tools\\install_desktop_links.py --all       # 连"推送全部"也放上
    python tools\\install_desktop_links.py --remove    # 只删本脚本创建的快捷方式
    python tools\\install_desktop_links.py --dry-run   # 只看会做什么
"""
import argparse
import datetime
import os
import shutil
import subprocess
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

# ⚠️ 必须用绝对路径：venv 里的 python 进程 PATH 不含 PowerShell 目录，
#    直接 subprocess.run(['powershell', ...]) 会 FileNotFoundError。
#    （2026-10-19 在 stop_dmr.py 上踩过同样的坑）
from DMR.paths import powershell_exe  # noqa: E402

#: (桌面显示名, 项目内目标文件, 说明)
LINKS = [
    ('DMR-启动',        'Start_DMR.bat',        '启动 DMR 录制（有窗口，崩溃自动重启）'),
    ('DMR-停止',        'Stop_DMR.bat',         '优雅停止 DMR 和所有录制子进程'),
    ('DMR-看实时日志',  'Watch_DMR_Log.bat',    '实时看日志和状态（没有窗口时用）'),
    ('DMR-添加主播',    'Add_Room.bat',         '粘贴直播间链接即可新增主播'),
    ('DMR-重启后检查',  'Check_After_Reboot.bat', '重启后确认录制是否正常'),
    ('DMR-体检',        'Doctor.bat',           '出任何问题先跑这个'),
]

EXTRA_LINKS = [
    ('DMR-推送全部',    'Push_All.bat',         '把项目推送到两个 GitHub 仓库'),
]


def desktop_dir() -> str:
    """拿真实的桌面路径（兼容 OneDrive 重定向）。"""
    try:
        r = subprocess.run(
            [powershell_exe(), '-NoProfile', '-Command',
             "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
        d = (r.stdout or '').strip()
        if d and os.path.isdir(d):
            return d
    except Exception:
        pass
    return os.path.join(os.path.expanduser('~'), 'Desktop')


def _ps_quote(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def create_links(links, desk, dry=False):
    """生成一个临时 ps1 批量创建 .lnk（一次调用，避免逐条启动 PowerShell）。"""
    lines = [
        # 让 PowerShell 的输出按 UTF-8 出来，否则 Python 读到的是 GBK 字节，
        # 控制台上这些中文快捷方式名会显示成乱码。
        '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8',
        '$ErrorActionPreference = "Stop"',
        '$ws = New-Object -ComObject WScript.Shell',
        f'$desk = {_ps_quote(desk)}',
        f'$proj = {_ps_quote(PROJ)}',
        '',
    ]
    made = []
    for i, (name, target, desc) in enumerate(links):
        src = os.path.join(PROJ, target)
        if not os.path.exists(src):
            print(f'  ⏭  跳过 {name}：缺少 {target}')
            continue
        lnk = os.path.join(desk, name + '.lnk')
        # ⚠️ 不要用 { } 把这几行包起来：PowerShell 里 { } 是**脚本块字面量**，
        #    写成一堆 { ... } 只会构造对象、根本不会执行，而且退出码还是 0
        #    —— 表现得像"运行成功但什么都没做"。（2026-11-02 踩过）
        lines += [
            f'$s{i} = $ws.CreateShortcut({_ps_quote(lnk)})',
            f'$s{i}.TargetPath = {_ps_quote(src)}',
            f'$s{i}.WorkingDirectory = $proj',
            f'$s{i}.Description = {_ps_quote(desc)}',
            f'$s{i}.IconLocation = "$env:SystemRoot\\System32\\shell32.dll,3"',
            f'$s{i}.Save()',
            f'Write-Output ("OK " + {_ps_quote(lnk)})',
        ]
        made.append(lnk)

    if dry:
        print(f'  DRY-RUN：将创建 {len(made)} 个快捷方式到 {desk}')
        for m in made:
            print(f'    {m}')
        return 0

    script = os.path.join(PROJ, '.temp', '_mklinks.ps1')
    os.makedirs(os.path.dirname(script), exist_ok=True)
    # UTF-8 with BOM：Windows PowerShell 5.1 读中文必须带 BOM，否则乱码
    with open(script, 'w', encoding='utf-8-sig') as f:
        f.write('\r\n'.join(lines))

    try:
        r = subprocess.run(
            [powershell_exe(), '-NoProfile', '-ExecutionPolicy', 'Bypass',
             '-File', script],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            stdin=subprocess.DEVNULL, timeout=120)
        out = (r.stdout or '')
        for line in out.splitlines():
            if line.startswith('OK '):
                print(f'  ✅ {os.path.basename(line[3:].strip())}')
        if r.returncode != 0:
            print(f'  ❌ 创建失败: {(r.stderr or out).strip()[:300]}')
            return 1
        n_ok = sum(1 for line in out.splitlines() if line.startswith('OK '))
        print(f'  共创建 {n_ok} 个快捷方式 -> {desk}')
        return 0
    finally:
        try:
            os.remove(script)
        except OSError:
            pass


def clean_legacy_copies(links, desk, dry=False):
    """把桌面上**同名的旧 .bat 副本**移到 backups/ 里（不直接删）。"""
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    dest = os.path.join(PROJ, 'backups', f'desktop-shortcuts-{stamp}')
    moved = []
    for name, _, _ in links:
        legacy = os.path.join(desk, name + '.bat')
        if not os.path.exists(legacy):
            continue
        # 安全阀：只搬"确实是本项目脚本拷贝"的文件。用户自己写的同名脚本
        # 如果内容里没有这些特征，就原样留着。
        try:
            with open(legacy, 'rb') as f:
                head = f.read(8192).decode('utf-8', 'ignore').lower()
        except OSError:
            continue
        if 'dmr' not in head and 'danmaku' not in head:
            print(f'  ⏭  保留 {name}.bat（看起来不是本项目的脚本）')
            continue
        moved.append((legacy, dest))

    if not moved:
        return 0
    if dry:
        for p, _ in moved:
            print(f'  DRY-RUN：将移走旧副本 {os.path.basename(p)}')
        return 0

    os.makedirs(dest, exist_ok=True)
    for p, _ in moved:
        try:
            shutil.move(p, os.path.join(dest, os.path.basename(p)))
            print(f'  🧹 旧副本已移入 {os.path.relpath(dest, PROJ)}: {os.path.basename(p)}')
        except OSError as e:
            print(f'  ⚠️  移不动 {os.path.basename(p)}: {e}')
    return len(moved)


def remove_links(links, desk):
    n = 0
    for name, _, _ in links:
        p = os.path.join(desk, name + '.lnk')
        if os.path.exists(p):
            try:
                os.remove(p)
                print(f'  🗑  已删除 {name}.lnk')
                n += 1
            except OSError as e:
                print(f'  ⚠️  删不掉 {name}.lnk: {e}')
    print(f'  共删除 {n} 个')
    return 0


def main():
    ap = argparse.ArgumentParser(description='在桌面创建项目脚本的快捷方式')
    ap.add_argument('--all', action='store_true', help='包含"推送全部"等附加脚本')
    ap.add_argument('--remove', action='store_true', help='删除已创建的快捷方式')
    ap.add_argument('--keep-legacy', action='store_true', help='不动桌面上的旧 .bat 副本')
    ap.add_argument('--dry-run', action='store_true', help='只看会做什么')
    args = ap.parse_args()

    links = LINKS + (EXTRA_LINKS if args.all else [])
    desk = desktop_dir()
    print(f'  桌面目录: {desk}')
    print(f'  项目目录: {PROJ}')
    print()

    if args.remove:
        return remove_links(links, desk)

    if not args.keep_legacy:
        clean_legacy_copies(links, desk, dry=args.dry_run)
    return create_links(links, desk, dry=args.dry_run)


if __name__ == '__main__':
    sys.exit(main())
