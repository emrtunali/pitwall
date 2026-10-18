@echo off
rem Double-click to open Pitwall on Windows.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo First run: setting up Pitwall...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --quiet --upgrade pip
  .venv\Scripts\pip install --quiet -e .
)
.venv\Scripts\python -m pitwall serve
pause
