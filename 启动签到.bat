@echo off
%SystemRoot%\System32\chcp.com 936 >nul 2>nul
setlocal
set "PYTHONIOENCODING=gb18030"
title 采蘑菇自动签到机
cd /d "%~dp0"

set "LOG_FILE=%~dp0run_log.txt"
set "CMD_OUT=%~dp0last_command_output.txt"
echo Run started at %date% %time% > "%LOG_FILE%"

:MENU
echo ============================================
echo   采蘑菇论坛自动签到机 （源码版）
echo ============================================
echo.
echo  本版本需要已安装 Python 环境与 Playwright
echo.
echo  请选择操作：
echo.
echo    1. 立即运行自动签到
echo    2. 配置登录（首次使用必做）
echo    3. 测试评论生成效果
echo    4. 查看签到日志
echo    5. 退出
echo.
set /p choice=请输入数字 1-5:

if "%choice%"=="1" goto RUN_SIGNIN
if "%choice%"=="2" goto SETUP_LOGIN
if "%choice%"=="3" goto TEST_COMMENT
if "%choice%"=="4" goto SHOW_LOG
if "%choice%"=="5" goto CLEAN_EXIT

echo 无效的选择，请重新输入
echo.
goto MENU

:RUN_SIGNIN
echo.
echo 正在运行自动签到...
echo 运行过程中请勿关闭此窗口
python "%~dp0caimogu_signin.py"
if exist "%~dp0signin_log.txt" copy /y "%~dp0signin_log.txt" "%CMD_OUT%" >nul
if exist "%CMD_OUT%" type "%CMD_OUT%" >> "%LOG_FILE%"
echo 退出码: %errorlevel% >> "%LOG_FILE%"
echo.
echo ============================================
echo  签到完成！
echo ============================================
goto END

:SETUP_LOGIN
echo.
echo 正在启动登录配置...
echo 浏览器窗口将会打开，请在浏览器中登录采蘑菇论坛
echo 登录成功后，回到此窗口按回车键保存
python "%~dp0caimogu_signin.py" --login
if exist "%~dp0signin_log.txt" copy /y "%~dp0signin_log.txt" "%CMD_OUT%" >nul
echo 退出码: %errorlevel% >> "%LOG_FILE%"
goto END

:TEST_COMMENT
echo.
echo 正在测试评论生成...
echo （仅预览评论，不会实际发帖）
python "%~dp0caimogu_signin.py" --test
if exist "%~dp0signin_log.txt" copy /y "%~dp0signin_log.txt" "%CMD_OUT%" >nul
if exist "%CMD_OUT%" type "%CMD_OUT%" >> "%LOG_FILE%"
echo 退出码: %errorlevel% >> "%LOG_FILE%"
goto END

:SHOW_LOG
echo.
echo ============================================
echo  签到日志
echo ============================================
echo.
set "SHOW_LOG_FILE=%~dp0signin_log.txt"
if not exist "%SHOW_LOG_FILE%" goto NO_SIGNIN_LOG
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -LiteralPath $env:SHOW_LOG_FILE -Encoding UTF8"
goto SHOW_LOG_DONE

:NO_SIGNIN_LOG
echo 暂无签到记录，请先运行一次签到

:SHOW_LOG_DONE
echo.
pause
cls
goto MENU

:END
echo.
echo 窗口将保持打开。如果遇到问题，请将以下文件发给开发者：
echo   %LOG_FILE%
echo   %CMD_OUT%
echo.
pause
goto CLEAN_EXIT

:CLEAN_EXIT
endlocal
