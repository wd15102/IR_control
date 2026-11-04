@echo off
cd /d %~dp0
set GIT_SSH_COMMAND=ssh -o StrictHostKeyChecking=no -o ProxyCommand="C:/PROGRA~1/Git/mingw64/bin/connect.exe -H 127.0.0.1:10808 %%h %%p"
git push -u origin master > push.log 2>&1
set code=%ERRORLEVEL%
echo EXITCODE=%code%
type push.log
