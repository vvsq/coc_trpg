@echo off
REM ============================================================
REM  Phase 6.1 one-click launcher (goal section 7 / decision D6)
REM
REM  This file is intentionally ASCII-only, and it does NOT call
REM  "chcp". Reason (measured bug, not superstition):
REM  cmd.exe mis-parses a UTF-8 batch file after "chcp 65001" when
REM  the console did not start as UTF-8 -- which is exactly the case
REM  when a user double-clicks it (fresh console = CP936). The tail
REM  of a Chinese comment line then gets executed as a command (cmd prints
REM  an "is not recognized as an internal or external command" error).
REM  Same file ran fine from a CP65001 console, so it is
REM  non-deterministic. All Chinese UX text therefore lives in
REM  scripts\bootstrap.py, which also forces the console to UTF-8.
REM
REM  Usage:
REM    start.bat              start on port 8000, open the browser
REM    start.bat 8080         use another port
REM    start.bat --rebuild    force rebuild the frontend bundle
REM    start.bat --check      self-check only, do not start server
REM ============================================================

cd /d "%~dp0"
setlocal
title COC TRPG Assistant - Quick Start

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)
if not defined PY goto :no_python

%PY% -X utf8 "%~dp0scripts\bootstrap.py" %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
    echo.
    echo [X] Startup failed with exit code %CODE%.
    echo     Read the messages above, or the deployment guide under docs\.
    echo.
    pause
)
exit /b %CODE%

:no_python
echo.
echo [X] Python not found.
echo     Install Python 3.11 or newer from https://www.python.org/downloads/
echo     During setup, remember to check "Add python.exe to PATH".
echo.
pause
exit /b 1
