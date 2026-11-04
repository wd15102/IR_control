@echo off
chcp 65001 >nul
cd /d %~dp0
python ir_remote.py
pause
