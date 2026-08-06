@echo off
%SystemRoot%\System32\chcp.com 936 >nul 2>nul
setlocal
title 设置开机自启动
cd /d "%~dp0"

echo ============================================
echo   设置开机自启动
echo ============================================
echo.
echo  此操作会将签到程序添加到 Windows 开机启动项
echo  每次开机后会自动在后台运行签到
echo.

set "VBS_FILE=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\caimogu_signin.vbs"
set "SCRIPT_PATH=%~dp0caimogu_signin.py"

echo Set WshShell = CreateObject("WScript.Shell") > "%VBS_FILE%"
echo WshShell.CurrentDirectory = "%~dp0" >> "%VBS_FILE%"
echo WshShell.Run "pythonw ""%SCRIPT_PATH%""", 0, False >> "%VBS_FILE%"

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
