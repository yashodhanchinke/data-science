@echo off

cd /d "C:\Users\Yash\Desktop\Data Science"

echo Starting Git Auto-Backup Watcher...
start "Git Auto-Backup Watcher" cmd /k python tools\git_watcher.py

echo Starting Jupyter...
jupyter notebook

pause