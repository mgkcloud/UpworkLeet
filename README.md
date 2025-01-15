# Upwork Job Automation System

An automated system for continuously monitoring Upwork job listings, generating cover letters, and preparing interview scripts. The system efficiently tracks seen jobs, processes new listings, and sends webhook notifications for high-value opportunities.

## Features

- Continuous polling of Upwork job listings
- Webhook notifications for high-value job matches
- Health check endpoint for container monitoring
- Efficient job tracking to avoid duplicate processing
- Automatic cover letter generation
- Interview script preparation
- Docker containerization for easy deployment
- Persistent storage of job data and generated content
- Rate limiting and error handling
- Configurable polling intervals and job retention

## Setup

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (if running locally)
- A freelancer profile markdown file
- Webhook endpoint for receiving notifications (optional)
- Upwork account credentials


### Configuration

The system can be configured using environment variables:

```env
# Required Settings
GOOGLE_API_KEY="your-api-key"  # Google API key for content generation

# Optional Settings
POLLING_INTERVAL=480  # Polling interval (8 minutes)
MAX_JOBS_PER_POLL=10  # Maximum jobs to process per poll
JOB_RETENTION_DAYS=30  # Days to keep job data
HIGH_VALUE_THRESHOLD=7.0  # Minimum score for high-value jobs
WEBHOOK_URL="https://your-webhook-url"  # Webhook for high-value job notifications
```

### Running Locally

1. Install dependencies:
```bash
pip install -r requirements.txt
playwright install firefox
playwright install-deps
```

2. Authentication

The system requires authentication to access Upwork job listings and apply pages. Authentication is handled through browser cookies that are saved from your logged-in Upwork session.

  1. Run the cookie saver script:
  ```bash
  ./scripts/save_upwork_cookies.py
  ```

  2. A browser window will open. Log in to your Upwork account if not already logged in.

  3. Once logged in, press Enter in the terminal. The script will save your authentication cookies to `files/auth/cookies.json`.

  4. The system will automatically use these cookies for all Upwork requests. If you get authentication errors, simply run the script again to update the cookies with a fresh session.

Note: Keep your cookies file secure as it contains sensitive authentication information.

3. Import the UPWORK_JOBS_n8n_IMPORTME.json into a new n8n workflow,
-  Generate a new webhook
-  Update the .env with the new webhook address


4. Run the continuous poller:
```bash
python src/continuous_poller.py
```


### Running with Docker (Untested)

1. Place your freelancer profile in `files/profile.md`

2. Create a `.env` file with your configuration

3. Build and start the container:
```bash
docker-compose up -d
```

4. Monitor the logs:
```bash
docker-compose logs -f
```




## System Architecture

### Job Tracking

The system maintains two types of data:

1. **Seen Jobs**: All jobs that have been discovered through polling
2. **Processed Jobs**: Jobs that have been analyzed and have generated content

This separation allows for:
- Efficient tracking of new jobs
- Recovery from processing failures
- Historical record keeping

### Webhook Notifications

The system sends webhook notifications for high-value job matches (score ≥ 7.0). The notification payload includes:

```json
{
  "timestamp": "ISO-8601 timestamp",
  "job_details": {
    "id": "job identifier",
    "title": "job title",
    "description": "job description",
    "job_type": "job type",
    "experience_level": "required experience",
    "duration": "project duration",
    "rate": "payment rate",
    "client_information": "client details",
    "score": "match score",
    "url": "job posting URL"
  },
  "generated_content": {
    "cover_letter": "generated cover letter",
    "interview_script": "generated interview script"
  },
  "metadata": {
    "processed_at": "processing timestamp",
    "search_query": "search query used",
    "match_score": "job match score"
  }
}
```

### Health Check

The system provides a health check endpoint at `http://localhost:8000/health` that returns:
- 200 OK when the system is healthy
- 404 for invalid endpoints

This endpoint can be used for container orchestration and monitoring.

### Data Storage

Data is stored in three locations:

- `/app/files/job_tracking`: JSON files tracking job status
- `/app/files/cache`: Cached web content to reduce API calls
- `/app/logs`: Application logs

These directories are persisted using Docker volumes.

### Rate Limiting

The system implements several rate limiting strategies:

- Configurable polling intervals (default: 8 minutes)
- Exponential backoff on errors
- Caching of web content
- Batch processing of jobs

## Monitoring

### Logs

Logs are written to both the console and `upwork_poller.log`. They include:
- Job discovery events
- Processing status
- Webhook notification status
- Error messages
- Rate limiting events

### Health Checks

Monitor container health:
```bash
curl http://localhost:8000/health
```

### Docker Stats

Monitor container resource usage:
```bash
docker stats upwork-job-poller
```

## Maintenance

### Cleaning Up Old Data

The system automatically cleans up old job data based on `JOB_RETENTION_DAYS`. Manual cleanup:

```bash
# Remove old volumes
docker-compose down
docker volume rm upwork-job-tracking upwork-cache upwork-logs

# Restart with clean state
docker-compose up -d
```

### Updating

1. Pull latest changes:
```bash
git pull
```

2. Rebuild and restart:
```bash
docker-compose down
docker-compose build
docker-compose up -d
```

## Troubleshooting

### Common Issues

1. **Rate Limiting**: If you see frequent rate limiting messages, try:
   - Increasing `POLLING_INTERVAL`
   - Decreasing `MAX_JOBS_PER_POLL`

2. **Memory Usage**: If the container uses too much memory:
   - Adjust the memory limits in `docker-compose.yml`
   - Decrease `JOB_RETENTION_DAYS`

3. **Processing Errors**: Check logs for specific error messages:
```bash
docker-compose logs -f | grep ERROR
```

4. **Webhook Issues**: If webhook notifications fail:
   - Verify the `WEBHOOK_URL` is correct and accessible
   - Check network connectivity from the container
   - Review webhook endpoint logs

5. **Health Check Failures**: If health checks fail:
   - Verify port 8000 is not in use
   - Check container logs for startup errors
   - Ensure container has network access

## Contributing

1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## License

MIT License
