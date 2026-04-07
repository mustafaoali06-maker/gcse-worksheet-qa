FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (Docker cache layer)
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy all project files
COPY . .

# Expose default port
EXPOSE 8000

# Run from backend directory so relative paths resolve correctly
WORKDIR /app/backend

CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
