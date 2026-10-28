@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONPATH="
echo [1/3] Python version:
python --version
if errorlevel 1 (
  echo Python not found on PATH.
  goto :end
)
if not exist ".demo-venv\Scripts\python.exe" (
  echo [2/3] Creating .demo-venv ...
  python -m venv .demo-venv
  if errorlevel 1 goto :fail
) else (
  echo [2/3] .demo-venv already exists, reusing it.
)
echo [3/3] Installing requirements-demo.txt ...
".demo-venv\Scripts\python.exe" -m pip install --upgrade pip
".demo-venv\Scripts\python.exe" -m pip install -r requirements-demo.txt
if errorlevel 1 (
  echo.
  echo Pinned versions not available for this Python, installing latest compatible versions ...
  ".demo-venv\Scripts\python.exe" -m pip install --only-binary=pydantic-core,numpy,scipy,scikit-learn fastapi uvicorn pydantic jieba httpx numpy scikit-learn
  if errorlevel 1 goto :fail
)
echo.
echo Verifying imports ...
".demo-venv\Scripts\python.exe" -c "import fastapi, pydantic_core, sklearn, jieba, numpy; import demo_api; print('OK - environment ready')"
if errorlevel 1 goto :fail
echo.
echo SETUP DONE. Double-click start_demo.bat to run the app.
goto :end
:fail
echo.
echo SETUP FAILED - please screenshot this window.
:end
pause
