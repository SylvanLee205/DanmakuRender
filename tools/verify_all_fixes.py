"""验证生产环境所有修复是否生效。"""
import inspect
import json
import logging
import os
import sys

UP = r'F:\DanmakuRender_AutoUp'
sys.path.insert(0, UP)
os.chdir(UP)
logging.basicConfig(level=logging.ERROR)

print('=' * 78)
print('生产环境修复验证')
print('=' * 78)

from DMR.Config import Config
cfg = Config('configs/global.yml')
tasks = cfg.get_replaytasks()
n_rt = sum(1 for t in tasks
           for ft, lst in (cfg.get_replay_config(
               cfg.add_task_config(os.path.join(UP, 'configs', f'DMR-{t}.yml'))
           ).get('upload_args') or {}).items()
           for one in lst if one.get('realtime'))
print(f'  [1] realtime=true 任务数           : {n_rt}/{len(tasks)}'
      f'  {"OK" if n_rt == len(tasks) else "FAIL"}')

from DMR.Uploader.subprocess_uploader import SubprocessUploader, safe_remote_name
up = SubprocessUploader()
ok2 = True
for sub, expect in (('copy', 'copyto'), ('move', 'moveto')):
    out = up._sanitize_rclone_copy(['rclone', sub, 'F:/x/相扑猫💦-a.mp4', 'cd2:dst'], None)
    got = out[1]
    name_ok = not any(ord(c) > 0xFFFF for c in out[3])
    good = (got == expect) and name_ok
    ok2 &= good
    print(f'  [2] {sub:4} → {got:6} 名字={os.path.basename(out[3])}  {"OK" if good else "FAIL"}')

from DMR.Render.ffmpeg import RawFFmpegRender
src = inspect.getsource(RawFFmpegRender.call_ffmpeg)
has_rc = 'returncode = self.render_proc.wait()' in src
print(f'  [3] ffmpeg 读取退出码               : {"OK" if has_rc else "FAIL"}')

from DMR.Render.dmrender import DmRender
src_dm = inspect.getsource(DmRender.render_one)
has_zero = 'out_size == 0' in src_dm
print(f'  [4] 渲染产物 0 字节校验             : {"OK" if has_zero else "FAIL"}')

from DMR.Task.liveevents import LiveEvents
src_le = inspect.getsource(LiveEvents)
ok5 = "'render/error': self.onTaskError" in src_le
ok6 = "'uploader/error': self.onTaskError" in src_le
print(f'  [5] render/error  → onTaskError     : {"OK" if ok5 else "FAIL"}')
print(f'  [6] uploader/error → onTaskError    : {"OK" if ok6 else "FAIL"}')
ok7 = "('ready', 'upload_skipped', 'failed')" in src_le
print(f'  [7] failed 状态可被清理             : {"OK" if ok7 else "FAIL"}')
ok8 = 'def terminal_statuses' in src_le
print(f'  [8] _free_state_memory 按 vtype 判定 : {"OK" if ok8 else "FAIL"}')
ok9 = "srcpre_info = video_state.get('src_video_pre') or {}" in src_le
print(f'  [9] src_video_pre 有 .get 保护      : {"OK" if ok9 else "FAIL"}')

src_cfg = inspect.getsource(
    __import__('DMR.Config', fromlist=['Config']).Config.add_task_config)
ok10 = 'pending_hash' in src_cfg and 'self.file_hashes[config_path] = current_hash' not in src_cfg
print(f'  [10] 任务加载失败不再吞 hash        : {"OK" if ok10 else "FAIL"}')

print()
allok = all([n_rt == len(tasks), ok2, has_rc, has_zero, ok5, ok6, ok7, ok8, ok9, ok10])
print('=' * 78)
print(f'  总体: {"✅ 全部修复已生效" if allok else "⚠ 有项目未生效"}')
print('=' * 78)
