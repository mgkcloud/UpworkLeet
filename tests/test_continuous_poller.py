import os
import json
import pytest
import signal
import time
import requests
import socket
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock, ANY
import pandas as pd
from src.job_tracker import JobTracker
from src.continuous_poller import UpworkPoller
from src.health_check import HealthCheckHandler

def get_free_port():
    """Get a free port number"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port

@pytest.fixture
def health_check_port():
    """Get a free port for health check server"""
    return get_free_port()

@pytest.fixture
def job_tracker():
    """Create a temporary job tracker for testing"""
    test_dir = "./tests/test_data/job_tracking"
    os.makedirs(test_dir, exist_ok=True)
    tracker = JobTracker(storage_dir=test_dir)
    yield tracker
    # Cleanup
    if os.path.exists(test_dir):
        for f in os.listdir(test_dir):
            os.remove(os.path.join(test_dir, f))
        os.rmdir(test_dir)

@pytest.fixture
def sample_jobs_df():
    """Create a sample jobs DataFrame"""
    return pd.DataFrame([
        {
            "job_id": "123",
            "title": "AI Developer",
            "description": "Test job description",
            "job_type": "Hourly",
            "experience_level": "Expert",
            "duration": "1-3 months",
            "rate": "$50-70/hr",
            "client_infomation": "Test client info",
            "score": 8.0  # High-value job
        },
        {
            "job_id": "456",
            "title": "ML Engineer",
            "description": "Another test job",
            "job_type": "Fixed",
            "experience_level": "Intermediate",
            "duration": "< 1 month",
            "rate": "$1000",
            "client_infomation": "Another client",
            "score": 6.0  # Not a high-value job
        }
    ])

def test_job_tracker_initialization(job_tracker):
    """Test that job tracker initializes correctly"""
    assert os.path.exists(job_tracker.seen_jobs_file)
    assert os.path.exists(job_tracker.processed_jobs_file)

def test_mark_and_check_seen_job(job_tracker):
    """Test marking and checking seen jobs"""
    job_id = "test_job_1"
    job_data = {"title": "Test Job", "description": "Test Description"}
    
    assert not job_tracker.is_job_seen(job_id)
    job_tracker.mark_job_seen(job_id, job_data)
    assert job_tracker.is_job_seen(job_id)

def test_mark_job_processed(job_tracker):
    """Test marking jobs as processed"""
    job_id = "test_job_2"
    processing_result = {
        "cover_letter": "Test cover letter",
        "interview_script": "Test script"
    }
    
    job_tracker.mark_job_processed(job_id, processing_result)
    processed_jobs = job_tracker._load_json(job_tracker.processed_jobs_file)
    assert job_id in processed_jobs
    assert "cover_letter" in processed_jobs[job_id]["result"]

def test_get_unprocessed_jobs(job_tracker):
    """Test getting unprocessed jobs"""
    # Add some seen jobs
    job_tracker.mark_job_seen("job1", {"data": "test1"})
    job_tracker.mark_job_seen("job2", {"data": "test2"})
    
    # Process one job
    job_tracker.mark_job_processed("job1", {"result": "processed"})
    
    unprocessed = job_tracker.get_unprocessed_jobs()
    assert len(unprocessed) == 1
    assert "job2" in unprocessed

def test_cleanup_old_jobs(job_tracker):
    """Test cleaning up old jobs"""
    # Add some jobs with old timestamps
    old_date = (datetime.now() - timedelta(days=40)).isoformat()
    recent_date = datetime.now().isoformat()
    
    seen_jobs = {
        "old_job": {"first_seen": old_date, "job_data": {}},
        "new_job": {"first_seen": recent_date, "job_data": {}}
    }
    job_tracker._save_json(job_tracker.seen_jobs_file, seen_jobs)
    
    job_tracker.cleanup_old_jobs(days_to_keep=30)
    remaining_jobs = job_tracker._load_json(job_tracker.seen_jobs_file)
    
    assert "old_job" not in remaining_jobs
    assert "new_job" in remaining_jobs

@patch('src.continuous_poller.scrape_upwork_data')
@patch('src.continuous_poller.generate_cover_letter')
@patch('src.continuous_poller.generate_interview_script_content')
@patch('requests.post')
def test_upwork_poller(mock_post, mock_script, mock_letter, mock_scrape, sample_jobs_df, job_tracker, health_check_port):
    """Test the UpworkPoller class"""
    # Setup mocks
    mock_scrape.return_value = sample_jobs_df
    mock_letter.return_value = {"letter": "Test cover letter"}
    mock_script.return_value = {"script": "Test interview script"}
    mock_post.return_value.status_code = 200
    
    # Create poller with test configuration
    with patch('src.health_check.HTTPServer') as mock_server:
        poller = UpworkPoller(
            search_query="test query",
            profile_path="tests/test_data/test_profile.md",
            webhook_url="http://test.webhook",
            poll_interval=1,
            max_jobs_per_poll=5,
            job_retention_days=30,
            high_value_threshold=7.0
        )
        
        # Replace job tracker with test instance
        poller.job_tracker = job_tracker
        
        # Mock profile content
        poller.profile = "Test profile content"
        
        # Run one iteration
        poller.running = True
        try:
            # Process high-value job
            poller._process_job("123", {
                "job_data": sample_jobs_df.iloc[0].to_dict()
            })
            
            # Verify webhook was called for high-value job
            mock_post.assert_called_once_with(
                "http://test.webhook",
                json=ANY,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            # Process low-value job
            mock_post.reset_mock()
            poller._process_job("456", {
                "job_data": sample_jobs_df.iloc[1].to_dict()
            })
            
            # Verify webhook was not called for low-value job
            mock_post.assert_not_called()
            
            # Verify jobs were processed
            processed_jobs = job_tracker._load_json(job_tracker.processed_jobs_file)
            assert "123" in processed_jobs
            assert "456" in processed_jobs
            
        finally:
            poller.running = False
            if hasattr(poller, 'health_server'):
                poller.health_server.shutdown()

def test_error_handling(job_tracker, health_check_port):
    """Test error handling in job processing"""
    with patch('src.continuous_poller.generate_cover_letter') as mock_letter, \
         patch('src.health_check.HTTPServer') as mock_server:
        # Simulate an error
        mock_letter.side_effect = Exception("Test error")
        
        poller = UpworkPoller(
            search_query="test",
            profile_path="tests/test_data/test_profile.md",
            webhook_url="http://test.webhook",
            poll_interval=1
        )
        poller.job_tracker = job_tracker
        
        try:
            result = poller._process_job("error_job", {
                "job_data": {
                    "description": "Test description"
                }
            })
            
            assert result is None
            # Verify job wasn't marked as processed
            processed_jobs = job_tracker._load_json(job_tracker.processed_jobs_file)
            assert "error_job" not in processed_jobs
        finally:
            if hasattr(poller, 'health_server'):
                poller.health_server.shutdown()

def test_initialization_error():
    """Test error handling during initialization"""
    with pytest.raises(Exception):
        UpworkPoller(
            search_query="test",
            profile_path="nonexistent_profile.md",
            webhook_url="http://test.webhook"
        )

def test_cleanup_scheduling(job_tracker, health_check_port):
    """Test that cleanup runs on schedule"""
    with patch('src.health_check.HTTPServer') as mock_server:
        poller = UpworkPoller(
            search_query="test",
            profile_path="tests/test_data/test_profile.md",
            webhook_url="http://test.webhook",
            poll_interval=1
        )
        poller.job_tracker = job_tracker
        
        try:
            # Set last cleanup to 25 hours ago
            poller.last_cleanup = datetime.now() - timedelta(hours=25)
            
            # Add test data
            old_date = (datetime.now() - timedelta(days=40)).isoformat()
            job_tracker._save_json(job_tracker.seen_jobs_file, {
                "old_job": {"first_seen": old_date, "job_data": {}}
            })
            
            # Run cleanup
            poller._cleanup_if_needed()
            
            # Verify old job was removed
            remaining_jobs = job_tracker._load_json(job_tracker.seen_jobs_file)
            assert "old_job" not in remaining_jobs
        finally:
            if hasattr(poller, 'health_server'):
                poller.health_server.shutdown()

@patch('src.continuous_poller.scrape_upwork_data')
def test_main_polling_loop(mock_scrape, job_tracker, sample_jobs_df, health_check_port):
    """Test the main polling loop"""
    mock_scrape.return_value = sample_jobs_df
    
    with patch('src.health_check.HTTPServer') as mock_server:
        poller = UpworkPoller(
            search_query="test",
            profile_path="tests/test_data/test_profile.md",
            webhook_url="http://test.webhook",
            poll_interval=1
        )
        poller.job_tracker = job_tracker
        
        def stop_after_one_iteration():
            time.sleep(0.1)  # Let the first iteration complete
            poller.running = False
        
        try:
            # Start a thread to stop the poller after one iteration
            import threading
            stop_thread = threading.Thread(target=stop_after_one_iteration)
            stop_thread.start()
            
            # Run the poller
            poller.run()
            
            # Verify jobs were processed
            seen_jobs = job_tracker._load_json(job_tracker.seen_jobs_file)
            assert len(seen_jobs) == 2  # Both sample jobs should be seen
            assert "123" in seen_jobs
            assert "456" in seen_jobs
        finally:
            if hasattr(poller, 'health_server'):
                poller.health_server.shutdown()

def test_signal_handling(health_check_port):
    """Test signal handling"""
    with patch('src.health_check.HTTPServer') as mock_server:
        poller = UpworkPoller(
            search_query="test",
            profile_path="tests/test_data/test_profile.md",
            webhook_url="http://test.webhook"
        )
        
        try:
            # Simulate SIGINT
            poller._handle_shutdown(signal.SIGINT, None)
            assert not poller.running
            
            # Reset and simulate SIGTERM
            poller.running = True
            poller._handle_shutdown(signal.SIGTERM, None)
            assert not poller.running
        finally:
            if hasattr(poller, 'health_server'):
                poller.health_server.shutdown()

def test_health_check(health_check_port):
    """Test health check endpoint"""
    with patch('src.health_check.HTTPServer') as mock_server:
        mock_server.return_value.server_address = ('localhost', health_check_port)
        
        poller = UpworkPoller(
            search_query="test",
            profile_path="tests/test_data/test_profile.md",
            webhook_url="http://test.webhook"
        )
        
        try:
            # Test health check endpoint
            mock_handler = MagicMock()
            mock_handler.path = '/health'
            handler = HealthCheckHandler(None, None, None)
            handler.send_response = MagicMock()
            handler.send_header = MagicMock()
            handler.end_headers = MagicMock()
            handler.wfile = MagicMock()
            
            handler.do_GET()
            
            handler.send_response.assert_called_once_with(200)
            handler.send_header.assert_called_once_with('Content-type', 'text/plain')
            handler.end_headers.assert_called_once()
            handler.wfile.write.assert_called_once_with(b"OK")
            
            # Test invalid endpoint
            mock_handler.path = '/invalid'
            handler.do_GET()
            
            assert handler.send_response.call_args_list[-1] == ((404,),)
        finally:
            if hasattr(poller, 'health_server'):
                poller.health_server.shutdown()

def test_webhook_notification():
    """Test webhook notification for high-value jobs"""
    with patch('requests.post') as mock_post, \
         patch('src.health_check.HTTPServer') as mock_server:
        mock_post.return_value.status_code = 200
        
        poller = UpworkPoller(
            search_query="test",
            profile_path="tests/test_data/test_profile.md",
            webhook_url="http://test.webhook",
            high_value_threshold=7.0
        )
        
        try:
            # Test high-value job
            job_data = {
                "job_id": "123",
                "title": "High Value Job",
                "score": 8.0
            }
            processed_data = {
                "cover_letter": "Test cover letter",
                "interview_script": "Test script",
                "processed_at": datetime.now().isoformat()
            }
            
            poller._send_webhook_notification(job_data, processed_data)
            
            # Verify webhook was called with correct data
            mock_post.assert_called_once_with(
                "http://test.webhook",
                json=ANY,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            # Verify webhook payload structure
            call_args = mock_post.call_args
            payload = call_args[1]["json"]
            assert "timestamp" in payload
            assert "job_details" in payload
            assert "generated_content" in payload
            assert "metadata" in payload
            assert payload["job_details"]["score"] == 8.0
            assert payload["generated_content"]["cover_letter"] == "Test cover letter"
            assert payload["metadata"]["search_query"] == "test"
        finally:
            if hasattr(poller, 'health_server'):
                poller.health_server.shutdown()

if __name__ == '__main__':
    pytest.main([__file__])
