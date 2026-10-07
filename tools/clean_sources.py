"""安全的源文件清理工具（带完整防护）。

⚠️⚠️ 为什么需要这个工具（2026-10-07 事故）：
    为了清理 7 个滞留的 .mkv，我临时写了个一次性脚本，结果它：
      1. **没有过滤 `[正在录制]` 前缀** —— 删掉了正在录制的 .ass
      2. **只对 .mkv 做了"弹幕版存在"检查**，.ass 直接删
    所幸删的是 0 字节文件，DMR 继续写入，没有实际损失。
    但这是个真实的教训：**一次性脚本绕过了正式流程的保护。**

    本工具把所有防护固化下来，以后清理一律用它。

防护清单（每一条都对应一次真实教训）：
    1. 跳过 `[正在录制]` 前缀的文件        <- 2026-10-07 事故
    2. 跳过 `.part` / `.tmp` / `.converting` 等中间文件
    3. 只处理超过 N 分钟没被修改的文件（默认 30 分钟）  <- 防正在写入
    4. 必须有对应的渲染产物（`（弹幕版）.mp4`）才允许删   <- 防删掉还没渲染的
    5. 默认 dry-run，加 --apply 才真删
    6. 删除前打印清单让用户确认

用法：
    python tools\\clean_sources.py            # 只报告（dry-run）
    python tools\\clean_sources.py --apply    # 真正删除
    python tools\\clean_sources.py --apply --min-age 120   # 只清 2 小时以上的
"""
import argparse
import os
import re
import sys
import time

ROOT = r'F:\DanmakuRender_AutoUp'
REPLAY = os.path.join(ROOT, '直播回放')

# 这些前缀/后缀表示"正在使用中"，绝对不能碰
ACTIVE_MARKERS = ('[正在录制]', '[正在渲染]', '[正在上传]')
SKIP_SUFFIX = ('.part', '.tmp', '.converting', '.temp', '.ytdl', '.download')
CLEANABLE_SUFFIX = ('.mkv', '.ass', '.flv', '.ts')

# 渲染产物目录的后缀
RENDERED_DIR_SUFFIX = '（弹幕版）'

# CD2 服务版缓存（云端真实内容）
CD2_CACHE = r'C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2\dir_cache.sqlite'


def cloud_files(task):
    """从 CD2 缓存读某任务的云端文件集合。查不到返回 None（表示未知）。

    ⚠️ 为什么要查云端：
        本地弹幕版可能已被清理（正常行为），这时源文件其实可以安全删掉，
        因为内容已经在云端了。只按"本地渲染产物存在"判断会过于保守，
        导致源文件永久滞留（实测 12 个文件 1.11 GB 因此没被清理）。
    """
    import shutil
    import sqlite3
    if not os.path.exists(CD2_CACHE):
        return None
    tmp = os.path.join(os.environ.get('TEMP', '.'), 'clean_sources_cache')
    try:
        os.makedirs(tmp, exist_ok=True)
        for suf in ('', '-wal', '-shm'):
            src = CD2_CACHE + suf
            if os.path.exists(src):
                try:
                    shutil.copy2(src, os.path.join(tmp, 'dir_cache.sqlite' + suf))
                except Exception:
                    pass
        q = os.path.join(tmp, 'dir_cache.sqlite')
        con = sqlite3.connect(f'file:{q}?mode=ro', uri=True)
        cur = con.cursor()
        cur.execute("SELECT id FROM cached_item WHERE path LIKE ?",
                    (f'%/DMR录播/{task}',))
        out = set()
        for (did,) in cur.fetchall():
            cur.execute('SELECT name FROM files WHERE parent_id=?', (did,))
            out |= {r[0] for r in cur.fetchall()}
        con.close()
        return out
    except Exception:
        return None


def find_candidates(min_age_minutes=30):
    """找出可以安全清理的文件，返回 [(路径, 大小, 原因) ...] 和跳过列表。"""
    ok, skipped = [], []
    if not os.path.isdir(REPLAY):
        return ok, skipped

    now = time.time()
    for task_dir in sorted(os.listdir(REPLAY)):
        sub = os.path.join(REPLAY, task_dir)
        if not os.path.isdir(sub):
            continue
        if task_dir.endswith(RENDERED_DIR_SUFFIX):
            continue        # 弹幕版目录是产物，不动

        rendered_dir = os.path.join(REPLAY, task_dir + RENDERED_DIR_SUFFIX)
        rendered_files = set()
        if os.path.isdir(rendered_dir):
            rendered_files = {f for f in os.listdir(rendered_dir)
                              if f.endswith('.mp4')}

        # 云端文件集合（用于判断"内容是否已在云端"），查不到为 None
        cloud_set = cloud_files(task_dir)

        for f in sorted(os.listdir(sub)):
            p = os.path.join(sub, f)
            if not os.path.isfile(p):
                continue

            # 防护 1/2：名字里带"正在..."标记，或扩展名是中间格式
            if any(m in f for m in ACTIVE_MARKERS):
                skipped.append((p, '文件名含"正在录制/渲染/上传"标记'))
                continue
            if f.lower().endswith(SKIP_SUFFIX):
                skipped.append((p, '中间文件（.part/.tmp 等）'))
                continue
            if not f.lower().endswith(CLEANABLE_SUFFIX):
                continue

            # 防护 3：太新的不动（可能还在写）
            try:
                age_min = (now - os.path.getmtime(p)) / 60
            except Exception:
                continue
            if age_min < min_age_minutes:
                skipped.append((p, f'刚修改过（{age_min:.0f} 分钟前 < '
                                   f'{min_age_minutes} 分钟）'))
                continue

            # 防护 4：必须有"内容已在别处"的证据才能删，二选一：
            #   a) 本地有渲染产物（（弹幕版）.mp4）
            #   b) 云端已有该分段（内容已备份，重渲染没意义）
            stem = os.path.splitext(f)[0]
            expected = stem + RENDERED_DIR_SUFFIX + '.mp4'
            if expected in rendered_files:
                ok.append((p, os.path.getsize(p), age_min, '本地已渲染'))
                continue
            # 云端校验（按文件名前缀匹配，因为云端名可能经过 emoji 清洗）
            if cloud_set is not None:
                # 云端文件名形如 "<源名>（弹幕版）.mp4"
                cloud_hit = any(
                    n.startswith(stem[:max(1, len(stem) - 6)])
                    for n in cloud_set
                )
                if cloud_hit:
                    ok.append((p, os.path.getsize(p), age_min, '云端已有'))
                    continue
                skipped.append((p, '本地无渲染产物，云端也没有'))
            else:
                skipped.append((p, '本地无渲染产物（云端查询不可用）'))
            continue

    return ok, skipped


def main():
    ap = argparse.ArgumentParser(description='安全清理源文件/弹幕文件')
    ap.add_argument('--apply', action='store_true',
                    help='真正删除（默认只报告，不删）')
    ap.add_argument('--min-age', type=int, default=30, metavar='MIN',
                    help='只清理最后修改早于 MIN 分钟的文件（默认 30）')
    ap.add_argument('--show-skipped', action='store_true',
                    help='也列出被跳过保护的文件')
    opt = ap.parse_args()

    print('=' * 78)
    print(f'源文件清理（min_age={opt.min_age} 分钟，'
          f'{"实际删除" if opt.apply else "DRY-RUN 仅报告"}）')
    print('=' * 78)

    ok, skipped = find_candidates(min_age_minutes=opt.min_age)

    if not ok:
        print('\n  没有可清理的文件。')
    else:
        total = sum(sz for _, sz, _, _ in ok)
        print(f'\n  可安全清理 {len(ok)} 个文件，共 {total/1024/1024/1024:.2f} GB：')
        for p, sz, age, why in sorted(ok, key=lambda x: -x[1]):
            rel = os.path.relpath(p, REPLAY)
            print(f'    {sz/1024/1024:>9.1f} MB  {age:>7.0f} 分钟前  '
                  f'[{why}]  {rel}')

    if opt.show_skipped and skipped:
        print(f'\n  被保护跳过的 {len(skipped)} 个：')
        for p, reason in skipped[:40]:
            rel = os.path.relpath(p, REPLAY)
            print(f'    [跳过] {rel}  <- {reason}')
        if len(skipped) > 40:
            print(f'    ... 还有 {len(skipped)-40} 个')

    if ok and not opt.apply:
        print('\n  这是 DRY-RUN。确认无误后加 --apply 真正删除。')
        return 0

    if ok and opt.apply:
        print('\n  开始删除...')
        n, freed, failed = 0, 0, 0
        for p, sz, _, _ in ok:
            # 删除前再确认一次：文件还在、且仍然"老"
            if not os.path.exists(p):
                continue
            try:
                if (time.time() - os.path.getmtime(p)) / 60 < opt.min_age:
                    print(f'    跳过（刚刚又被修改了）: {os.path.basename(p)}')
                    continue
                os.remove(p)
                n += 1
                freed += sz
            except Exception as e:
                failed += 1
                print(f'    删除失败 {os.path.basename(p)}: {e}')
        print(f'\n  已删除 {n} 个，释放 {freed/1024/1024/1024:.2f} GB'
              + (f'，失败 {failed} 个' if failed else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
