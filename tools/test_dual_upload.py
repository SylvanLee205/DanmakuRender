"""验证『同时上传 B站 + 网盘』的配置能否正确展开。

用法：python tools/test_dual_upload.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
from DMR.Config import Config
from DMR.utils import merge_dict

TEST_TASK = """common_event_args:
  auto_render: True
  auto_upload: True
  auto_clean: False
  auto_transcode: False

download_args:
  dltype: live
  url: 'https://live.douyin.com/123456'

upload_args:
  dm_video+bilibili+rclone:
    - target: bilibili
      engine: biliuprs
      account: bilibili
    - target: rclone
      engine: subprocess
      command: ['rclone', 'copy', '{PATH}', '123pan:DMR录播/{TASKNAME}', '--retries', '5']
"""


def main():
    cfg = Config('configs/global.yml')

    # 写一个临时任务配置，走一遍真实的 add_task_config 流程
    tmpdir = tempfile.mkdtemp(prefix='dmr_dual_')
    path = os.path.join(tmpdir, 'DMR-测试主播.yml')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(TEST_TASK)

    taskname = cfg.add_task_config(path)
    print(f'任务名: {taskname}')
    if not taskname:
        print('!! 任务配置加载失败')
        return 1

    rc = cfg.get_replay_config(taskname)
    up = rc['upload_args']
    print(f'\nupload_args 顶层 key（= 视频类型匹配表达式）: {list(up.keys())}')

    for file_types, args_list in up.items():
        print(f'\n[{file_types}] 子类型: {[t for t in file_types.split("+")]}')
        for i, arg in enumerate(args_list):
            print(f'  第{i}份上传 -> engine={arg.get("engine")}, account={arg.get("account")}, '
                  f'realtime={arg.get("realtime")}, retry={arg.get("retry")}')
            if arg.get('command'):
                print(f'      command={arg["command"]}')

    # 核心断言：一个 key 展开出两份上传
    key = 'dm_video+bilibili+rclone'
    assert key in up, f'缺少 {key}'
    assert len(up[key]) == 2, f'{key} 应该展开成 2 份上传，实际 {len(up[key])}'
    assert 'dm_video' in key.split('+'), '必须包含视频类型 dm_video'
    print('\n✓ 一个 key 成功展开为 2 份并行上传（B站 + 网盘）')

    # 验证 B站那份继承了 global.yml 的 bilibili 默认值
    bili = up[key][0]
    assert bili.get('tid') == 65, 'B站那份应该继承 global.yml 里 bilibili 的 tid'
    assert bili.get('title'), 'B站那份应该继承 title 模板'
    print('✓ B站那份已继承 global.yml 的 bilibili 默认参数（title/tid/desc 等）')

    rclone = up[key][1]
    assert rclone.get('engine') == 'subprocess'
    assert rclone.get('realtime') is False, 'rclone 应该继承 realtime: False（整场合并后上传）'
    print('✓ 网盘那份已继承 global.yml 的 rclone 默认参数（realtime=False）')

    # 再验证一次「只写 engine 不写 target」的简写形式也能自动识别
    print('\n--- 简写形式测试（不写 target，只写 engine）---')
    short = """common_event_args:
  auto_render: True
  auto_upload: True
  auto_clean: False
  auto_transcode: False

download_args:
  dltype: live
  url: 'https://live.douyin.com/123456'

upload_args:
  dm_video:
    - engine: subprocess
      command: ['rclone', 'copy', '{PATH}', '123pan:test/{TASKNAME}']
"""
    path2 = os.path.join(tmpdir, 'DMR-测试主播2.yml')
    with open(path2, 'w', encoding='utf-8') as f:
        f.write(short)
    tn2 = cfg.add_task_config(path2)
    rc2 = cfg.get_replay_config(tn2)
    arg2 = rc2['upload_args']['dm_video'][0]
    print(f'  engine={arg2.get("engine")} -> 自动识别为 rclone 目标: realtime={arg2.get("realtime")}')
    assert arg2.get('realtime') is False, '简写形式没能正确识别为 rclone 目标'
    assert arg2.get('retry') == 3, '应该继承 rclone 的 retry'
    print('✓ 简写形式（只写 engine: subprocess）也能正确继承 rclone 默认参数')
    os.remove(path2)

    os.remove(path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
