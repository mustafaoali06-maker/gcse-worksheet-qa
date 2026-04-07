# GCSE Worksheet QA Studio - Backend

FastAPI backend for the GCSE Worksheet QA Studio application.

## Setup

### Prerequisites
- Python 3.8+
- OpenAI API key

### Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set environment variables:
```bash
export OPENAI_API_KEY="your-api-key-here"
```

## Running the Server

```bash
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Or without auto-reload:
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`
API documentation: `http://localhost:8000/docs`

## API Endpoints

### POST `/api/process`
Process a worksheet through the full validation pipeline.

**Parameters:**
- `worksheet` (file, required): DOCX worksheet file
- `markscheme` (file, optional): DOCX mark scheme file
- `spec_txt` (file, optional): Text specification file
- `spec_docx` (file, optional): DOCX specification file
- `pasted_spec` (string, optional): Pasted specification text

**Returns:** Server-Sent Events stream with JSON events
- `{"step": int, "label": str, "detail": str}` - Progress update
- `{"done": true, "worksheet": str, "markscheme": str}` - Final result

### POST `/api/export/worksheet`
Export worksheet text as a DOCX file.

**Body:**
```json
{"text": "worksheet text here"}
```

**Returns:** DOCX file (application/vnd.openxmlformats-officedocument.wordprocessingml.document)

### POST `/api/export/markscheme`
Export mark scheme text as a DOCX file.

**Body:**
```json
{"text": "mark scheme text here"}
```

**Returns:** DOCX file (application/vnd.openxmlformats-officedocument.wordprocessingml.document)

### POST `/api/chat`
Interactive chat endpoint for revisions.

**Body:**
```json
{
  "message": "user message",
  "worksheet": "current worksheet text",
  "markscheme": "current mark scheme text"
}
```

**Returns:**
```json
{
  "reply": "response text",
  "updated_worksheet": "updated worksheet or null",
  "updated_markscheme": "updated mark scheme or null"
}
```

### GET `/`
Serves the frontend HTML file.

### GET `/static/*`
Serves static files from the frontend directory.

## Key Features

- **Full Processing Pipeline**: 5-stage validation using AI agents
- **Document Processing**: Reads DOCX files, generates professional formatting
- **Streaming Responses**: Real-time progress updates via Server-Sent Events
- **CORS Support**: Allows requests from any origin
- **Professional Output**: Generates GCSE exam-standard documents

## Architecture

The backend includes:
- Helper functions for text extraction and processing
- AI-powered agents for validation (Agents 1-5)
- Document building using python-docx
- FastAPI endpoints for all operations
- Stream-based response handling for long-running operations

## Agent Validation

The pipeline runs 5 validation agents:
1. **Agent 1**: Command Word Alignment Validator
2. **Agent 2**: Structural Mark Scheme Validator
3. **Agent 3**: Cognitive Balance Evaluator
4. **Agent 4**: Topic Coverage Evaluator
5. **Agent 5**: Intelligent Revision Agent

Each agent provides structured feedback that guides revision improvements.
