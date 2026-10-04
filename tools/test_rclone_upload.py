"""真实 rclone 上传冒烟测试：造一个小文件，用上传器传上网盘，验证后清理。

需要 rclone 已配置好 123pan remote。
用法：python tools/test_rclone_upload.py
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from DMR.Uploader.subprocess_uploader import SubprocessUploader
from DMR.utils import VideoInfo, replace_keywords

REMOTE_DIR = '123pan:__dmr_selftest__'


def main():
    tmpdir = tempfile.mkdtemp(prefix='dmr_rclone_')
    local = os.path.join(tmpdir, '测试文件-带空格 和中文.txt')
    with open(local, 'w', encoding='utf-8') as f:
        f.write('DanmakuRender 魔改版 rclone 上传自检\n' * 10)

    file = VideoInfo(path=local, taskname='自检', dtype='dm_video')
    cmd = ['rclone', 'copy', '{PATH}', REMOTE_DIR + '/{TASKNAME}', '--retries', '5']
    expanded = [replace_keywords(str(x), file) for x in cmd]
    print('展开后的命令:')
    print(' ', expanded)

    up = SubprocessUploader()
    status, message = up.call_subprocess(file, command=cmd)
    print(f'\n上传 status = {status}')
    print(f'message = {message}')

    # 注意：必须显式指定 utf-8，Windows 上默认用 GBK 解码中文文件名会炸
    listed = subprocess.run(
        ['rclone', 'lsf', REMOTE_DIR, '-R'],
        capture_output=True, text=True, encoding='utf-8', errors='replace'
    ).stdout.strip()
    print(f'\n网盘上 {REMOTE_DIR} 的内容:\n{listed}')

    ok = status and '自检' in listed
    print('\n清理测试目录...')
    subprocess.run(['rclone', 'purge', REMOTE_DIR], capture_output=True,
                   text=True, encoding='utf-8', errors='replace')

    # 再测一次失败路径：命令不存在
    print('\n--- 失败路径测试 ---')
    sts2, msg2 = up.call_subprocess(file, command=['rclone', 'definitely-not-a-command'])
    print(f'status={sts2}  message={msg2[:200]}')

    print()
    print('结果：' + ('✓ rclone 上传链路可用' if ok else '✗ 上传链路有问题'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
