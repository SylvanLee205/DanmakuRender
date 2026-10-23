from datetime import datetime
import json
import re
import platform
import warnings
from os import system
import os
import shutil
import sys
import zipfile
import subprocess


__all__ = ('check_ffmpeg','check_biliup','ToolsList')

def check_ffmpeg():
    if os.path.exists('tools/ffmpeg.exe') and os.path.exists('tools/ffprobe.exe'):
        ToolsList.set('ffmpeg', 'tools/ffmpeg.exe')
        ToolsList.set('ffprobe', 'tools/ffprobe.exe')
        return True
    
    try:
        proc = subprocess.Popen(['ffmpeg','-version'],stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = proc.stdout.readlines()[0].decode('utf-8')
        if 'ffmpeg version' in out:
            ToolsList.set('ffmpeg', 'ffmpeg')
        proc = subprocess.Popen(['ffprobe','-version'],stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = proc.stdout.readlines()[0].decode('utf-8')
        if 'ffprobe version' in out:
            ToolsList.set('ffprobe', 'ffprobe')
        return True
    except:
        pass
    
    if sys.platform == 'win32':
        # ⚠️ 2026-10-19：与 check_env/check_biliup 同一类坑 —— 裸 input() 在
        #    无控制台（计划任务 / session 0 / 开机自启）时会 EOFError，
        #    而那时 main.py 还没配置日志 → 表现为"程序完全没启动"。
        try:
            input('FFmpeg 未正确安装，回车自动安装:')
        except EOFError:
            _msg = ('找不到 ffmpeg：PATH 里没有，tools/ 下也没有。\n'
                    '请在命令行确认 `where ffmpeg` 能输出路径，或把 ffmpeg.exe/ffprobe.exe '
                    '放到 tools/ 目录。')
            try:
                os.makedirs('logs', exist_ok=True)
                with open(os.path.join('logs', 'startup_error.log'), 'a',
                          encoding='utf-8') as _f:
                    _f.write(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] {_msg}\n')
            except Exception:
                pass
            print(_msg)
            raise SystemExit(2)
        
        import requests
        print('正在下载FFmpeg (约80MB, 若下载速度过慢可以参考教程自行下载).')
        r = requests.get('https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip',stream=True)
        content = b''
        for i,chunk in enumerate(r.iter_content(1024*64)):
            print(f'\r已下载{i/16:.1f}MB.',end='')
            content += chunk
        print('')
        with open('./tools/ffmpeg-release-essentials.zip','wb') as f:
            f.write(content)

        # 检测 ffmpeg-release-essentials 完整性
        try:
            f = zipfile.ZipFile('./tools/ffmpeg-release-essentials.zip','r')
        except Exception as e:
            print("FFmpeg 安装过程出错，请检查网络连接.")
            exit(0)

        for file in f.namelist():
            f.extract(file,'./tools')
        f.close()
        ffmpeg_dir_list = [f for f in os.listdir('./tools') if 'essentials_build' in f]
        ffmpeg_version = sorted(ffmpeg_dir_list)[-1]
        shutil.move(f'./tools/{ffmpeg_version}/bin/ffmpeg.exe','./tools/ffmpeg.exe')
        shutil.move(f'./tools/{ffmpeg_version}/bin/ffplay.exe','./tools/ffplay.exe')
        shutil.move(f'./tools/{ffmpeg_version}/bin/ffprobe.exe','./tools/ffprobe.exe')

        # 清理下载文件
        shutil.rmtree(f'./tools/{ffmpeg_version}')
        os.remove("./tools/ffmpeg-release-essentials.zip")
        print('FFmpeg 安装完成.')
        ToolsList.set('ffmpeg', 'tools/ffmpeg.exe')
        ToolsList.set('ffprobe', 'tools/ffprobe.exe')
        return True
    else:
        print("FFmpeg 未正确安装，请参考安装文档.")
        exit(0)

def check_biliup():
    if os.path.exists("./tools/biliup.exe"):
        ToolsList.set('biliup', 'tools/biliup.exe')
        return True
    elif os.path.exists("./tools/biliup"):
        ToolsList.set('biliup', 'tools/biliup')
        return True

    try:
        proc = subprocess.Popen(['biliup', 'upload', '-help'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if proc.wait() == 0:
            ToolsList.set('biliup', "biliup")
            return True
    except Exception:
        pass

    if sys.platform == 'win32':
        if not os.access("./tools/biliup.exe", os.F_OK):
            # ⚠️ 2026-10-19：这里原来是裸的 input()，在服务/看门狗方式启动时
            # 会**永远挂住**（没人给他回车），表现为 DMR 启动卡死且无日志。
            # 实测：误删 tools/biliup.exe 后，非交互调用直接 EOFError。
            # 现在：交互终端才提示自动安装；否则给出明确错误并退出。
            # ⚠️ 不能用 sys.stdin.isatty() 判断：实测在 Windows 下
            #    python x.py < NUL 仍然返回 True。
            #    用 try/except 包住 input() 才靠谱：交互终端正常提示，
            #    非交互（EOF）时给出明确指引而不是一个裸 EOFError。
            try:
                input("Biliup未正确安装, 回车自动安装:")
            except EOFError:
                raise RuntimeError(
                    'tools/biliup.exe 缺失。它是**启动时强制检查**的依赖'
                    '（即使录制引擎用 ffmpeg 也会检查）。'
                    '请把 F:\\DanmakuRender_Mod\\tools\\biliup.exe 拷贝回本目录 tools/ 下。')

            import requests
            r = requests.get('https://github.com/biliup/biliup/releases/download/v1.1.28/biliupR-v1.1.28-x86_64-windows.zip', stream=True)

            # 下载
            content = b''
            for i, chunk in enumerate(r.iter_content(1024*64)):
                print(f'\r已下载{i/16:.1f}MB.', end='')
                content += chunk
            print('')

            # 写入文件
            os.makedirs('.temp', exist_ok=True)
            with open('.temp/biliuprs.zip', 'wb') as f:
                f.write(content)
            
            # 检测文件完整性
            try:
                f = zipfile.ZipFile('.temp/biliuprs.zip', 'r')
            except Exception as e:
                print("Biliup 安装过程出错，请检查网络连接或参考教程自行下载！")
                exit(0)

            # 解压
            for file in f.namelist():
                f.extract(file, '.temp')
            f.close()

            file_dir = [f for f in os.listdir('.temp') if 'biliupR-' in f]
            file_dir = sorted(file_dir)[-1]

            # 文件归位
            shutil.move(f'.temp/{file_dir}/biliup.exe', './tools/biliup.exe')

            # 删除下载文件
            shutil.rmtree(f'.temp/{file_dir}')
            os.remove('.temp/biliuprs.zip')

            print("Biliup 安装完成.")
        ToolsList.set('biliup', "tools/biliup.exe")
        return True
    
    else:
        if not os.path.exists("tools/biliup"):
            print("biliup未正确安装，请参考教程安装biliup！")
            exit(0)
        ToolsList.set('biliup', "tools/biliup")
        return True
    return 

class ToolsList(dict):
    _tools = {}

    @classmethod
    def get(cls, name:str, auto_install=True):
        if not cls._tools.get(name) and auto_install:
            if name == 'biliup':
                check_biliup()
            elif name == 'ffmpeg' or name == 'ffprobe':
                check_ffmpeg()

        return cls._tools.get(name)
    
    @classmethod
    def set(cls, name:str, path:str):
        cls._tools[name] = path