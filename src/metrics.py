"""Prometheus metrics for monitoring the Upwork job poller"""
from prometheus_client import Counter, Gauge, Histogram, start_http_server
import time

# Metrics definitions
JOBS_SCRAPED = Counter(
    'upwork_jobs_scraped_total',
    'Total number of jobs scraped from Upwork'
)

JOBS_PROCESSED = Counter(
    'upwork_jobs_processed_total',
    'Total number of jobs processed'
)

API_REQUESTS = Counter(
    'upwork_api_requests_total',
    'Total number of API requests made',
    ['api_type']  # gemini, webhook
)

API_ERRORS = Counter(
    'upwork_api_errors_total',
    'Total number of API errors encountered',
    ['api_type', 'error_type']
)

API_LATENCY = Histogram(
    'upwork_api_latency_seconds',
    'API request latency in seconds',
    ['api_type'],
    buckets=(1, 2, 5, 10, 20, 30, 60)
)

MEMORY_USAGE = Gauge(
    'upwork_memory_usage_bytes',
    'Memory usage in bytes'
)

JOBS_IN_QUEUE = Gauge(
    'upwork_jobs_in_queue',
    'Number of jobs waiting to be processed'
)

HIGH_VALUE_JOBS = Counter(
    'upwork_high_value_jobs_total',
    'Number of high-value jobs identified'
)

def start_metrics_server(port=8001):
    """Start the Prometheus metrics server"""
    try:
        start_http_server(port)
        return True
    except Exception as e:
        print(f"Failed to start metrics server: {e}")
        return False

class MetricsTimer:
    """Context manager for timing operations and recording metrics"""
    def __init__(self, metric, labels=None):
        self.metric = metric
        self.labels = labels or {}
        
    def __enter__(self):
        self.start = time.time()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start
        self.metric.labels(**self.labels).observe(duration)
