# Station 95 GroupMe Chatbot - Polling Mode
# Runs as a Docker container with cron scheduling

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including cron
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ /app/src/
COPY data/ /app/data/

# Create logs directory
RUN mkdir -p /app/logs /app/data

# Copy cron configuration
COPY docker/crontab /etc/cron.d/groupme-poller
RUN chmod 0644 /etc/cron.d/groupme-poller

# Apply cron job
RUN crontab /etc/cron.d/groupme-poller

# Create entrypoint script
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Environment variables (these should be overridden at runtime)
ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO

# Volume for persistent data (state file and logs)
VOLUME ["/app/data", "/app/logs"]

# Run entrypoint
ENTRYPOINT ["/entrypoint.sh"]

# Keep container running with cron in foreground
CMD ["cron", "-f"]
