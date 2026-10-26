@echo off
REM 天健湖 Windows 入口。用法：
REM   scripts\task.cmd setup
REM   scripts\task.cmd start
REM   scripts\task.cmd dev
REM   scripts\task.cmd doctor
setlocal
set "ROOT=%~dp0.."
python "%ROOT%\scripts\task.py" %*
if errorlevel 1 (
  echo.
  echo 如果提示找不到 python，请安装 Python 3.11+ 并勾选 "Add python.exe to PATH"
  echo 或用 py 启动器：py -3 "%ROOT%\scripts\task.py" %*
)
endlocal
