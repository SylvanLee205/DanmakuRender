import subprocess
import json
import warnings
import re

from .toolsmgr import ToolsList

class FFprobe():
    header = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 '
                                '(KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36 '
            }

    @classmethod
    def ffprobe(cls) -> str:
        return ToolsList.get('ffprobe')
    
    @classmethod
    def run_ffprobe(cls,fpath):
        out = subprocess.check_output([
            cls.ffprobe(),
            '-i', fpath,
            '-print_format','json',
            '-select_streams', 'v:0',
            '-show_format','-show_streams',
            '-v','quiet'
            ])
        out = out.decode('utf8')
        res = json.loads(out)
        return res
        
    @classmethod
    def get_duration(cls,fpath) -> float:
        try:
            res = cls.run_ffprobe(fpath)
            try:
                st = float(res['format']['start_time'])
            except:
                st = 0
            duration = float(res['format']['duration'])-st
            return max(duration, 0)
        except:
            return -1

    @classmethod
    def run_ffprobe_livestream(cls, url, header=None):
        if header is None:
            header = cls.header
        out = subprocess.check_output([
            cls.ffprobe(),
            '-headers', ''.join('%s: %s\r\n' % x for x in header.items()),
            '-i', url,
            '-select_streams', 'v:0', 
            '-print_format','json',
            '-show_format','-show_streams',
            '-v','quiet'
            ],
            timeout=15,
        )
        out = out.decode('utf8')
        res = json.loads(out)
        return res

    @classmethod
    def get_livestream_info(cls,url,header=None) -> dict:
        res = cls.run_ffprobe_livestream(url,header)
        return res['streams'][0]
        
    @classmethod
    def get_resolution(cls, url:str, header=None) -> tuple:
        try:
            if url.startswith('http'):
                res = cls.run_ffprobe_livestream(url, header)
            else:
                res = cls.run_ffprobe(url)
            resolution = res['streams'][0]['width'],res['streams'][0]['height']
            return resolution
        except:
            return 0,0

    @classmethod
    def get_fps(cls, url:str, header=None, fallback:float=0.0) -> float:
        """获取视频帧率（浮点数）。

        优先使用 r_frame_rate（真实基础帧率），失败时回退到 avg_frame_rate。
        获取不到时返回 fallback（默认 0，调用方需要自己决定兜底值）。
        """
        try:
            if str(url).startswith('http'):
                res = cls.run_ffprobe_livestream(url, header)
            else:
                res = cls.run_ffprobe(url)
            stream = res['streams'][0]

            for key in ('r_frame_rate', 'avg_frame_rate'):
                rate = stream.get(key)
                if not rate or rate in ('0/0', '0'): 
                    continue
                num, _, den = str(rate).partition('/')
                den = den or '1'
                try:
                    fps = float(num) / float(den)
                except (ZeroDivisionError, ValueError):
                    continue
                if fps > 0:
                    return fps
        except Exception:
            pass
        return fallback