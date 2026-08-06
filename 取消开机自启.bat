@echo off
%SystemRoot%\System32\chcp.com 936 >nul 2>nul
setlocal
title 取消开机自启动
cd /d "%~dp0"

echo ============================================
echo   取消开机自启动
echo ============================================
echo.

set "VBS_FILE=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\caimogu_signin.vbs"

if exist "%VBS_FILE%" (
    del "%VBS_FILE%"
    if exist "%VBS_FILE%" (
        echo [失败] 删除失败，请手动检查权限
    ) else (
        echo [成功] 已取消开机自启动！
        echo.
        echo 下次开机将不再自动运行签到
        echo 如需重新开启，请运行「设置开机自启.bat」
    )
) else (
    echo [提示] 未找到开机自启动项，可能已经取消过了
)

echo.
pause
endlocal
