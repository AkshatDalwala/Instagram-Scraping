@echo off
title Instagram Scraper Pro
echo.
echo  ============================================
echo   Instagram Scraper Pro
echo   FastAPI Backend  +  Streamlit Frontend
echo  ============================================
echo.

echo [1/2] Starting FastAPI backend on http://localhost:8000 ...
start /B python -m uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload

:: Give the backend a moment to boot
timeout /t 3 /nobreak > nul

echo [2/2] Starting Streamlit frontend on http://localhost:8501 ...
streamlit run app.py
