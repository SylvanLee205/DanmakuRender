"""创建 GitHub Release v5.1.0。

用 GitHub REST API。需要一个 token —— 优先从环境变量 / git credential 取。
如果取不到，会提示用户手动创建（并给出准备好的 notes 文件）。
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

REPO = 'SylvanLee205/DanmakuRender'
TAG = 'v5.1.0'
NAME = 'v5.1.0 —— 录制状态持久化 + 全链路稳定性加固'
NOTES = r'F:\DanmakuRender_Mod\docs\RELEASE-v5.1.0.md'

body = open(NOTES, encoding='utf-8').read()

print('=' * 78)
print(f'创建 GitHub Release: {TAG}')
print('=' * 78)
print(f'  仓库: {REPO}')
print(f'  标题: {NAME}')
print(f'  Notes: {len(body)} 字符（来自 {os.path.basename(NOTES)}）')

# ── 找 token ──
token = None
for env in ('GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_PAT'):
    if os.environ.get(env):
        token = os.environ[env]
        print(f'  token 来源: 环境变量 {env}')
        break

if not token:
    # 尝试从 git credential helper 取
    print('  环境变量没有 token，尝试 git credential helper...')
    try:
        r = subprocess.run(
            ['git', 'credential', 'fill'],
            input='protocol=https\nhost=github.com\n\n',
            capture_output=True, text=True, timeout=30)
        for line in (r.stdout or '').split('\n'):
            if line.startswith('password='):
                token = line.split('=', 1)[1].strip()
                print('  ✅ 从 git credential 取到 token')
                break
    except Exception as e:
        print(f'  ⚠️ {type(e).__name__}: {e}')

if not token:
    print()
    print('  ❌ 没有可用的 GitHub token。')
    print()
    print('  Release notes 已准备好，你可以两种方式发布：')
    print(f'    A) 网页手动创建：https://github.com/{REPO}/releases/new'
          f'?tag={TAG}')
    print(f'       把 {NOTES} 的内容粘进描述框')
    print('    B) 提供 token 后重跑本脚本：')
    print('       $env:GITHUB_TOKEN="ghp_xxx"; python tools/create_release.py')
    sys.exit(2)

# ── 创建 release ──
url = f'https://api.github.com/repos/{REPO}/releases'
payload = {
    'tag_name': TAG,
    'name': NAME,
    'body': body,
    'draft': False,
    'prerelease': False,
}
data = json.dumps(payload).encode('utf-8')
req = urllib.request.Request(url, data=data, method='POST')
req.add_header('Authorization', f'Bearer {token}')
req.add_header('Accept', 'application/vnd.github+json')
req.add_header('Content-Type', 'application/json')
req.add_header('User-Agent', 'dsh-release')

try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        j = json.loads(resp.read().decode('utf-8'))
        print()
        print('  ✅ Release 创建成功！')
        print(f'      tag:  {j.get("tag_name")}')
        print(f'      名称: {j.get("name")}')
        print(f'      页面: {j.get("html_url")}')
        print(f'      状态: {"草稿" if j.get("draft") else "已发布"}'
              f'{"（预发布）" if j.get("prerelease") else ""}')
        print()
        print('  自动生成的下载包:')
        for a in (j.get('assets') or []):
            print(f'      {a.get("name")}  {a.get("size", 0)/1024:.0f} KB')
        print(f'      （源码 zip / tar.gz 由 GitHub 自动生成）')
except urllib.error.HTTPError as e:
    detail = (e.read() or b'').decode('utf-8', 'replace')
    print()
    print(f'  ❌ HTTP {e.code}: {e.reason}')
    print(f'      {detail[:500]}')
    if e.code == 401:
        print('      → token 无效或过期')
    elif e.code == 403:
        print('      → token 权限不足，需要 repo 权限')
    elif e.code == 422:
        print('      → 可能该 tag 已有 release，或 tag 不存在')
    sys.exit(1)
except Exception as e:
    print(f'  ❌ {type(e).__name__}: {e}')
    sys.exit(1)
