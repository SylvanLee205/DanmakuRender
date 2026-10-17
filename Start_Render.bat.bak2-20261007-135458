@echo off
:: 设置 UTF-8 编码以支持中文
chcp 65001 >nul
title DanmakuRender_守护进程

:: --- 配置区 ---
:: 建议只保留 SendKey 部分，方便后期管理
set "API_URL=https://17530.push.ft07.com/send/sctp17530thl3urer2dsbnw3rnqyxzep.send"
set "TITLE=DMR服务器状态报告"
set "CONTENT=渲染服务器已成功复活。Intel A380 驱动正常，AV1 录制环境准备就绪。"
:: -------------

:loop
cls
echo [%date% %time%] 正在启动服务...

:: 使用 POST 方式发送通知，--data-urlencode 确保中文传输不乱码
curl -s --data-urlencode "title=%TITLE%" --data-urlencode "desp=%CONTENT%" "%API_URL%" >nul

:: 切换到项目盘符和目录
F:
cd "F:\DanmakuRender_AutoUp"

:: 调用虚拟环境运行程序
".\.venv\Scripts\python.exe" main.py --quiet

echo.
echo [%date% %time%] 警告：程序已退出（可能是崩溃或手动关闭）。
echo 10秒后将自动尝试重新循环启动...
echo.

:: 等待10秒
timeout /t 10
goto loop