"""重启通知：生成内容 + 发送（由 DMR 在启动成功后调用）。

⚠️ 换行格式见 DMR/notify.py 的说明：Server酱³ 按 Markdown 解析，
   必须用"两空格 + \n"（硬换行），纯 \n 和 <br> 都不行（实测）。

也可以单独运行做手动测试：
    python tools\\gen_restart_notify.py
"""
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from DMR.notify import send, disk_free_gb          # noqa: E402

STATE_FILE = os.path.join(ROOT, '.temp', 'restart_history.json')
VERSION_FILE = os.path.join(ROOT, 'DMR', '__init__.py')

FLAP_WINDOW = 3600      # 统计窗口（秒）
FLAP_THRESHOLD = 3      # 窗口内超过这个次数算频繁重启
MIN_COUNT_GAP = 600     # 距上次计数不足这个秒数不重复计数（防调试时误报）
DISK_WARN_GB = 30       # 剩余磁盘低于这个值就在通知里告警


def _ps(cmd):
    import subprocess
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=20)
        return ((r.stdout or '') + (r.stderr or '')).strip()
    except Exception:
        return ''


def version():
    """读版本号：优先 DMR 包里的 VERSION，退回 DMR/__init__.py 里的字面量。"""
    try:
        from DMR import VERSION as v
        return str(v)
    except Exception:
        pass
    try:
        t = open(VERSION_FILE, encoding='utf-8', errors='replace').read()
        m = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", t)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ''


def cd2_ok():
    """CD2 服务版是否正常（服务在跑 + 19798 在监听）。"""
    try:
        st = _ps("(Get-Service CloudDrive2 -ErrorAction SilentlyContinue).Status.ToString()")
        port = _ps("(Get-NetTCPConnection -LocalPort 19798 -State Listen "
                   "-ErrorAction SilentlyContinue | Measure-Object).Count")
        if st == 'Running' and port not in ('', '0'):
            return True, '正常'
        if st == 'Running':
            return False, '服务在跑但端口未监听'
        return False, (st or '服务不存在')
    except Exception as e:
        return False, f'查询失败({type(e).__name__})'


def bump_and_get_restarts():
    """记录本次启动，返回 (总次数, 窗口内次数)。

    MIN_COUNT_GAP：调试时可能几分钟内手动重启多次，每次都计数会误报
    "频繁重启"。所以距上次计数不足 10 分钟时不重复计数。
    真正的崩溃循环（10 秒重试）间隔远小于 10 分钟，仍能被识别。
    """
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    now = time.time()
    try:
        d = json.load(open(STATE_FILE, encoding='utf-8')) if os.path.exists(STATE_FILE) else {}
    except Exception:
        d = {}
    times = [t for t in (d.get('times') or []) if isinstance(t, (int, float))]
    times = [t for t in times if now - t < 7 * 86400]
    last = times[-1] if times else 0
    if now - last >= MIN_COUNT_GAP:
        times.append(now)
        try:
            json.dump({'times': times, 'count': len(times), 'last': now},
                      open(STATE_FILE, 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=2)
        except Exception:
            pass
    return len(times), len([t for t in times if now - t < FLAP_WINDOW])


def build(task_names=None, task_count=None):
    """生成 (标题, [正文行...])。

    设计取舍（2026-10-07 按用户反馈调整）：
      ✗ 启动时间     -> 删。通知本身自带时间，重复没意义
      ✗ 近 24h 录制  -> 删。启动时看它没有行动价值
      ✗ 正在录制     -> 删。启动瞬间必然还没开始录，只会显示"暂无"
      ✓ 主播加载     -> 从"32 个"改成**列出名字**，否则不知道是谁
      ✓ CD2 状态     -> 留。启动时最该确认的就是"上传通道通不通"
      ✓ 磁盘剩余     -> 新增。快满了会导致录制失败，是真实风险
    """
    _, recent = bump_and_get_restarts()
    ok, cd2_txt = cd2_ok()
    free_gb = disk_free_gb('F:\\')
    ver = version()

    head = 'DanmakuRender 已成功复活' + (f'（v{ver}）' if ver else '')
    L = [head, '']

    names = list(task_names or [])
    n = task_count if task_count is not None else len(names)
    if names:
        L.append(f'主播加载：{n} 个，全部成功')
        L.append('、'.join(names))
    else:
        L.append(f'主播加载：{n} 个')

    L.append('')
    L.append('云端通道：CD2 正常' if ok else f'⚠️ 云端通道：CD2 {cd2_txt}')

    if free_gb is not None:
        if free_gb < DISK_WARN_GB:
            L.append(f'⚠️ 磁盘剩余：{free_gb:.1f} GB（偏低，请清理）')
        else:
            L.append(f'磁盘剩余：{free_gb:.0f} GB')

    if recent >= FLAP_THRESHOLD:
        L.append('')
        L.append(f'⚠️ 频繁重启：最近 1 小时 {recent} 次，请检查日志')

    title = (f'⚠️ DanmakuRender 频繁重启（{recent}次/时）'
             if recent >= FLAP_THRESHOLD else 'DanmakuRender 已启动')
    return title, L


def notify(task_names=None, task_count=None, quiet=True):
    """生成并发送启动通知。返回 (ok, title, lines)。"""
    try:
        title, lines = build(task_names=task_names, task_count=task_count)
        ok = send(title, lines)
        if not quiet:
            print(f'[notify] {"已发送" if ok else "发送失败"}  标题: {title}')
            for l in lines:
                print(f'    {l}')
        return ok, title, lines
    except Exception as e:
        if not quiet:
            print(f'[notify] 异常: {type(e).__name__}: {e}')
        return False, '', []


if __name__ == '__main__':
    # 手动测试：不带参数就用一个假的示例名单，方便看排版
    ok, title, lines = notify(
        task_names=['苏苏没烦恼', 'vvu', '掉了颗兔牙', '相扑猫', '小鱼大王',
                    '年狗大号', '荞麦拌面', '小玟不是小玫', '哭哭不嘻嘻'],
        task_count=32, quiet=False)
    print(f'\n  结果: {"✅ 发送成功" if ok else "❌ 发送失败"}')
