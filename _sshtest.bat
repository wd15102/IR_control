@echo off
cd /d %~dp0
set GIT_SSH_COMMAND=ssh -o StrictHostKeyChecking=no -o ProxyCommand="C:/PROGRA~1/Git/mingw64/bin/connect.exe -H 127.0.0.1:10808 %%h %%p"
ssh -T -o StrictHostKeyChecking=no git@github.com 2>&1
echo EXITCODE=%ERRORLEVEL%
