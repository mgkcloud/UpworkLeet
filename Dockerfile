# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for Playwright and monitoring
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and browsers
RUN playwright install firefox
RUN playwright install-deps

# Copy application code
COPY . .

# Create directories for data persistence
RUN mkdir -p /app/files/job_tracking /app/files/cache /app/logs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV UPWORK_SEARCH_QUERY="AI agent Developer"
ENV FREELANCER_PROFILE_PATH="/app/files/profile.md"
ENV POLLING_INTERVAL=480
ENV MAX_JOBS_PER_POLL=10
ENV JOB_RETENTION_DAYS=30
ENV HIGH_VALUE_THRESHOLD=7.0
ENV WEBHOOK_URL="https://n8n.fy.studio/webhook-test/a9a844f3-d651-4413-8bf3-820c6877b153"

# Create volume mount points
VOLUME ["/app/files/job_tracking", "/app/files/cache", "/app/logs"]

# Expose health check port
EXPOSE 8000

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the continuous poller
CMD ["python", "-u", "src/continuous_poller.py"]
