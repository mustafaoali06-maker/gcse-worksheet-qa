@echo off
REM ─────────────────────────────────────────────────────────────────
REM  GCSE Worksheet QA Studio — start script (Windows)
REM ─────────────────────────────────────────────────────────────────

REM ── 1. Require OPENAI_API_KEY ──────────────────────────────────────
IF "%OPENAI_API_KEY%"=="" (
    echo.
    echo   WARNING: OPENAI_API_KEY is not set.
    echo   Run:  set OPENAI_API_KEY=sk-...
    echo   Then: start.bat
    echo.
    pause
    exit /b 1
)

REM ── 2. Install Python dependencies ────────────────────────────────
echo Installing Python dependencies...
pip install -r backend\requirements.txt --quiet

REM ── 3. Start FastAPI server ────────────────────────────────────────
echo.
echo Starting GCSE Worksheet QA Studio...
echo Open http://localhost:8000 in your browser
echo.

cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
