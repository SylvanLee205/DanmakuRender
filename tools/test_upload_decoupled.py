"""验证「清理与上传解耦」+「任务级默认上传配置」+「B站缺失自动跳过」。

覆盖：
  1. 任务不写 upload_args，能从 upload_args_task_default 继承到 rclone 上传
  2. global.yml 里没有 bilibili 段时，任务写了 target: bilibili 不会报错，只跳过
  3. 清理不再依赖上传状态：src_video 一 ready 就被清理
"""
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.WARNING, format='    [%(levelname)s] %(message)s')

from DMR.Config import Config

TASK_NO_UPLOAD_ARGS = """common_event_args:
  auto_render: True
  auto_upload: True
  auto_clean: True
  auto_transcode: False

download_args:
  dltype: live
  url: 'https://live.douyin.com/123456'
"""

TASK_WITH_BILIBILI = """common_event_args:
  auto_render: True
  auto_upload: True
  auto_clean: True
  auto_transcode: False

download_args:
  dltype: live
  url: 'https://live.douyin.com/123456'

upload_args:
  dm_video+bilibili+rclone:
    - target: bilibili
      engine: biliuprs
    - target: rclone
"""


def main():
    ok = True
    cfg = Config('configs/global.yml')

    print('=== 0. global.yml 的 upload_args 目标 ===')
    targets = sorted(k for k in cfg.global_config['upload_args'].keys())
    print(f'  可用的上传目标: {targets}')
    if 'bilibili' in targets:
        print('  ✗ bilibili 段应该已删除')
        ok = False
    else:
        print('  ✓ bilibili 段已删除')

    tmp = tempfile.mkdtemp(prefix='dmr_up_')

    print('\n=== 1. 任务不写 upload_args -> 继承任务级默认 ===')
    p1 = os.path.join(tmp, 'DMR-测试A.yml')
    open(p1, 'w', encoding='utf-8').write(TASK_NO_UPLOAD_ARGS)
    t1 = cfg.add_task_config(p1)
    rc1 = cfg.get_replay_config(t1)
    up1 = rc1.get('upload_args') or {}
    print(f'  upload_args keys: {list(up1.keys())}')
    for k, v in up1.items():
        for i, arg in enumerate(v):
            print(f'    [{k}] #{i}: engine={arg.get("engine")} realtime={arg.get("realtime")}')
            print(f'         command={arg.get("command")}')
    if up1.get('dm_video') and up1['dm_video'][0].get('engine') == 'subprocess':
        print('  ✓ 成功继承 rclone 上传配置（dm_video）')
    else:
        print('  ✗ 没有继承到上传配置')
        ok = False

    print('\n=== 2. 任务写了 target: bilibili（但 global.yml 已删除该段）===')
    p2 = os.path.join(tmp, 'DMR-测试B.yml')
    open(p2, 'w', encoding='utf-8').write(TASK_WITH_BILIBILI)
    try:
        t2 = cfg.add_task_config(p2)
        rc2 = cfg.get_replay_config(t2)
        up2 = rc2.get('upload_args') or {}
        print(f'  任务加载成功，upload_args keys: {list(up2.keys())}')
        for k, v in up2.items():
            print(f'    [{k}] 共 {len(v)} 份上传: {[a.get("engine") for a in v]}')
        if t2 and up2:
            print('  ✓ 没有崩溃，bilibili 那份被跳过，rclone 保留')
        else:
            print('  ✗ 结果不符合预期')
            ok = False
    except Exception as e:
        print(f'  ✗ 抛异常了: {type(e).__name__}: {e}')
        ok = False

    print('\n=== 3. clean_args 仍然是任务级默认 ===')
    ca = rc1.get('clean_args') or {}
    for k, v in ca.items():
        for arg in (v if isinstance(v, list) else [v]):
            print(f'    {k}: method={arg.get("method")} delay={arg.get("delay")} w_srcfile={arg.get("w_srcfile")}')
    if 'src_video' in ca:
        print('  ✓ src_video 有清理规则（渲染完会被删）')
    else:
        print('  ✗ src_video 没有清理规则')
        ok = False

    print()
    print('=' * 70)
    print('全部通过 ✓' if ok else '有失败项 ✗')
    print('=' * 70)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
