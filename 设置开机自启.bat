@echo off
%SystemRoot%\System32\chcp.com 936 >nul 2>nul
setlocal enabledelayedexpansion
title 设置开机自启动
cd /d "%~dp0"

echo ============================================
echo   设置开机自启动
echo ============================================
echo.
echo  此操作会将签到程序添加到 Windows 开机启动项
echo  每次开机后会自动在后台运行签到
echo.

REM === 查找 pythonw.exe 完整路径 ===
set "PYTHONW_PATH="

REM 1. 从 PATH 中查找
for /f "delims=" %%i in ('where pythonw 2^>nul') do (
    set "PYTHONW_PATH=%%i"
    goto FOUND_PYTHONW
)

REM 2. 检查 TRAE 环境路径
set "TRAE_PY=%APPDATA%\TRAE SOLO CN\ModularData\ai-agent\vm\tools\python\pythonw.exe"
if exist "%TRAE_PY%" (
    set "PYTHONW_PATH=%TRAE_PY%"
    goto FOUND_PYTHONW
)

REM 3. 检查常见安装路径
for %%V in (313 312 311 310 39 38) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\pythonw.exe" (
        set "PYTHONW_PATH=%LOCALAPPDATA%\Programs\Python\Python%%V\pythonw.exe"
        goto FOUND_PYTHONW
    )
    if exist "C:\Python%%V\pythonw.exe" (
        set "PYTHONW_PATH=C:\Python%%V\pythonw.exe"
        goto FOUND_PYTHONW
    )
)

echo [失败] 未找到 pythonw.exe
echo   请确保已安装 Python 并添加到系统 PATH
echo   或手动修改本文件中的 PYTHONW_PATH 变量
echo.
pause
exit /b 1

:FOUND_PYTHONW
echo  Python 路径: %PYTHONW_PATH%
echo  脚本路径: %~dp0caimogu_signin.py
echo.

set "VBS_FILE=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\caimogu_signin.vbs"
set "SCRIPT_PATH=%~dp0caimogu_signin.py"

REM === 生成 VBS 文件（使用 pythonw 完整路径，避免开机时 PATH 缺失）===
echo Set WshShell = CreateObject("WScript.Shell") > "%VBS_FILE%"
echo WshShell.CurrentDirectory = "%~dp0" >> "%VBS_FILE%"
echo WshShell.Run """%PYTHONW_PATH%"" ""%SCRIPT_PATH%""", 0, False >> "%VBS_FILE%"

if exist "%VBS_FILE%" (
    echo [成功] 已添加开机自启动！
    echo.
    echo 自启动文件位置：
    echo   %VBS_FILE%
    echo.
    echo 下次开机时将自动运行签到
    echo 如需取消，请运行「取消开机自启.bat」
) else (
    echo [失败] 设置失败，请手动检查权限
)

echo.
pause
endlocal
