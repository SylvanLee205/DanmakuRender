"""测试 main.py 启动时的 .part 自动恢复钩子。

做法：造一个假的 .part 文件（用真实视频切片），把 mtime 改成 2 小时前，
然后调用 main._startup_recover(wait=True)，看它是否自动恢复+渲染。
"""
import os
import shutil
import subprocess
import sys
import time

UP = r'F:\DanmakuRender_AutoUp'   # 用生产环境测试（有真实直播回放目录和任务配置）
sys.path.insert(0, UP)
os.chdir(UP)

# 准备一个真实的视频片段当"中断的 part"
SRC = r'F:\DanmakuRender_AutoUp\直播回放\掉了颗兔牙\掉了颗兔牙-2026年10月05日02点33分.mkv'
if not os.path.exists(SRC):
    SRC = r'F:\DanmakuRender_AutoUp\直播回放\哭哭不嘻嘻\哭哭不嘻嘻-2026年10月04日00点24分.mkv'
if not os.path.exists(SRC):
    print('找不到测试用源视频')
    sys.exit(1)

TEST_DIR = r'F:\DanmakuRender_AutoUp\直播回放\掉了颗兔牙'
TEST_PART = os.path.join(TEST_DIR, '[正在录制]掉了颗兔牙-20261005050000-testhook.flv.part')
print(f'造测试 .part: {TEST_PART}')
shutil.copy2(SRC, TEST_PART)
# 把 mtime 调成 2 小时前，绕过 min_age 保护
old = time.time() - 7200
os.utime(TEST_PART, (old, old))
print(f'  mtime 已设为 2 小时前, size={os.path.getsize(TEST_PART)/1024/1024:.1f}MB')

# 造一个配套弹幕
DM = os.path.join(TEST_DIR, '[正在录制]掉了颗兔牙-20261005-050000-Part001.ass')
if not os.path.exists(DM):
    with open(DM, 'w', encoding='utf-8') as f:
        f.write("""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: DMR,微软雅黑,65,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:06.00,DMR,,0,0,0,,这是自动恢复测试弹幕
""")
print(f'造测试弹幕: {os.path.basename(DM)}')

# 调用 main.py 的钩子
print()
print('=' * 74)
print('调用 main._startup_recover(wait=True)')
print('=' * 74)
import logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s][%(name)s] %(message)s')
logger = logging.getLogger('TEST')
logger.setLevel(logging.INFO)

import main as dmr_main
from DMR.Config import Config

cfg = Config('configs/global.yml')
dmr_main._startup_recover(cfg, logger, enabled=True, wait=True, min_age_minutes=10)

print()
print('=' * 74)
print('结果检查')
print('=' * 74)
# .part 应该没了
left = [p for p in os.listdir(TEST_DIR) if p.endswith('.part')]
print(f'  .part 是否残留: {left if left else "无 ✓"}')
# 恢复出的视频
recovered = [p for p in os.listdir(TEST_DIR) if p.startswith('掉了颗兔牙-2026年10月05日05点00分')]
print(f'  恢复出的视频: {recovered}')
# 渲染出的弹幕版
outdir = os.path.join(TEST_DIR + '（弹幕版）')
rendered = [p for p in os.listdir(outdir) if '05点00分' in p] if os.path.isdir(outdir) else []
print(f'  渲染出的弹幕版: {rendered}')

# 清理测试文件
print()
print('清理测试产生的文件...')
for f in recovered:
    p = os.path.join(TEST_DIR, f)
    os.remove(p)
    print(f'  删除 {f}')
for f in rendered:
    p = os.path.join(outdir, f)
    os.remove(p)
    print(f'  删除 {f}')
# 恢复时会把弹幕改名，一并清掉
for f in os.listdir(TEST_DIR):
    if '05点00分' in f or '050000' in f:
        os.remove(os.path.join(TEST_DIR, f))
        print(f'  删除 {f}')

print()
print('测试完成')
