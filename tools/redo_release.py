"""重做 v5.1.0 Release：删除旧的 → 重打 tag → 重新创建。

为什么重做：第一次发布后发现源码包里漏了 configs/global.yml
（用户个人配置）和一个 BROKEN 文件。已清理并重新提交，
所以 tag 和 release 都要重建。
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = 'SylvanLee205/DanmakuRender'
TAG = 'v5.1.0'
NAME = 'v5.1.0 —— 录制状态持久化 + 全链路稳定性加固'
NOTES = r'F:\DanmakuRender_Mod\docs\RELEASE-v5.1.0.md'
REPO_DIR = r'F:\DanmakuRender_Mod'
GIT = r'C:\Program Files\Git\cmd\git.exe'


def api(method, path, token=None, payload=None):
    url = f'https://api.github.com/repos/{REPO}{path}'
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('Content-Type', 'application/json')
    req.add_header('User-Agent', 'dsh-release')
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode('utf-8')
        return json.loads(body) if body.strip() else {}


def git(*args):
    r = subprocess.run([GIT] + list(args), cwd=REPO_DIR, capture_output=True,
                       text=True, encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout or ''), (r.stderr or '')


# ── token ──
token = None
for env in ('GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_PAT'):
    if os.environ.get(env):
        token = os.environ[env]
        break
if not token:
    r = subprocess.run(['git', 'credential', 'fill'],
                       input='protocol=https\nhost=github.com\n\n',
                       capture_output=True, text=True, timeout=30)
    for line in (r.stdout or '').split('\n'):
        if line.startswith('password='):
            token = line.split('=', 1)[1].strip()
            break

print('=' * 78)
print('重做 Release v5.1.0')
print('=' * 78)

# ── 1. 删除旧的 release ──
print('1. 删除旧的 GitHub Release')
try:
    rels = api('GET', '/releases', token)
    for r in rels:
        if r.get('tag_name') == TAG:
            api('DELETE', f'/releases/{r["id"]}', token)
            print(f'   ✅ 已删除 release id={r["id"]}')
    else:
        if not any(r.get('tag_name') == TAG for r in rels):
            print('   （没有同 tag 的 release）')
except urllib.error.HTTPError as e:
    print(f'   ⚠️ HTTP {e.code}: {(e.read() or b"").decode("utf-8","replace")[:200]}')

# ── 2. 重新打 tag ──
print()
print('2. 在当前 HEAD 重新打 tag')
rc, out, err = git('tag', '-d', TAG)
print(f'   删除本地旧 tag: {"✅" if rc == 0 else err.strip()[:60]}')
rc, out, err = git('rev-parse', 'HEAD')
head = out.strip()
print(f'   HEAD = {head[:12]}')
rc, out, err = git('tag', '-a', TAG, '-m',
                   'DanmakuRender-5 魔改版 v5.1.0\n\n'
                   '面向「抖音录播 → 弹幕渲染 → 百度网盘归档」的长期无人值守录制工具。\n\n'
                   '本版重点：\n'
                   '  · 合并上游 ab8d3f3「录制状态持久化与可靠恢复」\n'
                   '  · 修复合并引入的 5 个问题（xml2ass 导入、state_repo 注入、\n'
                   '    GOP 调用点、跳过上传规则调用点、0 字节保险闸）\n'
                   '  · 新增启动自检（配置完整性 + 关键名字）\n'
                   '  · 新增 4 套审计工具与配置保护机制\n\n'
                   '验证：437 个单元测试全部通过；录制/渲染/上传/恢复已在线验证。')
print(f'   创建 tag: {"✅" if rc == 0 else err.strip()[:80]}')
rc, out, err = git('push', '-f', 'origin', TAG)
print(f'   推送 tag: {"✅" if rc == 0 else err.strip()[:80]}')
time.sleep(3)

# ── 3. 创建 release ──
print()
print('3. 创建新 Release')
body = open(NOTES, encoding='utf-8').read()
try:
    j = api('POST', '/releases', token, {
        'tag_name': TAG, 'name': NAME, 'body': body,
        'draft': False, 'prerelease': False,
    })
    print('   ✅ 创建成功')
    print(f'      tag:  {j.get("tag_name")}')
    print(f'      页面: {j.get("html_url")}')
    print(f'      发布: {j.get("published_at")}')
except urllib.error.HTTPError as e:
    print(f'   ❌ HTTP {e.code}: {(e.read() or b"").decode("utf-8","replace")[:400]}')
    sys.exit(1)
