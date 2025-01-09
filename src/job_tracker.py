import os
import json
import uuid
import hashlib
from datetime import datetime
from .utils import setup_logger, truncate_content

logger = setup_logger('job_tracker')

class JobTracker:
    def __init__(self, storage_dir="./files/job_tracking"):
        self.storage_dir = storage_dir
        self.seen_jobs_file = os.path.join(storage_dir, "seen_jobs.json")
        self.processed_jobs_file = os.path.join(storage_dir, "processed_jobs.json")
        self._init_storage()

    def _init_storage(self):
        """Initialize storage directory and files if they don't exist"""
        os.makedirs(self.storage_dir, exist_ok=True)
        
        # Initialize files with empty objects
        for filepath in [self.seen_jobs_file, self.processed_jobs_file]:
            if not os.path.exists(filepath):
                with open(filepath, 'w') as f:
                    json.dump({}, f)

    def _load_json(self, filepath):
        """Load JSON data from file"""
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {filepath}: {truncate_content(str(e))}")
            return {}

    def _save_json(self, filepath, data):
        """Save data to JSON file"""
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving to {filepath}: {truncate_content(str(e))}")

    def is_job_seen(self, job_data):
        """Check if a job has been seen before based on Upwork ID"""
        seen_jobs = self._load_json(self.seen_jobs_file)
        upwork_id = job_data.get('upwork_id')
        
        if not upwork_id:
            logger.warning("No Upwork ID found in job data")
            # Fall back to description hash if no Upwork ID
            description = job_data.get('description', '')
            if not description:
                return False
            description_hash = hashlib.md5(description.encode()).hexdigest()
            for job in seen_jobs.values():
                if job.get('description_hash') == description_hash:
                    return True
            return False
            
        # Check if any existing job matches this Upwork ID
        return upwork_id in seen_jobs

    def mark_job_seen(self, job_data):
        """Mark a job as seen with timestamp"""
        seen_jobs = self._load_json(self.seen_jobs_file)
        upwork_id = job_data.get('upwork_id')
        
        if not upwork_id:
            logger.warning("No Upwork ID found in job data")
            # Fall back to description hash if no Upwork ID
            description = job_data.get('description', '')
            if not description:
                job_id = str(uuid.uuid4())
            else:
                description_hash = hashlib.md5(description.encode()).hexdigest()
                # Check if we've seen this description before
                for existing_job in seen_jobs.values():
                    if existing_job.get('description_hash') == description_hash:
                        return existing_job.get('job_id')
                job_id = str(uuid.uuid4())
                job_data['description_hash'] = description_hash
        else:
            job_id = upwork_id
            
        job_data['job_id'] = job_id
        seen_jobs[job_id] = job_data
        self._save_json(self.seen_jobs_file, seen_jobs)
        return job_id

    def mark_job_processed(self, job_id, processing_result):
        """Mark a job as processed with result data"""
        processed_jobs = self._load_json(self.processed_jobs_file)
        processed_jobs[job_id] = {
            "processed_at": datetime.now().isoformat(),
            "result": processing_result
        }
        self._save_json(self.processed_jobs_file, processed_jobs)

    def get_unprocessed_jobs(self):
        """Get list of seen jobs that haven't been processed"""
        seen_jobs = self._load_json(self.seen_jobs_file)
        processed_jobs = self._load_json(self.processed_jobs_file)
        
        unprocessed = {}
        for job_id, job_data in seen_jobs.items():
            if job_id not in processed_jobs:
                unprocessed[job_id] = job_data
        
        return unprocessed

    def cleanup_old_jobs(self, days_to_keep=30):
        """Remove jobs older than specified days"""
        cutoff = datetime.now().timestamp() - (days_to_keep * 24 * 60 * 60)
        
        seen_jobs = self._load_json(self.seen_jobs_file)
        processed_jobs = self._load_json(self.processed_jobs_file)
        
        # Clean processed jobs
        processed_jobs = {
            k: v for k, v in processed_jobs.items()
            if datetime.fromisoformat(v["processed_at"]).timestamp() > cutoff
        }
        
        # Clean seen jobs that are no longer in processed_jobs
        seen_jobs = {
            k: v for k, v in seen_jobs.items()
            if k in processed_jobs
        }
        
        self._save_json(self.seen_jobs_file, seen_jobs)
        self._save_json(self.processed_jobs_file, processed_jobs)
