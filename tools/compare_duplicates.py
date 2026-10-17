"""比对 (1)/(2) 重名文件与原文件是否为重复内容。

判定维度：
  1. 时长（ffprobe format=duration）
  2. 分辨率
  3. 抽帧 SSIM（3 个时间点）
  4. 文件大小比例

结论：
  - 时长接近 + SSIM 高  -> 重复，可删
  - 时长明显不同         -> 不同内容，保留
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

UP = r'F:\DanmakuRender_AutoUp'
REPLAY = os.path.join(UP, '直播回放')


def run(cmd, timeout=300):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=timeout)
    return r.returncode, (r.stdout or ''), (r.stderr or '')


def probe(p):
    rc, so, se = run(['ffprobe', '-v', 'error', '-show_entries',
                      'format=duration,size', '-show_entries',
                      'stream=width,height,codec_type',
                      '-of', 'json', p])
    if rc != 0:
        return None
    try:
        j = json.loads(so)
        fmt = j.get('format') or {}
        v = next((s for s in (j.get('streams') or [])
                  if s.get('codec_type') == 'video'), {})
        return {'dur': float(fmt.get('duration') or 0),
                'size': int(fmt.get('size') or 0),
                'w': v.get('width'), 'h': v.get('height')}
    except Exception:
        return None


def ssim_at(a, b, t):
    """在时刻 t 抽帧比对，返回 SSIM。"""
    tmp = tempfile.mkdtemp(prefix='ssim_')
    fa = os.path.join(tmp, 'a.png')
    fb = os.path.join(tmp, 'b.png')
    try:
        for src, out in ((a, fa), (b, fb)):
            run(['ffmpeg', '-y', '-v', 'error', '-ss', str(t), '-i', src,
                 '-frames:v', '1', '-vf', 'scale=320:-1', out])
        if not (os.path.exists(fa) and os.path.exists(fb)):
            return None
        rc, so, se = run(['ffmpeg', '-v', 'info', '-i', fa, '-i', fb,
                          '-lavfi', 'ssim', '-f', 'null', '-'])
        m = re.search(r'SSIM.*?All:([\d.]+)', se or '')
        return float(m.group(1)) if m else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    apply = '--apply' in sys.argv
    print('=' * 78)
    print(f'(1)/(2) 重名文件比对 {"（执行删除）" if apply else "（仅报告）"}')
    print('=' * 78)

    dups = []
    for root, dirs, files in os.walk(REPLAY):
        for f in files:
            if re.search(r'\(\d+\)', f) and f.endswith(('.mp4', '.mkv')):
                base = re.sub(r'\(\d+\)', '', f)
                # 处理"（弹幕版）(1).mp4" -> "（弹幕版）.mp4"
                bp = os.path.join(root, base)
                if os.path.exists(bp):
                    dups.append((os.path.join(root, f), bp))

    if not dups:
        print('  没有找到"有原文件存在"的重名文件。')
        return 0

    print(f'  找到 {len(dups)} 对：\n')
    verdicts = []
    for dup, base in sorted(dups, key=lambda x: -os.path.getsize(x[0])):
        n_dup, n_base = os.path.basename(dup), os.path.basename(base)
        pi, pb = probe(dup), probe(base)
        print(f'  ── {n_dup}')
        if not (pi and pb):
            print('      ⚠ 无法探测，跳过')
            continue
        print(f'      重名: {pi["size"]/1024/1024:>8.2f} MB  '
              f'{pi["dur"]:>8.1f}s  {pi["w"]}x{pi["h"]}')
        print(f'      原文件: {pb["size"]/1024/1024:>8.2f} MB  '
              f'{pb["dur"]:>8.1f}s  {pb["w"]}x{pb["h"]}')
        # 抽 3 帧比对
        ss = []
        for frac in (0.25, 0.5, 0.75):
            t = min(pi['dur'], pb['dur']) * frac
            if t <= 0:
                continue
            v = ssim_at(dup, base, t)
            if v is not None:
                ss.append(v)
        avg = sum(ss) / len(ss) if ss else None
        dur_ratio = (min(pi['dur'], pb['dur']) / max(pi['dur'], pb['dur'])
                     if max(pi['dur'], pb['dur']) > 0 else 0)
        print(f'      SSIM: {[round(x,3) for x in ss]}  平均={avg and round(avg,3)}')
        print(f'      时长比: {dur_ratio:.3f}')
        # 判定
        if avg is not None and avg > 0.9 and dur_ratio > 0.95:
            v = '重复（可删）'
        elif dur_ratio < 0.5:
            v = '不同内容（保留）'
        elif avg is not None and avg < 0.5:
            v = '不同内容（保留）'
        else:
            v = '不确定（保守：保留）'
        print(f'      -> {v}')
        print()
        verdicts.append((dup, base, v, pi, pb))

    print('=' * 78)
    print('汇总')
    print('=' * 78)
    safe = [x for x in verdicts if x[2] == '重复（可删）']
    keep = [x for x in verdicts if x[2] != '重复（可删）']
    print(f'  确认重复（可删）: {len(safe)} 个，共 '
          f'{sum(x[3]["size"] for x in safe)/1024/1024:.1f} MB')
    for dup, base, v, pi, pb in safe:
        print(f'      {os.path.basename(dup)}')
    print(f'  需保留: {len(keep)} 个')
    for dup, base, v, pi, pb in keep:
        print(f'      [{v}] {os.path.basename(dup)}')

    if not apply:
        print('\n  这是报告模式。加 --apply 删除"确认重复"的文件。')
        return 0

    if not safe:
        print('\n  没有可安全删除的文件。')
        return 0

    print(f'\n  删除 {len(safe)} 个确认重复的文件...')
    n, freed = 0, 0
    for dup, base, v, pi, pb in safe:
        try:
            if not os.path.exists(base):
                print(f'    跳过（原文件不见了）: {os.path.basename(dup)}')
                continue
            sz = os.path.getsize(dup)
            os.remove(dup)
            n += 1
            freed += sz
            print(f'    ✅ {os.path.basename(dup)}')
        except Exception as e:
            print(f'    ❌ {os.path.basename(dup)}: {e}')
    print(f'\n  已删 {n} 个，释放 {freed/1024/1024:.1f} MB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
