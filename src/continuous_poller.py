import os
import time
import signal
import sys
import json
import requests
import psutil
from datetime import datetime
from src.job_tracker import JobTracker
from src.metrics import (
    start_metrics_server,
    JOBS_SCRAPED,
    JOBS_PROCESSED,
    API_REQUESTS,
    API_ERRORS,
    API_LATENCY,
    MEMORY_USAGE,
    JOBS_IN_QUEUE,
    HIGH_VALUE_JOBS,
    MetricsTimer
)
from src.circuit_breaker import with_circuit_breaker
from src.utils import (
    scrape_upwork_data,
    score_scaped_jobs,
    generate_cover_letter,
    generate_interview_script_content,
    setup_logger,
    truncate_content
)
from src.health_check import start_health_check_server
from typing import Optional
import logging

class CustomJsonFormatter(logging.Formatter):
    def format(self, record):
        # Get the original format
        record.message = record.getMessage()
        if hasattr(record, 'extra'):
            extra_str = f', "extra": {json.dumps(record.extra)}'
        else:
            extra_str = ''
            
        # Format the timestamp
        if self.datefmt:
            record.asctime = self.formatTime(record, self.datefmt)
            
        # Create the JSON structure
        return ('{{'
                f'"timestamp": "{record.asctime}.{int(record.msecs):03d}", '
                f'"level": "{record.levelname}", '
                f'"logger": "{record.name}", '
                f'"message": "{record.message}"{extra_str}'
                '}}')

# Setup structured logging
logger = setup_logger('upwork_poller')
file_handler = logging.FileHandler('upwork_poller.log')
formatter = CustomJsonFormatter(datefmt='%Y-%m-%d %H:%M:%S')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Start metrics server
start_metrics_server()

class UpworkPoller:
    def __init__(
        self,
        search_query: str,
        profile_path: str,
        webhook_url: str,
        poll_interval: int = 480,  # 8 minutes
        max_jobs_per_poll: int = 10,
        job_retention_days: int = 30,
        high_value_threshold: float = 7.0
    ):
        self.search_query = search_query
        self.poll_interval = poll_interval
        self.max_jobs_per_poll = max_jobs_per_poll
        self.job_retention_days = job_retention_days
        self.webhook_url = webhook_url
        self.high_value_threshold = high_value_threshold
        self.job_tracker = JobTracker()
        self.running = False
        self.last_cleanup = datetime.now()
        
        # Load freelancer profile
        try:
            with open(profile_path, 'r') as f:
                self.profile = f.read()
        except Exception as e:
            logger.error(f"Failed to load profile from {profile_path}: {truncate_content(str(e))}")
            raise
            
        # Start health check server
        self.health_server = start_health_check_server()
            
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully"""
        if self.running:
            logger.info("Stopping poller...")
            self.running = False
            if hasattr(self, 'health_server'):
                self.health_server.shutdown()
            sys.exit(0)

    @with_circuit_breaker("webhook")
    def _send_webhook_notification(self, job_data: dict, processed_data: dict):
        """Send webhook notification for high-value jobs"""
        try:
            with MetricsTimer(API_LATENCY, {"api_type": "webhook"}):
                API_REQUESTS.labels(api_type="webhook").inc()
                payload = {
                "timestamp": datetime.now().isoformat(),
                "job_details": {
                    "id": job_data.get("job_id"),
                    "title": job_data.get("title"),
                    "description": job_data.get("description"),
                    "job_type": job_data.get("job_type"),
                    "experience_level": job_data.get("experience_level"),
                    "duration": job_data.get("duration"),
                    "rate": job_data.get("rate"),
                    "client_information": job_data.get("client_infomation"),
                    "score": job_data.get("score"),
                    "url": job_data.get("url")
                },
                "generated_content": {
                    "cover_letter": processed_data.get("cover_letter"),
                    "interview_script": processed_data.get("interview_script")
                },
                "metadata": {
                    "processed_at": processed_data.get("processed_at"),
                    "search_query": self.search_query,
                    "match_score": job_data.get("score")
                }
            }
            
                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=10
                )
                response.raise_for_status()
                logger.debug(f"Webhook sent for job {job_data.get('job_id')}")
            
        except requests.exceptions.RequestException as e:
            API_ERRORS.labels(api_type="webhook", error_type=type(e).__name__).inc()
            logger.error(f"Webhook failed: {truncate_content(str(e))}", 
                        extra={"error_type": type(e).__name__, "job_id": job_data.get("job_id")})
            raise

    def _update_metrics(self):
        """Update system metrics"""
        try:
            process = psutil.Process()
            MEMORY_USAGE.set(process.memory_info().rss)
        except Exception as e:
            logger.warning(f"Failed to update metrics: {e}")

    def _process_job(self, job_id: str, job_data: dict) -> Optional[dict]:
        """Process a single job and return the result"""
        try:
            JOBS_PROCESSED.inc()
            # Generate cover letter
            cover_letter_response = generate_cover_letter(
                job_data["job_data"]["description"],
                self.profile
            )
            cover_letter = cover_letter_response.get("letter", "") if isinstance(cover_letter_response, dict) else str(cover_letter_response)
            
            # Generate interview script
            script_response = generate_interview_script_content(
                job_data["job_data"]["description"]
            )
            interview_script = script_response.get("script", "") if isinstance(script_response, dict) else str(script_response)
            
            result = {
                "job_id": job_id,
                "cover_letter": cover_letter,
                "interview_script": interview_script,
                "processed_at": datetime.now().isoformat()
            }
            
            # Send webhook notification for high-value jobs
            if job_data["job_data"].get("score", 0) >= self.high_value_threshold:
                HIGH_VALUE_JOBS.inc()
                self._send_webhook_notification(job_data["job_data"], result)
            
            # Mark job as processed
            self.job_tracker.mark_job_processed(job_id, result)
            logger.debug(f"Processed job {job_id}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to process job {job_id}: {truncate_content(str(e))}")
            return None

    def _cleanup_if_needed(self):
        """Perform periodic cleanup of old job data"""
        now = datetime.now()
        hours_since_cleanup = (now - self.last_cleanup).total_seconds() / 3600
        
        if hours_since_cleanup >= 24:  # Daily cleanup
            logger.debug("Running daily cleanup...")
            self.job_tracker.cleanup_old_jobs(self.job_retention_days)
            self.last_cleanup = now

    def run(self):
        """Run the continuous polling loop"""
        logger.info(f"Starting Upwork poller for query: {self.search_query}")
        self.running = True
        
        while self.running:
            try:
                # Update system metrics
                self._update_metrics()
                # Scrape latest jobs
                logger.debug("Polling for new jobs...")
                with MetricsTimer(API_LATENCY, {"api_type": "scraper"}):
                    jobs_df = scrape_upwork_data(
                        self.search_query,
                        self.max_jobs_per_poll
                    )
                    if not jobs_df.empty:
                        JOBS_SCRAPED.inc(len(jobs_df))
                
                if jobs_df.empty:
                    logger.debug("No new jobs found")
                    continue
                
                # Score jobs
                scored_jobs = score_scaped_jobs(jobs_df, self.profile)
                
                # Process new jobs
                for _, job in scored_jobs.iterrows():
                    job_id = job["job_id"] if "job_id" in job else job.name
                    
                    # Skip if already seen
                    if self.job_tracker.is_job_seen(job_id):
                        continue
                    
                    # Mark as seen and store job data
                    job_data = job.to_dict()
                    self.job_tracker.mark_job_seen(job_id, job_data)
                    
                # Process unprocessed jobs
                unprocessed = self.job_tracker.get_unprocessed_jobs()
                JOBS_IN_QUEUE.set(len(unprocessed))
                for job_id, job_data in unprocessed.items():
                    result = self._process_job(job_id, job_data)
                    if result:
                        self.job_tracker.mark_job_processed(job_id, result)
                
                # Cleanup old data if needed
                self._cleanup_if_needed()
                
                # Wait for next poll
                logger.debug(f"Sleeping for {self.poll_interval}s...")
                time.sleep(self.poll_interval)
                
            except Exception as e:
                logger.error(f"Poll failed: {truncate_content(str(e))}")
                # Add exponential backoff on errors
                time.sleep(min(300, self.poll_interval * 2))

def main():
    # Load environment variables or use defaults
    search_query = os.getenv("UPWORK_SEARCH_QUERY", "AI agent Developer")
    profile_path = os.getenv("FREELANCER_PROFILE_PATH", "./files/profile.md")
    poll_interval = int(os.getenv("POLLING_INTERVAL", "480"))
    max_jobs = int(os.getenv("MAX_JOBS_PER_POLL", "10"))
    retention_days = int(os.getenv("JOB_RETENTION_DAYS", "30"))
    webhook_url = os.getenv("WEBHOOK_URL", "https://n8n.fy.studio/webhook-test/a9a844f3-d651-4413-8bf3-820c6877b153")
    high_value_threshold = float(os.getenv("HIGH_VALUE_THRESHOLD", "7.0"))
    
    poller = UpworkPoller(
        search_query=search_query,
        profile_path=profile_path,
        webhook_url=webhook_url,
        poll_interval=poll_interval,
        max_jobs_per_poll=max_jobs,
        job_retention_days=retention_days,
        high_value_threshold=high_value_threshold
    )
    
    poller.run()

if __name__ == "__main__":
    main()
