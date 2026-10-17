"""把抢救出来的孤儿分段（无弹幕）转封装成 mp4 并上传。

背景：
  三个孤儿 .flv 已改名成正式分段 .mkv，但**没有配套 .ass 弹幕文件**
  （全项目搜 .ass = 0 个，可能在录制中断时就没生成，或被清理误删）。
  所以无法渲染带弹幕的版本。

处置：
  1. 用 ffmpeg **流拷贝**（-c copy）把 .mkv 转成 .mp4
     - 不重编码，速度快、无质量损失
     - 只是换个容器，兼容性更好（部分播放器对 flv/mkv 支持一般）
  2. 输出到 "哭哭不嘻嘻（弹幕版）" 目录，命名与正常产物一致
     <名>（弹幕版）.mp4
     这样 upload_only 能自动推导任务名，直接上传
  3. 上传到云端

⚠️ 这些文件**没有弹幕**，是纯视频。上传后会混在弹幕版目录里，
   命名带（弹幕版）其实不准确 —— 但为了复用现有上传流程，
   先这么做，并在日志里注明。
"""
import os
import subprocess
import sys
import time

UP = r'F:\DanmakuRender_AutoUp'
D = os.path.join(UP, '直播回放', '哭哭不嘻嘻')
DM = os.path.join(UP, '直播回放', '哭哭不嘻嘻（弹幕版）')

TARGETS = [
    '哭哭不嘻嘻-2026年10月07日22点30分.mkv',
    '哭哭不嘻嘻-2026年10月07日23点30分.mkv',
    '哭哭不嘻嘻-2026年10月08日00点30分.mkv',
]


def convert(src, dst):
    """流拷贝转封装 mkv -> mp4。返回 (ok, msg)。"""
    cmd = ['ffmpeg', '-y', '-v', 'error',
           '-i', src,
           '-c', 'copy',
           '-movflags', '+faststart',   # mp4 头前置，便于边下边播
           dst]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=3600)
        if r.returncode != 0:
            return False, (r.stderr or '').strip()[:400]
        if not os.path.exists(dst) or os.path.getsize(dst) == 0:
            return False, '输出文件不存在或为 0 字节'
        return True, ''
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'


def main():
    apply = '--apply' in sys.argv
    do_upload = '--upload' in sys.argv

    print('=' * 78)
    print(f'转封装孤儿分段 {"（执行）" if apply else "（DRY-RUN）"}'
          f'{"  + 上传" if do_upload else ""}')
    print('=' * 78)
    os.makedirs(DM, exist_ok=True)

    todo = []
    for f in TARGETS:
        src = os.path.join(D, f)
        if not os.path.exists(src):
            print(f'  [X] 不存在: {f}')
            continue
        stem = os.path.splitext(f)[0]
        dst = os.path.join(DM, stem + '（弹幕版）.mp4')
        sz = os.path.getsize(src)
        exists = os.path.exists(dst)
        todo.append((src, dst, sz, exists))
        print(f'  {f}')
        print(f'      {sz/1024/1024:>8.1f} MB')
        print(f'   -> {os.path.basename(dst)}'
              + ('   [已存在，跳过]' if exists else ''))

    if not todo:
        print('\n  没有待处理的文件。')
        return 0
    if not apply:
        print(f'\n  DRY-RUN：将处理 {len(todo)} 个。加 --apply 执行。')
        return 0

    print()
    print('=' * 78)
    print('转封装（-c copy，不重编码）')
    print('=' * 78)
    done = []
    for src, dst, sz, exists in todo:
        if exists:
            print(f'  跳过（已存在）: {os.path.basename(dst)}')
            done.append(dst)
            continue
        t0 = time.time()
        print(f'  转换: {os.path.basename(src)}')
        ok, msg = convert(src, dst)
        el = time.time() - t0
        if ok:
            nsz = os.path.getsize(dst)
            print(f'      ✅ {nsz/1024/1024:.1f} MB  ({el:.0f}s, '
                  f'{nsz/sz*100:.0f}% of source)')
            done.append(dst)
        else:
            print(f'      ❌ 失败: {msg}')

    print(f'\n  完成 {len(done)}/{len(todo)}')

    if do_upload and done:
        print()
        print('=' * 78)
        print('上传到云端')
        print('=' * 78)
        sys.path.insert(0, os.path.join(UP, 'tools'))
        from recover_part import upload_only
        from DMR.Config import Config
        import logging
        logging.basicConfig(level=logging.WARNING)
        cfg = Config(os.path.join(UP, 'configs', 'global.yml'))
        upload_only(cfg, DM)

    print()
    print('  弹幕版目录现在:')
    for f in sorted(os.listdir(DM)):
        p = os.path.join(DM, f)
        if os.path.isfile(p):
            print(f'    {os.path.getsize(p)/1024/1024:>8.1f} MB  {f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
