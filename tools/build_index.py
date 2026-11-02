"""生成录播索引页（单文件 HTML，双击就能看）。

扫「直播回放/*（弹幕版）/」下的成品，按主播和日期整理成一个网页：
搜主播、筛日期、点开就播放。**不依赖网络**（CSS/JS 全内嵌）。

为什么用网页而不是 Excel/清单：
    要的是"我想回看某天某个主播"这种随手的操作，网页点两下就到，
    而且能直接在浏览器里播放。

用法：
    python tools\\build_index.py               # 生成到 <项目>/index.html
    python tools\\build_index.py --open        # 生成后自动打开
    python tools\\build_index.py --out D:\\x.html

DMR 内部每天 06:00 会自动跑一次（见 DMR/maintenance.py）。
"""
import argparse
import datetime
import os
import re
import subprocess
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

VIDEO_EXT = ('.mp4', '.mkv', '.flv', '.ts', '.mov')
DM_MARK = '（弹幕版）'

#: 文件名里的时间：2026年11月01日16点50分
_TIME_RE = re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})点(\d{1,2})分')
#: 兜底：20261101-165017 / 2026-11-01
_TIME_RE2 = re.compile(r'(20\d{2})[-_]?(\d{2})[-_]?(\d{2})[-_ ]?(\d{2})?[-_:]?(\d{2})?')

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
     background:#0f1115;color:#e6e8ee;padding:24px}
h1{font-size:20px;font-weight:600;margin-bottom:6px}
.sub{color:#8b93a7;font-size:13px;margin-bottom:20px}
.bar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px}
input,select{background:#1a1e26;border:1px solid #2a3040;color:#e6e8ee;
     padding:8px 12px;border-radius:8px;font-size:14px;outline:none}
input:focus,select:focus{border-color:#4a7cff}
input[type=search]{min-width:260px}
.stats{display:flex;gap:18px;color:#8b93a7;font-size:13px;margin-bottom:18px;flex-wrap:wrap}
.stats b{color:#e6e8ee;font-weight:600}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-weight:500;color:#8b93a7;font-size:12px;
   padding:8px 10px;border-bottom:1px solid #232936;position:sticky;top:0;background:#0f1115}
td{padding:9px 10px;border-bottom:1px solid #1a1e26;vertical-align:middle}
tr:hover td{background:#151922}
.name{color:#e6e8ee;text-decoration:none;word-break:break-all}
.name:hover{color:#4a7cff}
.tag{display:inline-block;padding:1px 8px;border-radius:20px;font-size:12px;
     background:#1f2637;color:#9aa8c7;white-space:nowrap}
.size{color:#8b93a7;font-variant-numeric:tabular-nums;white-space:nowrap}
.empty{color:#8b93a7;padding:40px 0;text-align:center}
.hint{color:#6b7385;font-size:12px;margin-top:22px}
"""

JS = """
const $ = s => document.querySelector(s);
const rows = [...document.querySelectorAll('tbody tr')];
const days = rows.map(r => r.dataset.day).filter(Boolean).sort();
if (days.length) { $('#from').min = days[0]; $('#to').max = days[days.length-1]; }

function apply() {
  const q = $('#q').value.trim().toLowerCase();
  const who = $('#who').value;
  const from = $('#from').value;
  const to = $('#to').value;
  let shown = 0, size = 0;
  for (const r of rows) {
    const ok =
      (!q || r.dataset.search.includes(q)) &&
      (!who || r.dataset.who === who) &&
      (!from || r.dataset.day >= from) &&
      (!to || r.dataset.day <= to);
    r.style.display = ok ? '' : 'none';
    if (ok) { shown++; size += Number(r.dataset.size || 0); }
  }
  $('#shown').textContent = shown;
  $('#shownSize').textContent = (size/1073741824).toFixed(1);
}
['q','who','from','to'].forEach(id => $('#'+id).addEventListener('input', apply));
apply();
"""


def parse_time(name: str):
    """从文件名里取日期时间，取不到返回 (None, '')。"""
    m = _TIME_RE.search(name)
    if m:
        y, mo, d, h, mi = (int(x) for x in m.groups())
        try:
            return datetime.datetime(y, mo, d, h, mi), f'{y:04d}-{mo:02d}-{d:02d}'
        except ValueError:
            pass
    m = _TIME_RE2.search(name)
    if m:
        g = [x for x in m.groups()]
        try:
            y, mo, d = int(g[0]), int(g[1]), int(g[2])
            h = int(g[3]) if g[3] else 0
            mi = int(g[4]) if g[4] else 0
            return datetime.datetime(y, mo, d, h, mi), f'{y:04d}-{mo:02d}-{d:02d}'
        except (ValueError, TypeError):
            pass
    return None, ''


def collect(recordings_root: str):
    """扫描所有弹幕版产物。

    兼容两种布局：
        <root>/<主播>（弹幕版）/*.mp4
        <root>/<主播>/*（弹幕版）*.mp4
    """
    items = []
    if not os.path.isdir(recordings_root):
        return items

    for entry in os.listdir(recordings_root):
        full = os.path.join(recordings_root, entry)
        if not os.path.isdir(full):
            continue
        if DM_MARK in entry:
            streamer = entry.replace(DM_MARK, '').strip()
            for name in os.listdir(full):
                if not name.lower().endswith(VIDEO_EXT):
                    continue
                path = os.path.join(full, name)
                if not os.path.isfile(path):
                    continue
                items.append(_mk_item(path, streamer, name))
        else:
            streamer = entry
            for name in os.listdir(full):
                if DM_MARK not in name or not name.lower().endswith(VIDEO_EXT):
                    continue
                path = os.path.join(full, name)
                if not os.path.isfile(path):
                    continue
                items.append(_mk_item(path, streamer, name))

    items.sort(key=lambda x: (x['sort'], x['streamer']), reverse=True)
    return items


def _mk_item(path, streamer, name):
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    dt, day = parse_time(name)
    if dt is None:
        try:
            dt = datetime.datetime.fromtimestamp(os.path.getmtime(path))
            day = dt.strftime('%Y-%m-%d')
        except OSError:
            dt = datetime.datetime(1970, 1, 1)
            day = ''
    return dict(path=path, name=name, streamer=streamer, size=size,
                dt=dt, day=day, sort=dt.strftime('%Y%m%d%H%M'))


def human(n):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024


def render(items, recordings_root):
    total = sum(i['size'] for i in items)
    streamers = sorted({i['streamer'] for i in items})
    first = items[-1]['dt'] if items else None
    last = items[0]['dt'] if items else None

    opts = ''.join(f'<option value="{s}">{s}</option>' for s in streamers)

    rows = []
    for i in items:
        rel = os.path.relpath(i['path'], os.path.dirname(recordings_root))
        href = rel.replace('\\', '/')
        search = f'{i["streamer"]} {i["name"]}'.lower().replace('"', '')
        rows.append(
            f'<tr data-who="{i["streamer"]}" data-day="{i["day"]}" '
            f'data-size="{i["size"]}" data-search="{search}">'
            f'<td><a class="name" href="{href}" target="_blank">{i["name"]}</a></td>'
            f'<td><span class="tag">{i["streamer"]}</span></td>'
            f'<td class="size">{i["day"]}</td>'
            f'<td class="size">{human(i["size"])}</td>'
            f'</tr>')

    span = ''
    if first and last:
        span = f'<span>时间范围 <b>{first:%Y-%m-%d}</b> ~ <b>{last:%Y-%m-%d}</b></span>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>录播索引 - DanmakuRepo</title>
<style>{CSS}</style></head><body>
<h1>录播索引</h1>
<div class="sub">DanmakuRepo · 生成于 {datetime.datetime.now():%Y-%m-%d %H:%M}</div>

<div class="stats">
  <span>共 <b>{len(items)}</b> 场</span>
  <span>总计 <b>{human(total)}</b></span>
  <span>主播 <b>{len(streamers)}</b> 位</span>
  {span}
  <span>当前显示 <b id="shown">{len(items)}</b> 场 / <b id="shownSize">{total/1073741824:.1f}</b> GB</span>
</div>

<div class="bar">
  <input type="search" id="q" placeholder="搜主播名或文件名…">
  <select id="who"><option value="">全部主播</option>{opts}</select>
  <input type="date" id="from" title="起始日期">
  <input type="date" id="to" title="结束日期">
</div>

<table>
<thead><tr><th>文件名</th><th>主播</th><th>日期</th><th>大小</th></tr></thead>
<tbody>
{''.join(rows) if rows else '<tr><td colspan="4" class="empty">还没有弹幕版成品</td></tr>'}
</tbody></table>

<div class="hint">
  点文件名在新标签页播放（需要浏览器支持该格式；.ts 可能只能下载）。<br>
  文件路径相对项目根目录，所以放在项目里的页面能直接打开本地文件。
</div>
<script>{JS}</script>
</body></html>
"""


def build(out_path=None, recordings_root=None):
    root = recordings_root or os.path.join(PROJ, '直播回放')
    items = collect(root)
    html = render(items, root)
    out = out_path or os.path.join(PROJ, 'index.html')
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    return out


def main():
    ap = argparse.ArgumentParser(description='生成录播索引页')
    ap.add_argument('--out', default=None, help='输出路径（默认 <项目>/index.html）')
    ap.add_argument('--open', action='store_true', help='生成后打开')
    args = ap.parse_args()

    out = build(args.out)
    print(f'  已生成: {out}')
    try:
        print(f'  共 {os.path.getsize(out)/1024:.0f} KB')
    except OSError:
        pass
    if args.open:
        try:
            os.startfile(out)          # noqa: S606  (Windows only)
        except Exception as e:
            print(f'  打开失败: {e}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
