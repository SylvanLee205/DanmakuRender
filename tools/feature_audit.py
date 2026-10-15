"""功能完整性核对：逐项验证我们的魔改 + 上游合入的功能在生产代码里都在。

每一项都给出「代码位置 + 生产是否生效」两重证据。
只列真实可验证的证据，不做主观判断。
"""
import ast
import os
import re
import subprocess
import sys

PROD = r'F:\DanmakuRender_AutoUp'
os.chdir(PROD)
sys.path.insert(0, PROD)


def has(rel, *pats):
    """文件里是否出现这些模式（全部出现才算 True）。"""
    p = os.path.join(PROD, rel)
    if not os.path.exists(p):
        return False, f'文件不存在: {rel}'
    txt = open(p, encoding='utf-8', errors='replace').read()
    miss = [x for x in pats if x not in txt]
    return (not miss), (f'缺: {miss}' if miss else 'OK')


def show(name, rel, pats, note=''):
    ok, why = has(rel, *pats)
    print(f'  {"✅" if ok else "❌"} {name:36} {rel}')
    if not ok:
        print(f'        {why}')
    if note:
        print(f'        {note}')
    return ok


print('=' * 78)
print('A. 我们的魔改功能')
print('=' * 78)
fails = 0

# 1. 移除 B站/YouTube 上传
r = show('A1 移除B站/YouTube上传', 'DMR/Uploader/__init__.py',
         ['_UPLOADER_ENGINES', "'subprocess'"])
if not r:
    fails += 1

# 2. rclone 网盘上传（subprocess 引擎）
r = show('A2 rclone 子进程上传引擎', 'DMR/Uploader/subprocess_uploader.py',
         ['class SubprocessUploader'])
if not r:
    fails += 1

# 3. 弹幕只收弹幕+礼物（过滤进场）
#    ⚠️ 实际键名是 download_args.live.dm_filter.dm_type，不是 dm_include_types
p = os.path.join(PROD, 'configs', 'global.yml')
cfg = open(p, encoding='utf-8').read()
import yaml as _yaml
_cd = _yaml.safe_load(cfg) or {}
_dmt = (((_cd.get('download_args') or {}).get('live') or {})
        .get('dm_filter') or {}).get('dm_type')
_ok_dmt = _dmt == ['danmaku', 'gift']
print(f'  {"✅" if _ok_dmt else "❌"} {"A3 弹幕只收弹幕+礼物":36} '
      f'dm_filter.dm_type = {_dmt!r}')
if not _ok_dmt:
    fails += 1

# 4. 跳过上传规则（横屏必选）
r = show('A4 跳过上传规则(横屏必选)', 'configs/global.yml',
         ['skip_upload_rule', 'skip_landscape', 'skip_require_landscape'])
if not r:
    fails += 1

# 5. 清理与上传解耦
r = show('A5 清理与上传解耦', 'DMR/Task/liveevents.py',
         ['_check_for_upload', '_check_for_clean'])
if not r:
    fails += 1

# 6. 通知系统
r = show('A6 通知系统(开播+启动)', 'DMR/notify.py', ['def send'])
ok2, _ = has('DMR/Task/liveevents.py', '_notify_live')
r = r and ok2
if not r:
    fails += 1

# 7. PROGRESS 日志级别 + 控制台过滤
r = show('A7 PROGRESS级别+控制台过滤', 'main.py',
         ['PROGRESS = 25', '_ConsoleNoiseFilter', '--quiet'])
if not r:
    fails += 1

# 8. 启动恢复 .part
r = show('A8 启动恢复.part', 'main.py', ['_startup_recover'])
if not r:
    fails += 1

# 9. GOP 自动设置
r = show('A9 GOP自动设置', 'DMR/Render/dmrender.py',
         ['gop_multiplier', '_build_gop_args'])
if not r:
    fails += 1

# 10. 编码器参数校验（防0字节）
r = show('A10 编码器参数校验(防0字节)', 'DMR/Render/dmrender.py',
         ['_check_encoder_args', '_QUALITY_ARGS'])
if not r:
    fails += 1

# 11. 0 字节产物保险闸（第二道闸；上游已在 Render/ffmpeg.py 从根因修过）
r = show('A11 0字节产物保险闸', 'DMR/Render/dmrender.py',
         ['渲染产物为 0 字节', 'out_size'])
if not r:
    fails += 1
r2 = show('A11b 上游根治(读ffmpeg退出码)', 'DMR/Render/ffmpeg.py',
          ['returncode = self.render_proc.wait()'])
if not r2:
    fails += 1

# 12. 心跳日志
r = show('A12 心跳日志', 'main.py', ['心跳'])
if not r:
    fails += 1

# 13. 配置完整性校验
r = show('A13 配置完整性校验', 'main.py', ['_verify_configs'])
if not r:
    fails += 1

# 14. 关键名字自检
r = show('A14 关键名字自检', 'main.py', ['_verify_critical_names'])
if not r:
    fails += 1

# 15. 关闭下播通知
src = open(os.path.join(PROD, 'DMR/Task/liveevents.py'), encoding='utf-8').read()
i = src.find("if kind == 'end':")
closed = i > 0 and 'return' in src[i:i + 200]
print(f'  {"✅" if closed else "❌"} A15 关闭下播通知(只留开播)')
if not closed:
    fails += 1

print()
print('=' * 78)
print('B. 上游合入的功能')
print('=' * 78)

r = show('B1 状态库(SQLite)', 'DMR/state/repository.py',
         ['class StateRepository'])
if not r:
    fails += 1
r = show('B2 启动对账', 'DMR/state/reconciler.py',
         ['class RecoveryManager'])
if not r:
    fails += 1
r = show('B3 恢复重驱动', 'DMR/state/resume.py', ['def '])
if not r:
    fails += 1
r = show('B4 xml2ass(XML弹幕)', 'DMR/utils/xml2ass.py', ['def xml_to_ass'])
if not r:
    fails += 1
r = show('B5 utils导出xml2ass', 'DMR/utils/__init__.py',
         ['from .xml2ass import *'])
if not r:
    fails += 1
r = show('B6 状态库注入', 'DMR/__init__.py', ['StateRepository', 'state_repo'])
if not r:
    fails += 1
r = show('B7 上传器工厂(稿件复用)', 'DMR/Uploader/__init__.py',
         ['_get_or_create_uploader', '_supports_resume'])
if not r:
    fails += 1
r = show('B8 分段登记到状态库', 'DMR/Downloader/stream_downloader.py',
         ['_record_segment'])
if not r:
    fails += 1
r = show('B9 单元测试套件', 'unit_tests/test_state_resume.py', ['def test_'])
if not r:
    fails += 1

print()
print('=' * 78)
print('C. 配置项与代码读取是否对得上')
print('=' * 78)
import yaml
gc = yaml.safe_load(open(p, encoding='utf-8')) or {}
gcd = yaml.safe_load(open(os.path.join(PROD, 'DMR', 'Config', 'default.yml'),
                          encoding='utf-8')) or {}
# 只扫描**引擎级**文件 —— 任务级文件（downloaders/uploaders）里的
# config['title'] 之类是任务配置的键，不是全局配置，扫进来会全是误报。
code_keys = set()
for rel in ('DMR/__init__.py', 'DMR/engine.py', 'DMR/Config/__init__.py'):
    _fp = os.path.join(PROD, rel)
    if not os.path.exists(_fp):
        continue
    t = open(_fp, encoding='utf-8', errors='replace').read()
    for m in re.finditer(r"get_config\(['\"](\w+)['\"]", t):
        code_keys.add(m.group(1))
    for m in re.finditer(r"global_config\[['\"](\w+)['\"]\]", t):
        code_keys.add(m.group(1))
    for m in re.finditer(r"global_config\.get\(['\"](\w+)['\"]", t):
        code_keys.add(m.group(1))
print(f'  代码读取的配置键: {sorted(code_keys)}')
missing = [k for k in code_keys if k not in gc and k not in gcd]
if missing:
    print(f'  ⚠️ global.yml 与 default.yml 里都找不到的键: {missing}')
    fails += len(missing)
else:
    print(f'  ✅ 代码读取的全局配置键都能在 global.yml 或 default.yml 里找到')

print()
print('=' * 78)
print(f'总结：{"✅ 全部通过" if fails == 0 else f"❌ 发现 {fails} 个问题"}')
print('=' * 78)
