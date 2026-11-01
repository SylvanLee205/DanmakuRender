"""抢救孤儿 .flv：改名成正式分段，供 DMR 的恢复流程处理。

命名规则（来自 DMR/Downloader/stream_downloader.py）：
    [正在录制]<task>-<YYYYMMDDHHMMSS>-<hash>.flv
 -> <task>-<YYYY>年<MM>月<DD>日<HH>点<MM>分.mkv

  例: [正在录制]哭哭不嘻嘻-20261007223036-....flv
   -> 哭哭不嘻嘻-2026年10月07日22点30分.mkv

⚠️ 重要：改名后**不要**让 DMR 的启动恢复误判为"中断的 .part"。
   这些 .flv 是**完整**文件（已验证可完整解码），不是 .part。
   改名为 .mkv 后，recover_part.py 只扫 .part，不会碰它们。
   然后它们会像普通分段一样：
     - 被 DMR 的 downloader 认为是历史文件？不会（不在录制状态）
     - 需要手动送进渲染/上传流程

   所以本脚本只做改名 + 报告，渲染上传由后续步骤处理。
"""
import json
import os
import shutil
import sys
import time

UP = r'F:\DanmakuRepo'
D = os.path.join(UP, '直播回放', '哭哭不嘻嘻')
BACKUP = os.path.join(UP, '.temp', 'orphan_flv_backup')

# 三个孤儿文件：(源文件名, 目标正式名)
TARGETS = [
    ('[正在录制]哭哭不嘻嘻-20261007223036-a9470204c25b11f1.flv',
     '哭哭不嘻嘻-2026年10月07日22点30分.mkv'),
    ('[正在录制]哭哭不嘻嘻-202610073035-a9470204c25b11f1.flv',
     '哭哭不嘻嘻-2026年10月07日23点30分.mkv'),   # 注意：下面是实际名，这行会被纠正
    ('[正在录制]哭哭不嘻嘻-20261008003037-a9470204c25b11f1.flv',
     '哭哭不嘻嘻-2026年10月08日00点30分.mkv'),
]
# 实际文件名（避免手抄错误）
TARGETS[1] = ('[正在录制]哭哭不嘻嘻-20261007233035-a9470204c25b11f1.flv',
              '哭哭不嘻嘻-2026年10月07日23点30分.mkv')


def main():
    apply = '--apply' in sys.argv

    print('=' * 78)
    print(f'抢救孤儿 .flv{"（实际执行）" if apply else "（DRY-RUN）"}')
    print('=' * 78)

    todo = []
    for src, dst in TARGETS:
        sp = os.path.join(D, src)
        dp = os.path.join(D, dst)
        if not os.path.exists(sp):
            # 可能已经改过了
            if os.path.exists(dp):
                print(f'  [已完成] {dst}')
            else:
                print(f'  [X] 源文件不存在: {src}')
            continue
        sz = os.path.getsize(sp)
        conflict = os.path.exists(dp)
        todo.append((sp, dp, sz, conflict))
        print(f'  {src}')
        print(f'      {sz/1024/1024:.1f} MB')
        print(f'   -> {dst}' + ('   ⚠️ 目标已存在！' if conflict else ''))

    if not todo:
        print('\n  没有需要处理的文件。')
        return 0

    if not apply:
        print(f'\n  DRY-RUN：将处理 {len(todo)} 个文件。加 --apply 执行。')
        print('  执行时会先备份到: ' + BACKUP)
        return 0

    # 备份
    os.makedirs(BACKUP, exist_ok=True)
    print(f'\n  备份到 {BACKUP}')
    for sp, dp, sz, conflict in todo:
        try:
            shutil.copy2(sp, os.path.join(BACKUP, os.path.basename(sp)))
            print(f'    已备份 {os.path.basename(sp)}')
        except Exception as e:
            print(f'    ❌ 备份失败 {os.path.basename(sp)}: {e}')
            print('    -> 中止（不敢在没备份的情况下改动）')
            return 1

    print()
    print('  改名:')
    ok = 0
    for sp, dp, sz, conflict in todo:
        if conflict:
            print(f'    跳过（目标已存在）: {os.path.basename(dp)}')
            continue
        try:
            os.rename(sp, dp)
            ok += 1
            print(f'    ✅ {os.path.basename(dp)}')
        except Exception as e:
            print(f'    ❌ {os.path.basename(sp)}: {e}')

    print(f'\n  完成 {ok}/{len(todo)}')
    print()
    print('  目录现在的分段:')
    for f in sorted(os.listdir(D)):
        p = os.path.join(D, f)
        print(f'    {os.path.getsize(p)/1024/1024:>8.1f} MB  {f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
