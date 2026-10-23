# -*- coding: utf-8 -*-
"""从剪贴板（或手动粘贴）读取抖音直播间链接，自动生成 configs/DMR-<主播名>.yml。

为什么要有这个脚本
------------------
手工加一个主播要：复制 DMR-灰蒙蒙.yml -> 改 url -> 改 output_dir -> 改文件名 ->
拖进 configs。四步全靠手，容易漏。而实际上一个任务真正个性化的只有两样：
**直播间地址** 和 **输出目录**（其余全部由 configs/global.yml 全局调控）。

所以这里做的就是把这两样自动化：
    复制直播间链接 -> 双击 DMR-添加主播.bat -> 完事

主播名不用手填：直接从抖音接口取（DMR.LiveAPI.douyin.get_info）。
取不到（比如主播下播、接口抽风）时，会请你手动敲一个名字，不会卡住。

生成后 DMR 会在下一个配置检查周期自动加载新文件（Config/__init__.py:225
检测新增的 DMR-*.yml 并 add_task_config），**不需要重启**。

用法：
    .venv\\Scripts\\python.exe tools\\add_room.py              # 读剪贴板
    .venv\\Scripts\\python.exe tools\\add_room.py --dry-run    # 只预览，不写文件
    .venv\\Scripts\\python.exe tools\\add_room.py "https://..."  # 直接给链接
"""
import argparse
import glob
import os
import re
import sys

# 控制台可能是 GBK（chcp 936），这里的中文 print 会 UnicodeEncodeError 直接崩。
# 2026-10-20 实测：stop_dmr.py 就栽在这上面，无人值守脚本必须容忍编码问题。
try:
    sys.stdout.reconfigure(errors='replace')
    sys.stderr.reconfigure(errors='replace')
except Exception:
    pass

UP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIGS = os.path.join(UP, 'configs')

TEMPLATE = """# DMR 录制任务 —— 由 tools/add_room.py 自动生成
# 添加时间: {ts}
# 主播: {name}    房间号: {rid}
# 除直播间地址与输出目录外，其余参数均由 configs/global.yml 全局调控。
common_event_args:
  auto_render: True
  auto_upload: True
  auto_clean: True
  auto_transcode: False

download_args:
  dltype: live
  url: '{url}'
  output_dir: ./直播回放/{name}
  output_name: '{{STREAMER.NAME}}-{{CTIME.YEAR}}年{{CTIME.MONTH:02d}}月{{CTIME.DAY:02d}}日{{CTIME.HOUR:02d}}点{{CTIME.MINUTE:02d}}分'
"""

# Windows 文件名非法字符
BAD_CHARS = '\\/:*?"<>|\r\n\t'


def _read_clipboard_ctypes(retries: int = 5):
    """用 ctypes 读剪贴板。返回 ``(是否读到剪贴板, 文本)``。

    ``(True, '')`` = 剪贴板确实没有文本（正常情况，不该再折腾）；
    ``(False, '')`` = 根本没拿到剪贴板访问权（句柄失效/被占用），该走兜底。
    """
    try:
        import ctypes
        import time
        CF_UNICODETEXT = 13
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        # OpenClipboard 会被"正握着剪贴板的进程"拒绝（复制图片、某些输入法、
        # 远程桌面剪贴板同步时很常见），重试几次再放弃。
        opened = False
        for _ in range(max(1, retries)):
            if user32.OpenClipboard(None):
                opened = True
                break
            time.sleep(0.1)
        if not opened:
            return (False, '')
        try:
            # 先确认格式真的在，避免 GetClipboardData 返回奇怪句柄
            if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return (True, '')
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return (True, '')
            kernel32.GlobalLock.restype = ctypes.c_wchar_p
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            text = kernel32.GlobalLock(handle)
            if not text:
                return (True, '')
            kernel32.GlobalUnlock(handle)
            return (True, text)
        finally:
            user32.CloseClipboard()
    except Exception:
        return (False, '')


def _read_clipboard_powershell() -> str:
    """ctypes 拿不到剪贴板时的兜底：PowerShell 的 Get-Clipboard。

    ``stdin=DEVNULL`` 是必须的：PowerShell 会吃掉继承来的 stdin，
    2026-10-23 实测把用户粘贴的那一行链接吞掉，表现为"脚本说没输入内容"。
    """
    try:
        import subprocess
        out = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             'Get-Clipboard -Raw -Format Text -ErrorAction SilentlyContinue'],
            capture_output=True, timeout=15, stdin=subprocess.DEVNULL)
        if out.returncode != 0:
            return ''
        return out.stdout.decode('utf-8', errors='replace').strip('\r\n')
    except Exception:
        return ''


def read_clipboard() -> str:
    """读剪贴板文本；读不到返回空串（不抛异常）。

    2026-10-23 加固：实测极少数情况下 ctypes 直接读剪贴板会让进程**段错误**，
    控制台不打印任何东西就消失，用户看到的就是"双击后只弹一句请按任意键继续"。
    根因是剪贴板被别的进程占用/句柄失效。现在：
      1) OpenClipboard 失败会重试（占用是常见情况）
      2) 先确认 CF_UNICODETEXT 可用再取句柄
      3) 只有"没拿到剪贴板访问权"才退回 PowerShell；剪贴板确实是空的不兜底
         （免得每次空剪贴板都白等一秒，还顺带吃掉用户的输入）
    """
    ok, text = _read_clipboard_ctypes()
    if ok:
        return text
    return _read_clipboard_powershell()


UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def expand_short_links(text: str) -> str:
    """抖音分享出来常是 v.douyin.com/xxxxx 短链，先展开成真实地址再解析。"""
    shorts = re.findall(r'https?://v\.douyin\.com/[A-Za-z0-9_\-/]+', text)
    if not shorts:
        return text
    try:
        import requests
    except Exception:
        return text
    for s in shorts:
        try:
            r = requests.head(s, allow_redirects=True, timeout=10,
                              headers={'User-Agent': UA})
            text += '\n' + (r.url or '')
        except Exception:
            pass
    return text


def parse_room_ids(text: str) -> list:
    """从任意文本里抽出抖音直播间号（支持一次粘贴多个链接）。"""
    found = []
    # 0) 短链先展开
    text = expand_short_links(text)
    # 1) 标准直播间链接 https://live.douyin.com/865102911165
    for m in re.finditer(r'live\.douyin\.com/(\d{6,})', text):
        if m.group(1) not in found:
            found.append(m.group(1))
    if found:
        return found
    # 2) 纯房间号（拖进来的可能只有一串数字）
    for m in re.finditer(r'(?<!\d)(\d{8,})(?!\d)', text):
        if m.group(1) not in found:
            found.append(m.group(1))
    return found


def sanitize(name: str) -> str:
    """把主播名整理成能当文件名/目录名的形式。"""
    for c in BAD_CHARS:
        name = name.replace(c, '')
    # 主播名常混着半角/全角括号（实测有 "APEX-QQ (皮蛋）" 这种），统一成全角，
    # 免得下游按半角括号切分字符串时出问题。
    name = name.replace('(', '（').replace(')', '）')
    name = re.sub(r'\s+', ' ', name).strip().strip('.')
    return name[:40]


def fetch_name(rid: str) -> str:
    """用 DMR 自己的抖音接口取主播昵称；失败返回空串。"""
    try:
        sys.path.insert(0, UP)
        from DMR.LiveAPI.douyin import douyin
        api = douyin(rid)
        _, uname, _, _ = api.get_info()
        return sanitize(uname or '')
    except Exception as e:
        print('      (取主播名失败: %s)' % str(e)[:60])
        return ''


def existing_room_ids() -> dict:
    """扫描 configs 下已有的任务，返回 {room_id: 文件名}。"""
    out = {}
    for f in glob.glob(os.path.join(CONFIGS, 'DMR-*.yml')):
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                txt = fh.read()
            for m in re.finditer(r'live\.douyin\.com/(\d{6,})', txt):
                out.setdefault(m.group(1), os.path.basename(f))
        except Exception:
            pass
    return out


def add_one(rid: str, dry_run: bool, existing: dict) -> bool:
    url = 'https://live.douyin.com/%s' % rid
    base = os.path.basename(existing.get(rid, ''))
    if rid in existing:
        print('  - 跳过 %s：已存在（%s）' % (rid, base))
        return False

    print('  + 房间 %s' % rid)
    name = fetch_name(rid)
    if not name:
        print('      抖音接口没返回主播名，请手动输入（直接回车用房间号代替）：')
        try:
            name = sanitize(input('      主播名 > ').strip())
        except EOFError:
            name = ''
        if not name:
            name = rid
    print('      主播名: %s' % name)

    target = os.path.join(CONFIGS, 'DMR-%s.yml' % name)
    if os.path.exists(target):
        print('      ! 文件已存在，改名追加房间号: DMR-%s-%s.yml' % (name, rid[-4:]))
        target = os.path.join(CONFIGS, 'DMR-%s-%s.yml' % (name, rid[-4:]))

    content = TEMPLATE.format(
        ts=__import__('time').strftime('%Y-%m-%d %H:%M'),
        name=name, rid=rid, url=url,
    )
    if dry_run:
        print('      [dry-run] 将写入: %s' % os.path.basename(target))
        return True
    with open(target, 'w', encoding='utf-8') as f:
        f.write(content)
    print('      -> 已写入 %s' % os.path.basename(target))
    return True


def main():
    ap = argparse.ArgumentParser(description='粘贴抖音直播间链接即可添加录制任务')
    ap.add_argument('links', nargs='*', help='直播间链接或房间号（不给则读剪贴板）')
    ap.add_argument('--dry-run', action='store_true', help='只预览不写文件')
    args = ap.parse_args()

    raw = ' '.join(args.links)
    if not raw:
        raw = read_clipboard()
        if raw:
            print('从剪贴板读到内容，正在解析…')
    if not raw:
        print('剪贴板里没有文本。请粘贴直播间链接后回车（支持一次粘多个）：')
        try:
            raw = input('> ')
        except EOFError:
            raw = ''

    rids = parse_room_ids(raw)
    if not rids:
        print()
        # 用户什么都没给（空剪贴板 + 空输入）不算错误，别让 bat 弹错误横幅
        benign = not raw.strip()
        print('没认出直播间地址。支持的格式：')
        print('  https://live.douyin.com/865102911165')
        print('  865102911165')
        print('  或者一段包含上面任一种的文字（抖音分享文本也行）')
        if benign:
            print()
            print('（剪贴板是空的，也没有输入内容 —— 先去抖音复制直播间链接再来。）')
        _wait_to_close()
        return 0 if benign else 1

    print()
    print('识别到 %d 个直播间：' % len(rids))
    existing = existing_room_ids()
    added = 0
    for rid in rids:
        if add_one(rid, args.dry_run, existing):
            added += 1

    print()
    if added:
        print('完成：新增 %d 个任务。DMR 会在下一个配置检查周期自动加载，无需重启。' % added)
        print('（想立刻生效可以去 DMR-看实时日志 确认，或重启一次。）')
    else:
        print('没有新增任务。')
    _wait_to_close()
    return 0


def _wait_to_close() -> None:
    """等用户看一眼结果再关窗口（双击运行时才有意义）。

    放在脚本里而不是 bat 的 pause：这样万一脚本自己崩了，bat 能看到非 0
    退出码并给出明确提示，而不是像以前那样只弹一句"请按任意键继续"。
    """
    print()
    print('按回车键关闭本窗口…')
    try:
        input()
    except EOFError:
        pass


if __name__ == '__main__':
    sys.exit(main())
