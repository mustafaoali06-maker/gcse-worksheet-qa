# Backend Files Index

## Core Implementation

### `main.py` (921 lines, 36KB)
The complete FastAPI backend. This is the only Python file needed to run the server.

**Key Sections:**
- Lines 1-38: Imports and configuration
- Lines 40-49: Constants (ANSWER_LINE, ANSWER_UNDERSCORES, LABEL_CM, TEXT_CM)
- Lines 51-69: FastAPI app setup with CORS and static files
- Lines 71-221: Helper functions (19 total)
- Lines 224-343: AI functions (improve_worksheet, generate_markscheme, run_agent)
- Lines 345-430: Agent pipeline functions
- Lines 445-630: Document building functions
- Lines 767-830: SSE stream generator
- Lines 832-912: API endpoints
- Lines 914-921: Entry point

**Functions by Category:**

**Text Processing (9 functions):**
- `extract_docx()` - Read DOCX files
- `clean_text()` - Remove markdown
- `add_answer_lines()` - Add underscore lines
- `extract_total()` - Get marks total
- `fractional_marks_present()` - Check for decimals
- `keyword_overlap()` - Calculate similarity
- `extract_question_numbers()` - Parse IDs
- `strip_answer_lines()` - Remove lines
- `detect_question_structure()` - Parse hierarchy

**AI Functions (7 functions):**
- `improve_worksheet()` - GPT enhancement
- `generate_markscheme()` - GPT generation
- `run_agent()` - Execute agent
- `run_full_revision_via_agents()` - Run all 5
- `parse_revised_output()` - Extract results
- `run_formatting_agent()` - Get JSON spec
- `read_spec_text()` - Combine specs

**Document Building (2 functions):**
- `build_formatted_docx()` - Create exam worksheet
- `build_markscheme_docx()` - Create mark scheme

**Utility (1 function):**
- `_set_run_font()` - DOCX formatting

**API Endpoints (6 routes):**
- `POST /api/process` - Full validation pipeline
- `POST /api/export/worksheet` - Export to DOCX
- `POST /api/export/markscheme` - Export to DOCX
- `POST /api/chat` - Interactive chat
- `GET /` - Serve frontend
- `GET /static/*` - Serve assets

---

## Documentation

### `README.md` (126 lines)
Complete API documentation covering:
- Setup and installation
- Running the server
- Detailed endpoint descriptions with examples
- Request/response formats
- Key features
- Architecture overview

### `QUICKSTART.md` (90 lines)
Quick start guide with:
- 30-second setup steps
- API testing examples
- Environment variables
- File structure
- Common issues and solutions
- Development vs production

### `BACKEND_SUMMARY.md` (240 lines)
Comprehensive implementation details:
- Overview and file summary
- Complete function reference
- Agent integration details
- Code quality notes
- Testing checklist
- Production deployment considerations

---

## Configuration

### `requirements.txt` (5 packages)
All Python dependencies:
```
fastapi==0.104.1
uvicorn==0.24.0
python-docx==0.8.11
openai==1.3.0
python-multipart==0.0.6
```

---

## Quick Navigation

**Want to...**

| Task | File | Location |
|------|------|----------|
| Run the server | main.py | Entire file |
| Understand API | README.md | All sections |
| Get started fast | QUICKSTART.md | All sections |
| See implementation details | BACKEND_SUMMARY.md | All sections |
| Deploy to production | QUICKSTART.md | "Development vs Production" |
| Add logging | main.py | Lines 18-22 (imports) |
| Change port | main.py | Line 921 (port=8000) |
| Use specific function | main.py | See "Functions by Category" above |
| Check API docs | main.py | Run server, visit /docs |

---

## File Statistics

```
total files: 5
total lines: ~1,500
total size: ~50KB

Breakdown:
  - main.py:                921 lines (36KB)
  - BACKEND_SUMMARY.md:     240 lines
  - README.md:              126 lines
  - QUICKSTART.md:           90 lines
  - requirements.txt:         5 lines
  - INDEX.md (this file):    120 lines
```

---

## Import Structure

```
main.py imports from:
  ├── Standard library: os, re, json, sys, io, typing, pathlib
  ├── FastAPI: fastapi, fastapi.responses, fastapi.middleware
  ├── python-docx: docx, docx.shared, docx.enum, docx.oxml
  ├── openai: OpenAI
  └── agents.py: All 6 agent prompts
```

---

## How Everything Works Together

```
User makes request
    ↓
FastAPI receives request
    ↓
Appropriate endpoint handler called
    ↓
Helper functions process data
    ↓
AI functions call OpenAI API
    ↓
Document building functions create DOCX
    ↓
Response sent back to user
```

### Example: POST /api/process

```
1. Receive: worksheet.docx, markscheme.docx, spec.txt
   ↓
2. extract_docx() → text strings
   ↓
3. improve_worksheet() → GPT enhancement
   ↓
4. generate_markscheme() → GPT generation
   ↓
5. run_agent(AGENT_1) → Validation report 1
6. run_agent(AGENT_2) → Validation report 2
7. run_agent(AGENT_3) → Validation report 3
8. run_agent(AGENT_4) → Validation report 4
   ↓ (with SSE streaming updates)
9. run_agent(AGENT_5) → Final revision
   ↓
10. parse_revised_output() → Separate texts
    ↓
11. Stream final event with results
```

---

## Constants Reference

### ANSWER_LINE
- Value: 58 underscores: `__________________________________________________________`
- Used: Creating answer spaces in worksheet

### ANSWER_UNDERSCORES
```python
{
  0: 62,  # Main question level
  1: 59,  # Sub-part level (a), (b)
  2: 55   # Roman numeral level (i), (ii)
}
```

### LABEL_CM
```python
[
  0.0,   # Main question: no indent
  0.63,  # Sub-part: 0.63cm indent
  1.27   # Roman: 1.27cm indent
]
```

### TEXT_CM
```python
[
  0.7,   # Main question text starts at 0.7cm
  1.27,  # Sub-part text starts at 1.27cm
  1.90   # Roman text starts at 1.90cm
]
```

---

## Deployment Checklist

- [ ] Install dependencies: `pip install -r requirements.txt`
- [ ] Set environment: `export OPENAI_API_KEY="sk-..."`
- [ ] Test syntax: `python3 -m ast main.py`
- [ ] Start server: `python main.py`
- [ ] Check docs: Open `http://localhost:8000/docs`
- [ ] Test endpoint: `curl http://localhost:8000/api/process`
- [ ] Configure CORS: Edit line 58-64 in main.py
- [ ] Set up logging: Add logging configuration
- [ ] Configure database: Add data persistence if needed
- [ ] Deploy: Use Gunicorn with Nginx reverse proxy

---

## Support & Troubleshooting

**See QUICKSTART.md for:**
- Common issues
- Quick fixes
- Testing examples

**See README.md for:**
- Complete API reference
- Endpoint descriptions
- Request/response formats

**See BACKEND_SUMMARY.md for:**
- Implementation details
- Architecture overview
- Production considerations

---

## Version Information

- Created: 2026-04-06
- Python Version: 3.8+
- Framework: FastAPI 0.104.1
- ASGI Server: Uvicorn 0.24.0
- Document Library: python-docx 0.8.11
- AI Provider: OpenAI (gpt-4o-mini)

---

**Start Here:** Read QUICKSTART.md for a 30-second setup guide.
**Full Documentation:** See README.md for complete API reference.
**Implementation Details:** See BACKEND_SUMMARY.md for architecture.
