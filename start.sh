#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
#  GCSE Worksheet QA Studio — start script (macOS / Linux)
# ─────────────────────────────────────────────────────────────────
set -e

# ── 1. Require OPENAI_API_KEY ──────────────────────────────────────
if [ -z "$OPENAI_API_KEY" ]; then
  echo ""
  echo "  ⚠️  OPENAI_API_KEY is not set."
  echo "  Run:  export OPENAI_API_KEY=sk-..."
  echo "  Then: ./start.sh"
  echo ""
  exit 1
fi

# ── 2. Install Python dependencies ────────────────────────────────
echo "📦 Installing Python dependencies..."
pip install -r backend/requirements.txt --quiet

# ── 3. Start FastAPI server ────────────────────────────────────────
echo ""
echo "🚀 Starting GCSE Worksheet QA Studio..."
echo "   Open http://localhost:8000 in your browser"
echo ""

cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
