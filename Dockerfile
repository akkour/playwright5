FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy
RUN apt-get update && apt-get install -y docker.io docker-compose && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/data /app/logs


# Expose port
EXPOSE 11235

# Start command
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${WORKER_PORT:-11235} --workers ${UVICORN_WORKERS:-2}"]
