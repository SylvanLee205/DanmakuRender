import subprocess
import logging
import tempfile
import time

from DMR.utils import VideoInfo, replace_keywords


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

    def call_subprocess(self, file, command, timeout=None, **kwargs):
        cmds = [replace_keywords(str(x), file) for x in command]
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
