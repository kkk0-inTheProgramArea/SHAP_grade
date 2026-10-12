@echo off
chcp 65001 >nul
title 成绩清洗与SHAP分析 - 本地预览
cd /d "%~dp0"

set "PY=C:\Users\25195\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo ================================================================
echo   成绩数据清洗 ^& SHAP 分析 —— 本地预览
echo ----------------------------------------------------------------
echo   改完 app.py 或 templates\index.html 后，重跑本脚本即可看效果
echo   启动成功后，用浏览器打开：  http://127.0.0.1:5000
echo   停止服务：直接关闭这个黑窗口（或按 Ctrl+C）
echo ================================================================
echo.

"%PY%" app.py

echo.
echo 服务已退出。
pause
