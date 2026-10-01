@echo off
pushd "%~dp0"
"runtime\python.exe" -X utf8 displayhdr_remote.py %*
set "displayhdrExitCode=%ERRORLEVEL%"
if not "%displayhdrExitCode%"=="0" pause
popd
exit /b %displayhdrExitCode%
