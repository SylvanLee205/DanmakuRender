"""部署后功能回归验证：确认上传等核心功能没受影响。

验证项（对照 prod 的实际行为）：
  1. upload_args_task_default 的 rclone 上传规则能被正确解析
  2. Uploader 能用 subprocess 引擎创建
  3. 上传命令模板替换正确（{PATH} / {TASKNAME}）
  4. 跳过上传规则判断和之前一致
  5. Cleaner 能删除文件（basename 修复）
  6. 状态库的 artifact 同步不影响上传流程
  7. 渲染插件接口兼容（DmRender 可构造）
"""
import logging
import os
import subprocess
import sys
import tempfile

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根目录，自动识别（可放在任意路径）

PROD = _PROJECT_ROOT
os.chdir(PROD)
sys.path.insert(0, PROD)
logging.basicConfig(level=logging.CRITICAL)

print('=' * 78)
print('部署后功能回归验证')
print('=' * 78)

# ── 1. 配置解析 ──
print()
print('1. 上传配置解析')
from DMR.Config import Config
cfg = Config(os.path.join(PROD, 'configs', 'global.yml'))
gc = cfg.global_config
ua = gc.get('upload_args') or {}
utd = gc.get('upload_args_task_default') or {}
print(f'   upload_args 引擎: {sorted(ua.keys())}')
rclone = ua.get('rclone') or {}
print(f'   rclone 段: engine={rclone.get("engine")}, retry={rclone.get("retry")}, '
      f'realtime={rclone.get("realtime")}')
dmv = utd.get('dm_video')
print(f'   dm_video 规则: {len(dmv) if dmv else 0} 条')
if dmv:
    r0 = dmv[0]
    print(f'       target={r0.get("target")}  engine={r0.get("engine")}  '
          f'realtime={r0.get("realtime")}')
    print(f'       command={r0.get("command")}')
    ok_rclone = 'rclone' in (r0.get('command') or [])
    print(f'   >>> rclone 上传命令: {"✅ 存在" if ok_rclone else "❌ 缺失"}')

# ── 2. Uploader 构造 ──
print()
print('2. Uploader 能否用 subprocess 引擎创建')
from DMR.Uploader import Uploader


def _tool(name):
    """定位外部工具：环境变量 -> tools/ -> PATH -> 注册表 PATH -> 安装目录。

    见 DMR/utils/toolsmgr.py。不写死版本号和安装位置 ——
    换个 rclone 版本、换台电脑都不用改代码。
    """
    import os as _o
    import sys as _s
    _root = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
    if _root not in _s.path:
        _s.path.insert(0, _root)
    from DMR.utils.toolsmgr import find_tool
    return find_tool(name) or name

try:
    task = {
        'engine': 'subprocess',
        'upload_group': 'testgroup',
        'args': dict(rclone),
        'expire': 3600,
    }
    # 不启动线程，只测工厂方法
    up = Uploader.__new__(Uploader)
    up._lock = __import__('threading').RLock()
    up._uploader_pool = {}
    up.logger = logging.getLogger('test')
    up._uploader_factory = None
    up.state_repo = None
    cls = up._get_or_create_uploader(task)
    print(f'   ✅ 创建成功: {type(cls).__name__}')
except Exception as e:
    import traceback
    print(f'   ❌ 失败: {type(e).__name__}: {e}')
    traceback.print_exc()

# ── 3. 命令模板替换 ──
print()
print('3. 上传命令模板替换（{PATH} / {TASKNAME}）')
try:
    from DMR.utils import VideoInfo, StreamerInfo
    from DMR.utils.utils import replace_keywords
    # 用构造出来的假路径即可 —— 这里只验证 {PATH}/{TASKNAME} 的替换，
    # 文件不必真实存在（原来是写死的 F:\tmp\...，换机器就失效）
    _fake = os.path.join(_PROJECT_ROOT, '直播回放', '测试主播',
                         '测试主播-2026年10月15日20点00分（弹幕版）.mp4')
    vi = VideoInfo(path=_fake,
                   streamer=StreamerInfo(name='测试主播'),
                   taskname='测试主播', dtype='dm_video')
    cmd_tpl = (dmv or [{}])[0].get('command') or []
    out = [replace_keywords(str(x), vi) if isinstance(x, str) else x
           for x in cmd_tpl]
    print(f'   模板 : {cmd_tpl}')
    print(f'   展开 : {out}')
    ok = any('测试主播' in str(x) and '（弹幕版）' in str(x) for x in out)
    print(f'   >>> 替换: {"✅ 正确" if ok else "⚠ 需检查"}')
except Exception as e:
    import traceback
    print(f'   ❌ {type(e).__name__}: {e}')
    traceback.print_exc()

# ── 4. 跳过上传规则 ──
print()
print('4. 跳过上传规则（应和部署前一致）')
sru = ((gc.get('render_args') or {}).get('dmrender') or {}).get('skip_upload_rule')
print(f'   配置: {sru}')
EXPECT = {'enabled': True, 'skip_landscape': True, 'skip_require_landscape': True}
if sru:
    same = all(sru.get(k) == v for k, v in EXPECT.items())
    print(f'   >>> 与预期{"一致 ✅" if same else "不一致 ❌"}')

# ── 5. Cleaner（basename 修复）──
print()
print('5. Cleaner 删除功能（basename 修复验证）')
tmpd = tempfile.mkdtemp(prefix='dmr_regr_')
src = os.path.join(tmpd, 'x.mkv')
ass = os.path.join(tmpd, 'x.ass')
open(src, 'wb').write(b'x' * 100)
open(ass, 'w', encoding='utf-8').write('d')
try:
    import queue as _q
    from DMR.Cleaner import Cleaner
    from DMR.utils import FileInfo
    c = Cleaner(pipe=(_q.Queue(), _q.Queue()))
    fi = FileInfo(path=src)
    try:
        fi['dm_file_id'] = ass
    except Exception:
        pass
    c._clean_subprocess({'method': 'delete', 'args': {}, 'files': [fi],
                         'source': 't', 'request_id': 't'})
    a = not os.path.exists(src)
    b = not os.path.exists(ass)
    print(f'   源文件删除={a}  弹幕删除={b}  '
          f'{"✅ 正常" if (a and b) else "❌ 异常"}')
    import shutil
    shutil.rmtree(tmpd, ignore_errors=True)
except Exception as e:
    import traceback
    print(f'   ❌ {type(e).__name__}: {e}')
    traceback.print_exc()

# ── 6. 渲染插件接口 ──
print()
print('6. DmRender 构造（渲染插件接口兼容）')
ra = (gc.get('render_args') or {}).get('dmrender') or {}
try:
    from DMR.Render.dmrender import DmRender
    r = DmRender(**ra)
    print(f'   ✅ 构造成功')
    print(f'      dmconvert={"✅" if hasattr(r, "dmconvert") else "❌"}  '
          f'gop_multiplier={getattr(r, "gop_multiplier", None)}  '
          f'gop_default_fps={getattr(r, "gop_default_fps", None)}')
except Exception as e:
    import traceback
    print(f'   ❌ {type(e).__name__}: {e}')
    traceback.print_exc()

# ── 7. 状态库 ──
print()
print('7. 状态库可用性')
try:
    from DMR.state import StateRepository
    db = os.path.join(PROD, 'logs', 'dmr_state.db')
    print(f'   文件: {os.path.getsize(db) if os.path.exists(db) else "不存在"} 字节')
    repo = StateRepository(db).open()
    sessions = repo.list_sessions()
    print(f'   ✅ 打开成功，schema=v{repo.schema_version}，会话 {len(sessions)} 个')
    repo.close()
except Exception as e:
    import traceback
    print(f'   ❌ {type(e).__name__}: {e}')
    traceback.print_exc()

# ── 8. 实际上传测试（可选）──
print()
print('8. 实际 rclone 连通性（只读，不传文件）')
rclone_exe = None
for p in (_tool('rclone'), 'rclone'):
    if p == 'rclone' or os.path.exists(p):
        rclone_exe = p
        break
if rclone_exe:
    r = subprocess.run([rclone_exe, 'lsf', 'cd2:百度网盘/DMR录播',
                        '--max-depth', '1'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=180)
    dirs = [x.strip() for x in (r.stdout or '').split('\n') if x.strip()]
    print(f'   exit={r.returncode}  云端任务目录 {len(dirs)} 个')
    print(f'   >>> rclone 连通: {"✅ 正常" if r.returncode == 0 else "❌ 异常"}')
    if r.returncode != 0:
        print(f'       {(r.stderr or "")[:200]}')

print()
print('=' * 78)
print('回归验证完成')
print('=' * 78)
