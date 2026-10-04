"""用真实 global.yml 的 rclone 命令做端到端上传测试（百度网盘）。

会在网盘建一个临时目录，测完自动清理。
"""
import logging
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.WARNING)

from DMR.Config import Config
from DMR.Uploader.subprocess_uploader import SubprocessUploader
from DMR.utils import VideoInfo, replace_keywords

cfg = Config('configs/global.yml')
default = cfg.global_config['upload_args_task_default']['dm_video'][0]
base = cfg.global_config['upload_args']['rclone']

# 合并出任务实际会用的配置（和 Config 里的逻辑一致）
upload_cfg = dict(base)
upload_cfg.update(default)

print('任务实际会执行的上传配置:')
for k, v in upload_cfg.items():
    print(f'    {k}: {v}')
print()

cmd = upload_cfg['command']
print('原始命令模板:')
print('   ', cmd)
print()

# 把目标目录换成临时目录，测完清理
TEST_REMOTE_DIR = 'cd2:百度网盘/__dmr_selftest__'
test_cmd = [TEST_REMOTE_DIR + '/{TASKNAME}' if 'DMR录播' in str(x) else x for x in cmd]
print('本次测试命令（目标换成临时目录）:')
print('   ', test_cmd)
print()

tmpdir = tempfile.mkdtemp(prefix='dmr_cd2_')
local = os.path.join(tmpdir, '测试-带空格 和中文.mp4')
with open(local, 'wb') as f:
    f.write(b'\x00' * (512 * 1024))     # 512KB 假文件

video = VideoInfo(path=local, taskname='自检主播', dtype='dm_video')
print('展开后的真实命令:')
print('   ', [replace_keywords(str(x), video) for x in test_cmd])
print()

up = SubprocessUploader()
status, message = up.call_subprocess(video, command=test_cmd)
print(f'上传结果: status={status}')
print(f'  {message}')
print()

r = subprocess.run(['rclone', 'lsf', TEST_REMOTE_DIR, '-R'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')
print(f'网盘上 {TEST_REMOTE_DIR} 的内容:')
print(r.stdout or '(空)')

ok = status and '自检主播' in (r.stdout or '')
print()
print('清理测试目录...')
subprocess.run(['rclone', 'purge', TEST_REMOTE_DIR],
               capture_output=True, text=True, encoding='utf-8', errors='replace')
print()
print('结果:', '✓ 百度网盘上传链路可用' if ok else '✗ 上传失败')
sys.exit(0 if ok else 1)
