@echo off
rem Dev launcher: put "src" on the module path, then run the CLI.
rem Usage:  campusnet.cmd status
rem         campusnet.cmd settings
rem Not needed after Phase 7 packaging (single exe).
setlocal
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
python -m campusnet %*
exit /b %ERRORLEVEL%
