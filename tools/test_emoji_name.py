"""测试 emoji 文件名清洗。"""
import sys

sys.path.insert(0, r'F:\DanmakuRender_Mod')
from DMR.Uploader.subprocess_uploader import safe_remote_name, has_bad_remote_chars

CASES = [
    '相扑猫💦-2026年10月01日13点13分（弹幕版）.mp4',
    '掉了颗兔牙（9.13🎂-2026年09月08日23点48分（弹幕版）.mp4',
    'test💦.txt',
    'testcake🎂.txt',
    '🇨🇳国旗-2026年01月01日.mp4',
    '❤️心形-测试.mp4',
    '普通中文名-2026年10月05日（弹幕版）.mp4',
    '🎂.mp4',
    'abc.mp4',
    'no_ext_💦',
]

print('=' * 78)
print('emoji 文件名清洗测试')
print('=' * 78)
for c in CASES:
    bad = has_bad_remote_chars(c)
    s = safe_remote_name(c)
    tag = '脏' if bad else '净'
    print(f'  [{tag}] {c}')
    print(f'        -> {s}')
    if bad:
        assert not has_bad_remote_chars(s), f'清洗后仍然脏: {s}'
        assert s.strip(), '清洗后为空'

print()
print('  所有脏名字清洗后都干净 ✓')
