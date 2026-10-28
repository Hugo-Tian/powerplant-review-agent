@echo off
setlocal
cd /d "%~dp0"
if exist "llm.env.bat" call "llm.env.bat"
if defined LLM_PROVIDER (echo LLM: %LLM_PROVIDER% %LLM_MODEL%) else (echo LLM: disabled, using rule + TF-IDF only)
if not exist "frontend-vue\dist\index.html" (
  echo Vue build not found. Run npm ci and npm run build in frontend-vue first.
  pause
  exit /b 1
)
set "PY="
rem Prefer the openJiuwen environment (setup_openjiuwen.bat); fall back to .demo-venv.
if exist ".jiuwen-venv\Scripts\python.exe" (
  set "PY=.jiuwen-venv\Scripts\python.exe"
  echo Review agent engine: openJiuwen ReActAgent
) else if exist ".demo-venv\Scripts\python.exe" (
  set "PY=.demo-venv\Scripts\python.exe"
  echo Review agent engine: built-in ^(run setup_openjiuwen.bat to use openJiuwen^)
)
if defined PY (
  set "PYTHONPATH="
  echo Open http://127.0.0.1:8000 after startup. Press Ctrl+C to stop.
  "%PY%" -W ignore -m uvicorn demo_api:app --host 127.0.0.1 --port 8000
) else (
  if exist ".local-deps" set "PYTHONPATH=%~dp0.local-deps"
  echo Open http://127.0.0.1:8000 after startup. Press Ctrl+C to stop.
  python -m uvicorn demo_api:app --host 127.0.0.1 --port 8000
)
if errorlevel 1 (
  echo Startup failed. See README.md for dependency setup and port configuration.
  pause
)
endlocal
