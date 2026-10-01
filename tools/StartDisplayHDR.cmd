@echo off
pushd "%~dp0"
python displayhdr_server.py %*
set "displayhdrExitCode=%ERRORLEVEL%"
if not "%displayhdrExitCode%"=="0" pause
popd
exit /b %displayhdrExitCode%
