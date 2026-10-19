import platform
import warnings
import sys
import subprocess

__all__ = ('check_pypi', 'check_update')

def compare_version(ver1, ver2):
    list1 = str(ver1).split(".")
    list2 = str(ver2).split(".")
    for i in range(len(list1)) if len(list1) < len(list2) else range(len(list2)):
        if int(list1[i]) == int(list2[i]):
            pass
        elif int(list1[i]) < int(list2[i]):
            return -1
        else:
            return 1
    if len(list1) == len(list2):
        return 0
    elif len(list1) < len(list2):
        return -1
    else:
        return 1

def check_pypi():
    try:
        import requests
        import aiohttp
        import jsengine
        import lxml
        import yaml
        import stream_gears
        import google.protobuf 
        import websocket
        import brotli
        import yutto
        import easydict
        import streamlink
        import m3u8
        import gmssl
        import rsa
        import PIL
        import flask
        return True
    except ImportError as _imp_err:
        # ⚠️ 2026-10-19：原来是裸 input()。无人值守启动时（计划任务 / session 0 /
        #    开机自启）没有控制台，input() 会抛 EOFError 或永久挂住 —— 而那时
        #    main.py **还没配置日志**，表现为"程序根本没起、连一行日志都没有"。
        #    现在：交互终端仍然提示自动安装；非交互则写诊断文件 + 退出码 2。
        try:
            input('Python 包未正确安装，回车自动安装:')
        except EOFError:
            _msg = (f'缺少 Python 依赖（{_imp_err}），且当前无控制台无法交互安装。\n'
                    f'请在命令行执行：\n'
                    f'  cd /d F:\\DanmakuRender_AutoUp\n'
                    f'  .venv\\Scripts\\python.exe -m pip install -r requirements.txt\n')
            try:
                import os
                os.makedirs('logs', exist_ok=True)
                with open(os.path.join('logs', 'startup_error.log'), 'a',
                          encoding='utf-8') as _f:
                    import time
                    _f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {_msg}\n')
            except Exception:
                pass
            print(_msg)
            raise SystemExit(2)
        subprocess.Popen([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt', '-i', 'https://pypi.tuna.tsinghua.edu.cn/simple']).wait()
        print('Python 包安装完成.')
        return 

def check_update(version):
    try:
        import requests
        resp = requests.get('https://api.github.com/repos/SmallPeaches/DanmakuRender/releases/latest', timeout=5).json()
        lastest_version = resp["tag_name"]
        if compare_version(lastest_version, version) > 0:
            print('存在可用更新：')
            print(f"版本：{lastest_version}")
            print(f"发行时间：{resp['published_at']}")
            print(f"发行说明：{resp.get('name')}")
            print(f"{resp.get('body','')}\n")
            print("如果需要更新可以直接运行 update.py 或者前往 https://github.com/SmallPeaches/DanmakuRender 更新.")
            print('')
    except Exception as e:
        print(f'检查更新失败, {e}')