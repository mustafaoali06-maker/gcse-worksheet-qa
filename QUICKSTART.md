# GCSE Worksheet QA Studio — Quick Start

## What changed
The app is now **React + FastAPI** (no more Streamlit). The UI exactly matches the Figma Make v3 dark navy design, with zero CSS fights.

---

## One-time setup

**Prerequisites:** Python 3.10+, pip

```bash
cd backend
pip install -r requirements.txt
```

---

## Running the app

### macOS / Linux
```bash
export OPENAI_API_KEY=sk-...YOUR_KEY...
./start.sh
```

### Windows
```bat
set OPENAI_API_KEY=sk-...YOUR_KEY...
start.bat
```

Then open **http://localhost:8000** in your browser.

---

## File structure

```
gcse_worksheets_system/
├── backend/
│   ├── main.py            ← FastAPI server (all logic)
│   └── requirements.txt   ← Python dependencies
├── frontend/
│   └── index.html         ← React app (single file, no build step)
├── agents.py              ← Agent prompts (unchanged)
├── start.sh               ← Mac/Linux launcher
└── start.bat              ← Windows launcher
```

---

## How it works

1. Backend starts on port 8000 and serves `frontend/index.html` at `/`
2. Browser loads the React app (React 18 + Tailwind via CDN — no npm needed)
3. Upload your worksheet `.docx`, optionally mark scheme + spec, hit **Run QA**
4. Watch the 8-step pipeline run in real time via server-sent events
5. Edit the worksheet/mark scheme text directly in the UI
6. Use the **AI Chat** to request changes (e.g. "Change Olivia to Mustafa")
7. Export to `.docx` using the export cards

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `OPENAI_API_KEY is not set` | Run `export OPENAI_API_KEY=sk-...` first |
| `ModuleNotFoundError` | Run `pip install -r backend/requirements.txt` |
| Page shows blank | Check browser console — CDN may be blocked (needs internet) |
| Port already in use | Change `--port 8000` to `--port 8080` in start script |
