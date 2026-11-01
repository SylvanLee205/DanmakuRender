"""进程级单实例锁（Windows 命名互斥体）。

为什么需要
----------
能拉起 DMR 的入口有三个：

  · 开机计划任务 DMR_Boot（session 0）
  · 登录自启 DMR_AutoUp.cmd（session 1）
  · 用户手动双击 Start_Render.bat / Start_DMR.bat

三者各自都有进程检查（`tools/autostart_launch.py`、`tools/single_instance.py`），
但检查通过之后、python 进程真正出现之前有几秒空档（开机时磁盘忙会更长）。
两边同时通过检查就会起两个 DMR，而两个实例共用同一份状态库、同一个录制目录，
会互相覆盖产物状态、同时往同一个 `[正在录制]xxx.ts` 里写。

为什么用 `Global\\` 前缀
------------------------
开机任务在 session 0，登录自启在 session 1。`Local\\` 互斥体只在会话内可见，
两边互相看不见，防不住跨会话双开。`Global\\` 才是全机器唯一。

为什么全程 fail-open
--------------------
无人值守机器上"能起来"比"绝不双开"更重要：任何异常（无权限建 Global 互斥体、
ctypes 缺失等）都返回 None，让调用方照常启动。
"""
import sys

MUTEX_NAME = r'Global\DanmakuRender_AutoUp_SingleInstance'
ERROR_ALREADY_EXISTS = 183

#: 持有句柄，进程存活期间不能被回收
_handle = None


def acquire(name: str = MUTEX_NAME):
    """尝试占有单实例锁。

    返回
    ----
    ``'busy'``  已有实例在跑（调用方应退出）
    ``handle``  拿到了锁（调用方**不要**关闭它，进程退出时系统自动释放）
    ``None``    平台不支持 / 出错 —— 调用方按"没有锁"处理，照常启动
    """
    global _handle
    if sys.platform != 'win32':
        return None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.CreateMutexW.restype = wintypes.HANDLE
        k32.CreateMutexW.argtypes = (wintypes.LPCVOID, wintypes.BOOL,
                                     wintypes.LPCWSTR)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        k32.CloseHandle.restype = wintypes.BOOL

        handle = k32.CreateMutexW(None, True, name)
        if not handle:
            return None
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            k32.CloseHandle(handle)
            return 'busy'
        _handle = handle
        return handle
    except Exception:                                        # noqa: BLE001
        return None
