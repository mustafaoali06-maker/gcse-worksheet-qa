# Quick Start Guide - FastAPI Backend

## 30-Second Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your OpenAI API key
export OPENAI_API_KEY="sk-your-key-here"

# 3. Run the server
python main.py
```

Server starts at `http://localhost:8000`

## Test the API

### Test 1: Check API is running
```bash
curl http://localhost:8000/docs
```
Opens interactive API documentation.

### Test 2: Export a worksheet (POST)
```bash
curl -X POST http://localhost:8000/api/export/worksheet \
  -H "Content-Type: application/json" \
  -d '{"text": "1 State two uses of ultrasound. (2)"}'
```

Returns a DOCX file for download.

### Test 3: Process with SSE stream
```bash
curl -X POST http://localhost:8000/api/process \
  -F "worksheet=@worksheet.docx" \
  -F "pasted_spec=@spec.txt"
```

Returns real-time progress updates via Server-Sent Events.

## API Quick Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Frontend HTML |
| `/static/*` | GET | Static files |
| `/api/process` | POST | Full validation pipeline (SSE stream) |
| `/api/export/worksheet` | POST | Convert text to DOCX worksheet |
| `/api/export/markscheme` | POST | Convert text to DOCX mark scheme |
| `/api/chat` | POST | Interactive revision chat |

## Environment Variables

```bash
OPENAI_API_KEY   # Required: Your OpenAI API key
```

## File Structure

```
backend/
├── main.py                 # 921 lines - complete backend
├── requirements.txt        # Python dependencies
├── README.md              # Full API documentation
└── QUICKSTART.md          # This file
```

## Key Features

✓ **Fast:** Async/await throughout for high concurrency
✓ **Streaming:** Real-time progress via Server-Sent Events
✓ **Complete:** All app.py logic included directly
✓ **Production:** Error handling, CORS, static files
✓ **Documented:** Docstrings, type hints, comments

## Common Issues

**Issue: `ModuleNotFoundError: No module named 'fastapi'`**
→ Run: `pip install -r requirements.txt`

**Issue: `Error code: 401, message: 'Incorrect API key'`**
→ Check: `echo $OPENAI_API_KEY` shows your key

**Issue: Port 8000 already in use**
→ Run: `python -m uvicorn main:app --port 8001`

**Issue: Frontend not found**
→ The frontend files should be in `../frontend/`
→ The GET `/` endpoint will show a message if missing

## Development vs Production

### Development
```bash
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
Auto-reloads on file changes.

### Production
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```
Use multiple workers and consider adding:
- Gunicorn wrapper
- Nginx reverse proxy
- SSL/TLS with certificates
- Rate limiting
- Request validation
- Proper logging

## Architecture Overview

```
User Request
    ↓
FastAPI Endpoint
    ↓
Helper Functions (text processing)
    ↓
OpenAI Client (gpt-4o-mini)
    ↓
Agent Pipeline (1-5)
    ↓
python-docx (document building)
    ↓
Response (DOCX file or JSON)
```

## Code Flow - `/api/process`

1. **Read Files** → `extract_docx()`
2. **Enhance WS** → `improve_worksheet()`
3. **Generate MS** → `generate_markscheme()`
4. **Agent 1-4** → `run_agent()` (parallel validation)
5. **Agent 5** → `run_full_revision_via_agents()`
6. **Parse Output** → `parse_revised_output()`
7. **Stream Progress** → SSE events via `process_stream_generator()`

## Advanced: Calling Functions Directly

```python
from backend.main import improve_worksheet, detect_question_structure

# Use any function independently
structure = detect_question_structure(worksheet_text)
improved = improve_worksheet(worksheet_text)
```

## Monitoring

Add logging to `main.py`:
```python
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.post("/api/process")
async def process_worksheet(...):
    logger.info("Processing worksheet...")
```

## Next Steps

1. Read `README.md` for detailed API documentation
2. Check `main.py` for function signatures and docstrings
3. Test endpoints using `/docs` interactive UI
4. Read `BACKEND_SUMMARY.md` for implementation details

---

**Need Help?**
- View API docs: http://localhost:8000/docs
- Check function signatures: `grep "^def \|^async def" main.py`
- Review docstrings: `grep -A 2 "def \|async def" main.py`
