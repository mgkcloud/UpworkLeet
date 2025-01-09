import os
import time
import signal
import sys
import json
import requests
import psutil
import logging
import google.generativeai as genai
from dotenv import load_dotenv
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
    scrape_job_questions,
    generate_question_answers,
    setup_logger,
    truncate_content
)
from src.health_check import start_health_check_server
from typing import Optional

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

# Setup structured logging first
logger = setup_logger('upwork_poller', level=logging.DEBUG)
file_handler = logging.FileHandler('upwork_poller.log')
formatter = CustomJsonFormatter(datefmt='%Y-%m-%d %H:%M:%S')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Load environment variables from .env file, overriding any existing values
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
logger.debug(f"Loading environment from: {env_path}")
load_dotenv(env_path, override=True)

# Debug: Print all environment variables
logger.debug("Environment variables:")
for key, value in os.environ.items():
    if key in ["WEBHOOK_URL", "POLLING_INTERVAL", "HIGH_VALUE_THRESHOLD"]:
        logger.debug(f"{key}={value}")

# Initialize Gemini API
api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
    raise ValueError("GOOGLE_API_KEY environment variable is required")
genai.configure(api_key=api_key)

# Start metrics server
start_metrics_server()

class UpworkPoller:
    def __init__(
        self,
        profile_path: str,
        webhook_url: str,
        search_config_path: str = "./files/search_config.json",
        poll_interval: int = 480,  # 8 minutes
        max_jobs_per_poll: int = 10,
        job_retention_days: int = 30,
        high_value_threshold: float = 7.0
    ):
        self.search_config_path = search_config_path
        self.current_search_index = 0
        self.search_configs = self._load_search_configs()
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

        # Load search configurations
        if not self.search_configs:
            raise ValueError("No search configurations found in config file")
            
        # Start health check server
        self.health_server = start_health_check_server()
            
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _load_search_configs(self):
        """Load search configurations from file"""
        try:
            with open(self.search_config_path, 'r') as f:
                config = json.load(f)
                return config.get('searches', [])
        except Exception as e:
            logger.error(f"Failed to load search configs: {truncate_content(str(e))}")
            return []

    def _get_next_search_config(self):
        """Get the next search configuration in rotation"""
        if not self.search_configs:
            return None
        config = self.search_configs[self.current_search_index]
        self.current_search_index = (self.current_search_index + 1) % len(self.search_configs)
        return config

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully"""
        if self.running:
            logger.info("Stopping poller...")
            self.running = False
            try:
                if hasattr(self, 'health_server'):
                    self.health_server.shutdown()
            except:
                pass
            finally:
                # Force exit after 2 seconds if graceful shutdown fails
                time.sleep(2)
                os._exit(0)

    @with_circuit_breaker("webhook")
    def _send_webhook_notification(self, job_data: dict, processed_data: dict, search_config: dict):
        """Send webhook notification for high-value jobs"""
        try:
            with MetricsTimer(API_LATENCY, {"api_type": "webhook"}):
                API_REQUESTS.labels(api_type="webhook").inc()
                
                # Extract location from client info if available
                location = "Unknown"
                client_info = job_data.get("client_infomation", "")
                if client_info:
                    parts = client_info.split("|")
                    if parts:
                        location = parts[0].strip()
                
                # Scrape and answer questions for high-value jobs
                questions_data = {}
                answers_data = {}
                if job_data.get("apply_url"):
                    questions_data = scrape_job_questions(job_data["apply_url"])
                    if questions_data.get("questions"):
                        answers_data = generate_question_answers(job_data, questions_data["questions"])

                payload = {
                    "timestamp": datetime.now().isoformat(),
                    "job_url": job_data.get("url"),
                    "apply_url": job_data.get("apply_url"),
                    "payment": job_data.get("rate"),
                    "location": location,
                    "posted_time": job_data.get("posted_time", "Recently"),
                    "cover_letter": processed_data.get("cover_letter"),
                    "job_details": {
                        "id": job_data.get("upwork_id"),  # Use Upwork ID instead of random UUID
                        "title": job_data.get("title"),
                        "description": job_data.get("description"),
                        "job_type": job_data.get("job_type"),
                        "experience_level": job_data.get("experience_level"),
                        "duration": job_data.get("duration"),
                        "client_information": job_data.get("client_infomation"),
                        "score": job_data.get("score"),
                        "full_description": job_data.get("description")  # Include full description
                    },
                    "application_details": {
                        "questions": questions_data.get("questions", []),
                        "answers": [
                            {
                                "question": q["text"],
                                "answer": a["answer"],
                                "type": q.get("type", "text")
                            }
                            for q, a in zip(questions_data.get("questions", []), answers_data.get("answers", []))
                        ]
                    },
                    "metadata": {
                        "processed_at": processed_data.get("processed_at"),
                        "search_config": search_config
                    }
                }
            
                logger.debug(f"Sending webhook to URL: {self.webhook_url}")
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

    def _process_job(self, job_id: str, job_data: dict, search_config: dict) -> Optional[dict]:
        """Process a single job and return the result"""
        try:
            logger.debug(f"Starting to process job {job_id}")
            logger.debug(f"Job data structure: {truncate_content(str(job_data))}")
            
            JOBS_PROCESSED.inc()
            
            # Check job data structure
            if "description" not in job_data:
                logger.error(f"Missing description in job data for job {job_id}")
                return None
            
            result = {
                "job_id": job_id,
                "processed_at": datetime.now().isoformat()
            }
            
            # Only generate content for high-value jobs
            if job_data.get("score", 0) >= self.high_value_threshold:
                HIGH_VALUE_JOBS.inc()
                logger.info(f"High-value job found: {job_id} (score: {job_data.get('score')})")
                
                # Generate cover letter
                logger.debug(f"Generating cover letter for job {job_id}")
                cover_letter_response = generate_cover_letter(
                    job_data["description"],
                    self.profile
                )
                cover_letter = cover_letter_response.get("letter", "") if isinstance(cover_letter_response, dict) else str(cover_letter_response)
                result["cover_letter"] = cover_letter
                
                # Generate interview script
                script_response = generate_interview_script_content(
                    job_data["description"]
                )
                interview_script = script_response.get("script", "") if isinstance(script_response, dict) else str(script_response)
                result["interview_script"] = interview_script
                
                # Send webhook notification with current search config
                self._send_webhook_notification(job_data, result, search_config)
            
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
        logger.info("Starting Upwork poller with search configurations")
        self.running = True
        
        while self.running:
            try:
                # Update system metrics
                self._update_metrics()
                # Get next search configuration
                search_config = self._get_next_search_config()
                if not search_config:
                    logger.error("No valid search configurations available")
                    time.sleep(self.poll_interval)
                    continue

                # Scrape latest jobs
                logger.debug(f"Polling for new jobs with config: {search_config}")
                with MetricsTimer(API_LATENCY, {"api_type": "scraper"}):
                    jobs_df = scrape_upwork_data(
                        search_config,
                        self.max_jobs_per_poll
                    )
                    if not jobs_df.empty:
                        JOBS_SCRAPED.inc(len(jobs_df))
                
                if jobs_df.empty:
                    logger.debug(f"No new jobs found for current search, rotating to next...")
                    continue
                
                # Score jobs
                scored_jobs = score_scaped_jobs(jobs_df, self.profile)
                logger.debug(f"Scored jobs DataFrame: {scored_jobs.columns.tolist()}")
                
                try:
                    # Process new jobs
                    logger.debug("Starting to process new jobs...")
                    for _, job in scored_jobs.iterrows():
                        # Convert job row to dictionary
                        job_data = job.to_dict()
                        
                        # Skip if already seen based on Upwork ID
                        if self.job_tracker.is_job_seen(job_data):
                            logger.debug(f"Job already seen, skipping: {truncate_content(job_data['title'])}")
                            continue
                        
                        # Mark as seen and get assigned job ID
                        logger.debug(f"Marking job as seen: {truncate_content(job_data['title'])}")
                        job_id = self.job_tracker.mark_job_seen(job_data)
                        logger.debug(f"Assigned job ID: {job_id}")
                    
                    # Process unprocessed jobs
                    logger.debug("Getting unprocessed jobs...")
                    unprocessed = self.job_tracker.get_unprocessed_jobs()
                    logger.debug(f"Found {len(unprocessed)} unprocessed jobs")
                    JOBS_IN_QUEUE.set(len(unprocessed))
                    
                    for job_id, job_data in unprocessed.items():
                        logger.debug(f"Processing unprocessed job {job_id}")
                        result = self._process_job(job_id, job_data, search_config)
                        if result:
                            logger.debug(f"Successfully processed job {job_id}")
                            self.job_tracker.mark_job_processed(job_id, result)
                        else:
                            logger.error(f"Failed to process job {job_id}")
                except Exception as e:
                    logger.error(f"Error in job processing: {truncate_content(str(e))}")
                    raise
                
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
    profile_path = os.getenv("FREELANCER_PROFILE_PATH", "./files/profile.md")
    search_config_path = os.getenv("SEARCH_CONFIG_PATH", "./files/search_config.json")
    poll_interval = int(os.getenv("POLLING_INTERVAL", "480"))
    max_jobs = int(os.getenv("MAX_JOBS_PER_POLL", "10"))
    retention_days = int(os.getenv("JOB_RETENTION_DAYS", "30"))
    webhook_url = os.getenv("WEBHOOK_URL")
    if not webhook_url:
        webhook_url = "https://n8n.fy.studio/webhook/a9a844f3-d651-4413-8bf3-820c6877b153"
        logger.warning(f"WEBHOOK_URL not found in environment, using default: {webhook_url}")
    else:
        logger.debug(f"Using webhook URL from environment: {webhook_url}")
    high_value_threshold = float(os.getenv("HIGH_VALUE_THRESHOLD", "7.0"))
    
    poller = UpworkPoller(
        profile_path=profile_path,
        webhook_url=webhook_url,
        search_config_path=search_config_path,
        poll_interval=poll_interval,
        max_jobs_per_poll=max_jobs,
        job_retention_days=retention_days,
        high_value_threshold=high_value_threshold
    )
    
    poller.run()

if __name__ == "__main__":
    main()
