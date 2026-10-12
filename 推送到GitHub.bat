@echo off
rem ==========================================================
rem  双击本文件：把本项目推送到 GitHub 仓库 SHAP_grade
rem  第一次运行会弹出浏览器让你登录 GitHub，登录后自动完成。
rem ==========================================================
cd /d "%~dp0"

rem 找到 git.exe：优先用 WorkBuddy 自带的，找不到就用系统里装的
set "GITEXE=D:\Programs\WorkBuddy\resources\vendor\PortableGit\mingw64\bin\git.exe"
if not exist "%GITEXE%" (
  where git >nul 2>&1
  if errorlevel 1 (
    echo 没有找到 git，请先安装 Git: https://git-scm.com/
    pause
    exit /b 1
  )
  set "GITEXE=git"
)
for %%i in ("%GITEXE%") do set "GITDIR=%%~dpi"
set "PATH=%GITDIR%;%PATH%"

echo 正在推送到 https://github.com/kkk0-inTheProgramArea/SHAP_grade
echo 若弹出浏览器，请登录 GitHub 并点击授权。
echo.

"%GITEXE%" push -u origin main
if not errorlevel 1 goto ok

echo.
echo 普通推送被拒绝，改用覆盖方式推送一次
echo （会覆盖 GitHub 上自动生成的 README，本项目自己的 README 会保留）
"%GITEXE%" push -u origin main --force
if not errorlevel 1 goto ok

echo.
echo [失败] 请把上面的提示截图发给我。
echo   1. 提示要登录：在弹出浏览器登录 GitHub 后，重新双击本文件
echo   2. 提示网络错误：换个网络环境再试
pause
exit /b 1

:ok
echo.
echo [成功] 打开下面地址就能看到代码：
echo   https://github.com/kkk0-inTheProgramArea/SHAP_grade
pause
