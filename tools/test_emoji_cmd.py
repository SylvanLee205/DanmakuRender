"""测试 _sanitize_rclone_copy 的命令改写（不真的上传）。"""
import os
import sys

sys.path.insert(0, r'F:\DanmakuRender_Mod')
from DMR.Uploader.subprocess_uploader import SubprocessUploader
from DMR.utils import VideoInfo, StreamerInfo

up = SubprocessUploader()
up.logger.setLevel(10)   # DEBUG

CMD = ['rclone', 'copy', '{PATH}', 'cd2:百度网盘/DMR录播/{TASKNAME}', '--retries', '5']

CASES = [
    ('emoji 文件名', '相扑猫💦-2026年10月01日13点13分（弹幕版）.mp4', '相扑猫'),
    ('cake emoji', '掉了颗兔牙（9.13🎂-2026年09月08日23点48分（弹幕版）.mp4', '掉了颗兔牙'),
    ('普通中文名', '苏苏没烦恼-2026年10月04日00点24分（弹幕版）.mp4', '苏苏没烦恼'),
    ('纯英文', 'test.mp4', 'test'),
]

print('=' * 78)
print('rclone 命令改写测试（不实际上传）')
print('=' * 78)
for label, fname, task in CASES:
    vi = VideoInfo(path='F:/fake/' + fname, taskname=task,
                   streamer=StreamerInfo(name=task))
    # 复刻 call_subprocess 的前两步
    from DMR.utils import replace_keywords
    cmds = [replace_keywords(str(x), vi) for x in CMD]
    orig = list(cmds)
    new = up._sanitize_rclone_copy(cmds, vi)

    print(f'\n--- {label} ---')
    print(f'  原始: {orig[:4]}')
    print(f'  改写: {new[:4]}')
    if new[1] == 'copyto':
        print(f'  → 子命令 {orig[1]} 改为 copyto，远程名: {os.path.basename(new[3])}')
        assert not any(ord(c) > 0xFFFF for c in new[3]), '改写后远程名仍含非 BMP 字符!'
        # 参数尾部要保留
        assert new[4:] == orig[4:], '尾部参数丢了!'
    else:
        print('  → 未改写（文件名本来就干净）')
        assert orig == new, '干净文件名不该被改'
    print('  ✓')

print()
print('=' * 78)
print('全部通过 ✓')
print('=' * 78)
