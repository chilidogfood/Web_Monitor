FROM python:3.9-slim

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ .

# Create volume mount points
VOLUME ["/app/config", "/app/logs"]

# Run the monitor
CMD ["python", "web_monitor.py"]