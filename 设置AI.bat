@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& python '%~dp0caimogu_signin.py' --set-ai"
pause
