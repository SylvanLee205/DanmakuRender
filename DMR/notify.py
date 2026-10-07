"""推送通知模块（Server酱³ / PushDeer）。

⚠️ 换行格式（2026-10-07 实测确定）：
    Server酱³ 按 **Markdown** 解析 desp。
        - 纯 "\\n"           -> 手机列表页看着像换行，点进"原文"就没了
        - "<br>"             -> 原样显示成文本，无效
        - "两空格 + \\n"     -> ✅ 正确换行（Markdown 硬换行语法）
    所以本模块统一用 `_nl()` 生成换行：'  \n'（两个空格 + 换行）。

用法：
    from DMR.notify import notify
    notify('标题', ['第一行', '第二行'])
"""
import os
import subprocess
import time

API_URL = ('https://17530.push.ft07.com/send/'
           'sctp17530thl3urer2dsbnw3rnqyxzep.send')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TITLE_FILE = os.path.join(ROOT, 'notify_title.txt')
CONTENT_FILE = os.path.join(ROOT, 'notify_content.txt')

# Markdown 硬换行：两个空格 + 换行符
# 为什么不能用 <br>：实测会原样显示成 "<br>" 文本
_NL = '  \n'


def _join(lines):
    """把多行拼成 Server酱³ 能正确换行的格式。"""
    return _NL.join(str(x) for x in lines)


def send(title, lines, timeout=15):
    """发送通知。lines 可以是字符串列表，会自动按 Markdown 硬换行拼接。

    失败**不抛异常** —— 通知不能影响录制主流程。
    返回 True/False。
    """
    try:
        content = lines if isinstance(lines, str) else _join(lines)
        with open(TITLE_FILE, 'w', encoding='utf-8', newline='') as f:
            f.write(title)
        with open(CONTENT_FILE, 'w', encoding='utf-8', newline='') as f:
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


def disk_free_gb(path='F:\\'):
    """磁盘剩余空间（GB）。返回 None 表示查不到。"""
    try:
        import shutil
        return shutil.disk_usage(path).free / 1024 / 1024 / 1024
    except Exception:
        return None


if __name__ == '__main__':
    # 手动测试
    ok = send('DanmakuRender 通知测试',
              ['第一行', '第二行（应该有换行）', '', '第四行'])
    print(f'发送{"成功" if ok else "失败"}')
    print(f'标题文件: {TITLE_FILE}')
    print(f'正文文件: {CONTENT_FILE}')
