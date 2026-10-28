@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONPATH="
rem openJiuwen agent-core needs Python 3.11-3.13 (not 3.14). Uses the py launcher.
set "PYV="
for %%v in (3.12 3.13 3.11) do (
  if not defined PYV (
    py -%%v --version >nul 2>&1 && set "PYV=%%v"
  )
)
if not defined PYV (
  echo Python 3.11/3.12/3.13 not found. Install Python 3.12 from python.org, then run this again.
  goto :end
)
echo [1/3] Using Python %PYV%
if not exist ".jiuwen-venv\Scripts\python.exe" (
  echo [2/3] Creating .jiuwen-venv ...
  py -%PYV% -m venv .jiuwen-venv
  if errorlevel 1 goto :fail
) else (
  echo [2/3] .jiuwen-venv already exists, reusing it.
)
echo [3/3] Installing requirements-openjiuwen.txt (first time takes a few minutes) ...
".jiuwen-venv\Scripts\python.exe" -m pip install --upgrade pip
".jiuwen-venv\Scripts\python.exe" -m pip install -r requirements-openjiuwen.txt
if errorlevel 1 goto :fail
echo.
echo Verifying imports ...
".jiuwen-venv\Scripts\python.exe" -W ignore -c "import demo_api; from core import agent_openjiuwen as a; assert a.available(), a.import_error(); print('OK - openJiuwen engine ready')"
if errorlevel 1 goto :fail
echo.
echo SETUP DONE. start_demo.bat will now use the openJiuwen engine automatically.
goto :end
:fail
echo.
echo SETUP FAILED - please screenshot this window.
:end
pause
