import os
import re
import subprocess
import logging
import tempfile
import time

from DMR.utils import VideoInfo, replace_keywords

# 非 BMP 字符（emoji 等）——百度网盘开放平台 API 会拒绝含这类字符的路径，
# 返回 errno -7「文件或目录无权访问」。CD2 作为第三方客户端无法绕过，
# 官方客户端不受影响。所以必须在**上传层**兜底清洗远程文件名。
# 覆盖：Emoji 主体、杂项符号、装饰符号、国旗、变体选择符、零宽连接符、
#       键帽、其他符号、CJK 兼容补充。
_EMOJI_RE = re.compile(
    '['
    '\U0001F000-\U0001FAFF'   # Emoji 主体（含 💦 U+1F4A6）
    '\U00002600-\U000027BF'   # 杂项符号 + 装饰符号（含 ❤ ✅ 等）
    '\U0001F1E6-\U0001F1FF'   # 区域指示符（国旗）
    '\U0000FE00-\U0000FE0F'   # 变体选择符
    '\U0000200D'              # 零宽连接符 ZWJ
    '\U000020E3'              # 键帽 combining enclosing keycap
    '\U00002B00-\U00002BFF'   # 其他符号与箭头
    '\U00002190-\U000021FF'   # 箭头（部分表情会带）
    '\U0001F900-\U0001F9FF'   # 补充符号（已在主体范围内，冗余但明确）
    ']+'
)


def safe_remote_name(name: str) -> str:
    """把文件名里百度网盘不接受的字符去掉，得到一个可上传的名字。

    只清洗**远程**名字，本地文件名保持不变（继续留档）。
    """
    if not name:
        return 'unnamed'
    cleaned = _EMOJI_RE.sub('', name)
    # 去掉 emoji 后可能留下多余空格/括号前的空格，收拾一下
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = re.sub(r'([（(])\s+', r'\1', cleaned)
    cleaned = re.sub(r'\s+([）)])', r'\1', cleaned)
    # 保留扩展名，避免全被清空
    stem, dot, ext = cleaned.rpartition('.')
    if not dot:
        stem, ext = cleaned, ''
    if not stem.strip():
        stem = 'unnamed'
    return f'{stem}.{ext}' if ext else stem


def has_bad_remote_chars(name: str) -> bool:
    """名字里有没有百度开放平台会拒绝的字符（非 BMP / emoji）。"""
    return bool(_EMOJI_RE.search(name)) or any(ord(c) > 0xFFFF for c in name)


class SubprocessUploader:
    """通过子进程调用外部程序上传（网盘归档用 rclone，也可以接任意自定义命令）。

    魔改点（相对原版）：
      1. 原版直接把子进程 stdout/stderr 交给父进程，出错时日志里看不到任何原因，
         只知道 "return code: 1"。现在把输出重定向到临时文件，失败时把尾部内容带进错误信息。
      2. 原版命令不存在时抛 FileNotFoundError，会被上层当成未知异常；现在会给出明确提示。
      3. 成功时报告耗时，方便判断上传是否真的在跑。
    """

    def __init__(self, **kwargs) -> None:
        self.procs = {}
        self.logger = logging.getLogger(__name__)

    def _sanitize_rclone_copy(self, cmds: list, file) -> list:
        """把 `rclone copy <src> <dst目录>` 改写成 `rclone copyto <src> <dst目录>/<干净名>`。

        只在「命令是 rclone copy、且目标文件名含 emoji」时才动，其它情况原样返回。
        """
        try:
            if len(cmds) < 4:
                return cmds
            if not os.path.basename(str(cmds[0])).lower().startswith('rclone'):
                return cmds
            if str(cmds[1]) != 'copy':
                return cmds

            src, dst = str(cmds[2]), str(cmds[3])
            remote_name = os.path.basename(src.replace('\\', '/'))
            if not has_bad_remote_chars(remote_name):
                return cmds

            safe = safe_remote_name(remote_name)
            target = dst.rstrip('/') + '/' + safe
            self.logger.warning(
                f'远程文件名含 emoji（百度网盘 API 会拒绝），已自动改名为: '
                f'{remote_name}  ->  {safe}'
            )
            return [cmds[0], 'copyto', src, target] + list(cmds[4:])
        except Exception as e:
            self.logger.debug(f'文件名清洗跳过（不影响上传）: {e}')
            return cmds

    def call_subprocess(self, file, command, timeout=None, **kwargs):
        cmds = [replace_keywords(str(x), file) for x in command]

        # ── 兜底：把远程文件名里的 emoji 去掉 ──────────────────────────
        # 背景（2026-10-05 实测）：百度网盘开放平台 API 拒绝含 emoji 的路径，
        # 返回 errno -7；而 CD2 WebDAV 收到 PUT 会先回 2xx（落暂存后异步上传），
        # 所以 **rclone 退出码是 0**，DMR 会误判成功 → 静默丢失。
        # rclone 的 `copy` 不改名，必须换成 `copyto <源> <目标目录>/<干净文件名>`。
        cmds = self._sanitize_rclone_copy(cmds, file)

        self.logger.debug(f'Subprocess uploader: {cmds}')

        with tempfile.TemporaryFile() as logfile:
            try:
                proc = subprocess.Popen(cmds, stdout=logfile, stderr=subprocess.STDOUT)
            except FileNotFoundError as e:
                # 最常见：命令不在 PATH 里（例如没装 rclone / 名字写错）
                return False, f'无法启动 {cmds[0]}: {e}'

            self.procs[proc.pid] = proc
            status, message = False, ''
            start = time.time()
            try:
                if timeout:
                    proc.wait(timeout=timeout)
                else:
                    proc.wait()
                elapsed = time.time() - start
                status = proc.returncode == 0
                if status:
                    message = f'{cmds[0]} 上传成功，耗时 {elapsed:.1f}s: {file.path}'
                else:
                    message = (f'{cmds[0]} 返回码 {proc.returncode}（耗时 {elapsed:.1f}s）: '
                               f'{self._tail(logfile)}')
            except subprocess.TimeoutExpired:
                status = False
                proc.kill()
                message = f'{cmds[0]} 超时（{timeout}s）被终止: {self._tail(logfile)}'
            finally:
                self.procs.pop(proc.pid, None)
            return status, message

    @staticmethod
    def _tail(logfile, max_bytes: int = 2000) -> str:
        """读取子进程输出的尾部，用于报错时给出可读原因。"""
        try:
            logfile.seek(0, 2)
            size = logfile.tell()
            logfile.seek(max(0, size - max_bytes))
            text = logfile.read().decode('utf-8', errors='replace').strip()
            return text or '(子进程没有任何输出)'
        except Exception as e:
            return f'(读取子进程输出失败: {e})'

    def upload(self, files: list[VideoInfo], **kwargs):
        if not isinstance(files, list):
            files = [files]

        status, message = True, ''
        for file in files:
            try:
                sts, msg = self.call_subprocess(file, **kwargs)
                status = status and sts
                if sts:
                    message += f'File {file.path} upload success.\n'
                else:
                    message += f'File {file.path} upload failed: {msg}\n'
            except Exception as e:
                status = False
                message += f'File {file.path} upload raise an error: {e}\n'

        return status, message.strip()

    def stop(self):
        for pid, proc in list(self.procs.items()):
            try:
                proc.kill()
            except Exception as e:
                self.logger.error(f'Error stopping process {pid}: {e}')
