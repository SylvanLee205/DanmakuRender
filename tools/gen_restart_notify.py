"""重启通知：生成内容 + 发送。

两个用途：
  1. 被 DMR（main.py）在**成功启动后**调用 —— 这样通知里的状态是真实的
  2. 也可单独运行做手动测试：python tools\\gen_restart_notify.py

为什么由 DMR 发而不是 bat 发：
    bat 在**启动前**发通知，只能说"我要启动了"；
    DMR 在**启动成功后**发，才能说"已经起来了、加载了 N 个主播"，
    而且 DMR 根本没起来时不会误报成功。

为什么不把中文写进 bat：
    cmd.exe 按系统代码页(936/GBK)解析 bat 文件，UTF-8 中文会乱码导致
    命令破碎、无限刷屏（2026-10-07 踩过这个坑）。所以中文一律走本文件。
"""
import json
import os
import re
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TITLE_FILE = os.path.join(ROOT, 'notify_title.txt')
CONTENT_FILE = os.path.join(ROOT, 'notify_content.txt')
STATE_FILE = os.path.join(ROOT, '.temp', 'restart_history.json')
API_URL = ('https://17530.push.ft07.com/send/'
           'sctp17530thl3urer2dsbnw3rnqyxzep.send')

FLAP_WINDOW = 3600      # 统计窗口（秒）
FLAP_THRESHOLD = 3      # 窗口内超过这个次数算频繁重启
MIN_COUNT_GAP = 600     # 距上次计数不足这个秒数就不重复计数
                        # （避免调试期间手动重启几次就误报"频繁重启"）


def ps(cmd):
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=20)
        return ((r.stdout or '') + (r.stderr or '')).strip()
    except Exception:
        return ''


def cd2_ok():
    """CD2 服务版是否正常（服务在跑 + 19798 在监听）。"""
    try:
        st = ps("(Get-Service CloudDrive2 -ErrorAction SilentlyContinue).Status.ToString()")
        port = ps("(Get-NetTCPConnection -LocalPort 19798 -State Listen "
                  "-ErrorAction SilentlyContinue | Measure-Object).Count")
        if st == 'Running' and port not in ('', '0'):
            return True, '正常'
        if st == 'Running':
            return False, '服务在跑但端口未监听'
        return False, (st or '服务不存在')
    except Exception as e:
        return False, f'查询失败({type(e).__name__})'


def recent_render_count(hours=24):
    """近 N 小时渲染出的弹幕版分段数（反映录制活跃度）。"""
    try:
        d = os.path.join(ROOT, '直播回放')
        cutoff = time.time() - hours * 3600
        n = 0
        for name in os.listdir(d):
            sub = os.path.join(d, name)
            if not (os.path.isdir(sub) and name.endswith('（弹幕版）')):
                continue
            for f in os.listdir(sub):
                if f.endswith('.mp4'):
                    try:
                        if os.path.getmtime(os.path.join(sub, f)) >= cutoff:
                            n += 1
                    except Exception:
                        pass
        return n
    except Exception:
        return None


def live_now(log_file=None):
    """当前正在录制的任务名列表。

    判定依据：日志里每个任务**最后一次**出现的 直播开始/直播已结束。
    """
    try:
        if log_file and os.path.exists(log_file):
            logs = [log_file]
        else:
            logdir = os.path.join(ROOT, 'logs')
            logs = [os.path.join(logdir, f) for f in os.listdir(logdir)
                    if f.startswith('DMR-') and f.endswith('.log')]
            logs.sort(key=os.path.getmtime, reverse=True)
            logs = logs[:2]
        last = {}
        for lg in logs:
            try:
                txt = open(lg, encoding='utf-8', errors='replace').read()
            except Exception:
                continue
            for line in txt.split('\n'):
                m = re.search(r'\[liveevents\]\[info\]: (.+?): (直播开始|直播已结束)', line)
                if m:
                    last[m.group(1)] = (m.group(2) == '直播开始')
        return [k for k, v in last.items() if v]
    except Exception:
        return []


def bump_and_get_restarts():
    """记录本次启动时间，返回 (总次数, 窗口内次数)。

    ⚠️ MIN_COUNT_GAP 的作用：
        调试时可能几分钟内手动重启好几次，如果每次都计数，
        就会误报"频繁重启告警"。所以距上次计数不足 10 分钟时，
        **不重复计数**（但仍返回当前统计）。
        真正"崩溃→自动重启"的循环间隔通常是 10 秒 + 启动时间，
        远小于 10 分钟，所以仍能被正确识别。
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


def build(task_count=None, log_file=None):
    """生成标题和正文，返回 (title, content)。"""
    now_str = time.strftime('%Y-%m-%d %H:%M:%S')
    total, recent = bump_and_get_restarts()
    ok, cd2_txt = cd2_ok()
    n_files = recent_render_count()
    lives = live_now(log_file)

    L = ['DanmakuRender 已成功复活。', '']
    L.append(f'启动时间：{now_str}')
    if task_count:
        L.append(f'录制服务：已启动，正在监听 {task_count} 个主播')
    else:
        L.append('录制服务：已启动，正在监听主播')
    L.append('云端通道：CD2 正常' if ok else f'⚠️ 云端通道：CD2 {cd2_txt}')
    if n_files is not None:
        L.append(f'近 24h 录制：{n_files} 个分段')
    if lives:
        L.append('正在录制：' + '、'.join(lives[:6])
                 + (f' 等 {len(lives)} 人' if len(lives) > 6 else ''))
    else:
        L.append('正在录制：暂无（当前无主播开播）')
    if recent >= FLAP_THRESHOLD:
        L.append('')
        L.append(f'⚠️ 频繁重启：最近 1 小时 {recent} 次，请检查日志')

    title = (f'⚠️ DanmakuRender 频繁重启（{recent}次/时）'
             if recent >= FLAP_THRESHOLD else 'DanmakuRender 状态报告')
    return title, '\n'.join(L)


def send(title, content, timeout=15):
    """写文件并用 curl 发送。失败不抛异常（不能影响主流程）。"""
    try:
        with open(TITLE_FILE, 'w', encoding='utf-8', newline='\n') as f:
            f.write(title)
        with open(CONTENT_FILE, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
    except Exception:
        return False
    try:
        r = subprocess.run(
            ['curl.exe', '-s', '-m', str(timeout),
             '--data-urlencode', f'title@{TITLE_FILE}',
             '--data-urlencode', f'desp@{CONTENT_FILE}',
             API_URL],
            capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=timeout + 10)
        return '"code":0' in (r.stdout or '')
    except Exception:
        return False


def notify(task_count=None, log_file=None, quiet=True):
    """一步到位：生成 + 发送。返回 (是否成功, 标题, 正文)。"""
    try:
        title, content = build(task_count=task_count, log_file=log_file)
        ok = send(title, content)
        if not quiet:
            print(f'[notify] {"已发送" if ok else "发送失败"}  标题: {title}')
            for l in content.split('\n'):
                print(f'    {l}')
        return ok, title, content
    except Exception as e:
        if not quiet:
            print(f'[notify] 异常: {type(e).__name__}: {e}')
        return False, '', ''


if __name__ == '__main__':
    ok, title, content = notify(quiet=False)
    print(f'\n  结果: {"✅ 发送成功" if ok else "❌ 发送失败"}')
