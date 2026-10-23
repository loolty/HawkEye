@echo off
REM Compatibility launcher: all startup logic lives in run.bat.
call "%~dp0run.bat" %*
exit /b %errorlevel%
