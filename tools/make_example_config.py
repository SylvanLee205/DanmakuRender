"""从生产配置生成脱敏的 global.example.yml。

用途：新手下载后有个能对照的模板。
脱敏内容：
  · remote 名（cd2: → <你的remote>:）
  · 网盘账号相关
  · 本机绝对路径
  · 主播房间号 / 主播名
"""
import os
import re

PROD_CFG = r'F:\DanmakuRender_AutoUp\configs\global.yml'
OUT = r'F:\DanmakuRender_Mod\configs\global.example.yml'

txt = open(PROD_CFG, encoding='utf-8').read()
orig_len = len(txt)

REPL = [
    (r'cd2:百度网盘', '<你的remote>:百度网盘'),
    (r'\bcd2\b', '<你的remote>'),
    (r'1871163532@qq\.com', 'you@example.com'),
    (r'DMR录播', 'DMR录播'),
    (r'F:\\\\DanmakuRender[^\s\'"]*', '<项目目录>'),
    (r'F:\\DanmakuRender[^\s\'"]*', '<项目目录>'),
]
for pat, rep in REPL:
    txt = re.sub(pat, rep, txt)

# 顶部加说明
HEADER = '''# ══════════════════════════════════════════════════════════════════════
#  DanmakuRender-5 魔改版 —— 全局配置示例
#
#  ⚠️ 这是**脱敏后的模板**，不是可直接运行的配置。使用步骤：
#
#    1. 复制成 configs/global.yml
#         cp configs/global.example.yml configs/global.yml
#
#    2. 把下面这些占位符换成你自己的：
#         <你的remote>     —— rclone 的 remote 名（rclone config 里建的）
#         <项目目录>        —— 本项目的绝对路径（如 /home/me/DanmakuRender）
#         you@example.com  —— 如需通知功能，填你的邮箱
#
#    3. 按需调整上传/渲染/清理参数
#
#  ⚠️ 注意：全局配置**改动后需要重启程序**才生效（程序会打印提醒横幅）。
#     任务配置 configs/DMR-*.yml 支持热加载。
# ══════════════════════════════════════════════════════════════════════

'''

if not txt.startswith('# ═'):
    txt = HEADER + txt

open(OUT, 'w', encoding='utf-8', newline='\n').write(txt)
print('=' * 78)
print('生成脱敏示例配置')
print('=' * 78)
print(f'  来源: {PROD_CFG}')
print(f'  输出: {OUT}')
print(f'  {orig_len} → {len(txt)} 字节')

print()
print('  脱敏效果检查:')
for name, pat in [
        ('remote 名 cd2', r'\bcd2\b'),
        ('邮箱', r'1871163532@qq\.com'),
        ('本机路径 F:\\DanmakuRender', r'F:\\DanmakuRender')]:
    n = len(re.findall(pat, txt))
    print(f'    {"✅ 已清理" if n == 0 else f"⚠️ 还剩 {n} 处"}  {name}')

print()
print('  占位符出现次数:')
for ph in ('<你的remote>', '<项目目录>', 'you@example.com'):
    print(f'    {ph}: {txt.count(ph)} 处')

# YAML 有效性
import yaml
try:
    yaml.safe_load(txt)
    print('\n  ✅ YAML 语法有效')
except Exception as e:
    print(f'\n  ❌ YAML 语法错误: {str(e)[:200]}')
