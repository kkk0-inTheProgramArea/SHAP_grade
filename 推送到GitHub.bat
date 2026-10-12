@echo off
chcp 65001 >nul
rem ============================================================
rem  双击本文件，把代码推送到 GitHub 仓库 SHAP_grade
rem  第一次推送时会自动弹出浏览器让你登录 GitHub，登录完即完成。
rem ============================================================
cd /d "%~dp0"

rem 找到 git.exe：优先用 WorkBuddy 自带的，找不到就用系统里装的
set "GITEXE=D:\Programs\WorkBuddy\resources\vendor\PortableGit\mingw64\bin\git.exe"
if not exist "%GITEXE%" (
  where git >nul 2>&1
  if errorlevel 1 (
    echo 没找到 git，请先安装 Git：https://git-scm.com/
    pause
    exit /b 1
  )
  set "GITEXE=git"
)
for %%i in ("%GITEXE%") do set "GITDIR=%%~dpi"
set "PATH=%GITDIR%;%PATH%"

echo 正在推送到 https://github.com/kkk0-inTheProgramArea/SHAP_grade ...
echo （若弹出浏览器，请登录并授权 GitHub）
echo.

"%GITEXE%" push -u origin main

if errorlevel 1 (
  echo.
  echo [!] 推送未成功，请看一下上面的提示：
  echo     1. 提示要登录 —— 在弹出浏览器里登录 GitHub 后，重新双击本文件
  echo     2. 提示仓库不存在 —— 确认 https://github.com/kkk0-inTheProgramArea/SHAP_grade 已建好
  echo     3. 提示网络错误 —— 换个网络环境再试
) else (
  echo.
  echo [OK] 推送成功！打开下面地址就能看到代码：
  echo      https://github.com/kkk0-inTheProgramArea/SHAP_grade
)
echo.
pause
