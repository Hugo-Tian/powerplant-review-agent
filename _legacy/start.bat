@echo off
docker compose up -d
timeout /t 5 /nobreak
cd frontend
start cmd /k "npm run dev"
echo Frontend: http://localhost:5173
echo Backend:  http://localhost:8000/docs
pause
