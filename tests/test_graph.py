import pytest
from unittest.mock import Mock, patch
import pandas as pd
from src.graph import UpworkAutomation

@pytest.fixture
def sample_jobs_df():
    """Create a sample jobs DataFrame for testing"""
    return pd.DataFrame([
        {
            "job_id": "123",
            "title": "AI Developer",
            "description": "Test job description",
            "job_type": "Hourly",
            "experience_level": "Expert",
            "duration": "1-3 months",
            "rate": "$50-70/hr",
            "client_infomation": "Test client info"
        }
    ], columns=[
        "job_id",
        "title",
        "description",
        "job_type",
        "experience_level",
        "duration",
        "rate",
        "client_infomation"
    ])

@pytest.fixture
def automation():
    """Create a UpworkAutomation instance for testing"""
    with open("tests/test_data/test_profile.md", "r") as f:
        profile = f.read()
    return UpworkAutomation(profile=profile, num_jobs=5)

def test_graph_initialization(automation):
    """Test that the graph is initialized correctly"""
    assert automation.graph is not None
    assert automation.profile is not None
    assert automation.number_of_jobs == 5

@patch('src.utils.scrape_upwork_data')
def test_scrape_upwork_jobs(mock_scrape, automation, sample_jobs_df):
    """Test job scraping functionality"""
    # Test with valid job title
    mock_scrape.return_value = sample_jobs_df.copy()
    
    initial_state = {
        "job_title": "test",
        "scraped_jobs_df": pd.DataFrame(),
        "matches": [],
        "job_description": "",
        "cover_letter": "",
        "call_script": "",
        "num_matches": 0
    }
    
    result = automation.scrape_upwork_jobs(initial_state)
    
    # Verify state is maintained and updated correctly
    assert "job_title" in result
    assert "scraped_jobs_df" in result
    assert "matches" in result
    assert "job_description" in result
    assert "cover_letter" in result
    assert "call_script" in result
    assert "num_matches" in result
    
    # Verify content is correct
    assert isinstance(result["scraped_jobs_df"], pd.DataFrame)
    assert len(result["scraped_jobs_df"]) == len(sample_jobs_df)
    pd.testing.assert_frame_equal(result["scraped_jobs_df"], sample_jobs_df)
    
    # Verify mock was called correctly
    mock_scrape.assert_called_once_with("test", automation.number_of_jobs)
    
    # Test with empty job title
    empty_state = {
        "job_title": "",
        "scraped_jobs_df": pd.DataFrame(),
        "matches": [],
        "job_description": "",
        "cover_letter": "",
        "call_script": "",
        "num_matches": 0
    }
    
    empty_result = automation.scrape_upwork_jobs(empty_state)
    
    # Verify empty state is handled correctly
    assert isinstance(empty_result["scraped_jobs_df"], pd.DataFrame)
    assert empty_result["scraped_jobs_df"].empty
    assert mock_scrape.call_count == 1  # Should not be called again

@patch('src.utils.score_scaped_jobs')
@patch('src.utils.convert_jobs_matched_to_string_list')
def test_score_scraped_jobs(mock_convert, mock_score, automation, sample_jobs_df):
    """Test job scoring functionality"""
    # Test with jobs to score
    # Create scored DataFrame with expected columns
    scored_df = pd.DataFrame([{
        "job_id": "123",
        "title": "AI Developer",
        "description": "Test job description",
        "job_type": "Hourly",
        "experience_level": "Expert",
        "duration": "1-3 months",
        "rate": "$50-70/hr",
        "client_infomation": "Test client info",
        "score": 8.0  # Score >= 7 for matching
    }], columns=[
        "job_id",
        "title",
        "description",
        "job_type",
        "experience_level",
        "duration",
        "rate",
        "client_infomation",
        "score"
    ])
    mock_score.return_value = scored_df
    mock_convert.return_value = ["Test job match"]
    
    initial_state = {
        "job_title": "test",
        "scraped_jobs_df": sample_jobs_df,
        "matches": [],
        "job_description": "",
        "cover_letter": "",
        "call_script": "",
        "num_matches": 0
    }
    
    result = automation.score_scraped_jobs(initial_state)
    
    assert "scraped_jobs_df" in result
    assert "matches" in result
    assert "num_matches" in result
    assert len(result["matches"]) == 1
    assert result["num_matches"] == 1
    pd.testing.assert_frame_equal(result["scraped_jobs_df"], scored_df)
    assert result["matches"] == ["Test job match"]
    
    # Test with empty DataFrame
    empty_state = {
        "job_title": "test",
        "scraped_jobs_df": pd.DataFrame(),
        "matches": [],
        "job_description": "",
        "cover_letter": "",
        "call_script": "",
        "num_matches": 0
    }
    
    empty_result = automation.score_scraped_jobs(empty_state)
    
    assert "scraped_jobs_df" in empty_result
    assert "matches" in empty_result
    assert "num_matches" in empty_result
    assert len(empty_result["matches"]) == 0
    assert empty_result["num_matches"] == 0
    assert empty_result["matches"] == []

def test_need_to_process_matches(automation):
    """Test match processing decision logic"""
    # Test with matches
    initial_state = {
        "job_title": "test",
        "scraped_jobs_df": pd.DataFrame(),
        "matches": ["job1", "job2"],
        "job_description": "",
        "cover_letter": "",
        "call_script": "",
        "num_matches": 2
    }
    result = automation.need_to_process_matches(initial_state)
    assert result == "Process jobs"
    
    # Test without matches
    empty_state = {
        "job_title": "test",
        "scraped_jobs_df": pd.DataFrame(),
        "matches": [],
        "job_description": "",
        "cover_letter": "",
        "call_script": "",
        "num_matches": 0
    }
    result = automation.need_to_process_matches(empty_state)
    assert result == "No matches"
    
    # Test edge case with None matches
    none_state = {
        "job_title": "test",
        "scraped_jobs_df": pd.DataFrame(),
        "matches": None,
        "job_description": "",
        "cover_letter": "",
        "call_script": "",
        "num_matches": 0
    }
    result = automation.need_to_process_matches(none_state)
    assert result == "No matches"

@patch('src.utils.generate_cover_letter')
def test_generate_cover_letter(mock_generate, automation):
    """Test cover letter generation"""
    mock_generate.return_value = {"letter": "Hello, I'm excited about this opportunity... Best, Aymen"}
    
    initial_state = {
        "job_title": "test",
        "scraped_jobs_df": pd.DataFrame(),
        "matches": ["Test job description"],
        "job_description": "",
        "cover_letter": "",
        "call_script": "",
        "num_matches": 1
    }
    
    result = automation.generate_cover_letter(initial_state)
    
    # Verify state is maintained and updated correctly
    assert "job_title" in result
    assert "scraped_jobs_df" in result
    assert "matches" in result
    assert "job_description" in result
    assert "cover_letter" in result
    assert "call_script" in result
    assert "num_matches" in result
    
    # Verify content is correct
    assert result["job_description"] == "Test job description"
    assert result["cover_letter"].startswith("Hello")
    assert result["cover_letter"].endswith("Best, Aymen")
    
    # Verify mock was called correctly
    mock_generate.assert_called_once_with("Test job description", automation.profile)

@patch('src.utils.generate_interview_script_content')
def test_generate_interview_script_content(mock_generate, automation):
    """Test interview script generation"""
    mock_generate.return_value = {"script": "# Introduction\nHi [Client Name]...\n\n# Key Points\n...\n\n# Client Questions\n...\n\n# Questions to Ask\n..."}
    
    initial_state = {
        "job_title": "test",
        "scraped_jobs_df": pd.DataFrame(),
        "matches": ["Test job description"],
        "job_description": "Test job description",
        "cover_letter": "Test cover letter",
        "call_script": "",
        "num_matches": 1
    }
    
    result = automation.generate_interview_script_content(initial_state)
    
    # Verify state is maintained and updated correctly
    assert "job_title" in result
    assert "scraped_jobs_df" in result
    assert "matches" in result
    assert "job_description" in result
    assert "cover_letter" in result
    assert "call_script" in result
    assert "num_matches" in result
    
    # Verify content is correct
    assert "# Introduction" in result["call_script"]
    assert "# Key Points" in result["call_script"]
    assert "# Client Questions" in result["call_script"]
    assert "# Questions to Ask" in result["call_script"]
    assert result["job_description"] == "Test job description"
    assert result["cover_letter"] == "Test cover letter"
    
    # Verify mock was called correctly
    mock_generate.assert_called_once_with("Test job description")

def test_save_job_application_content(automation, tmp_path, monkeypatch):
    """Test saving job application content"""
    # Set up test file path
    test_file = tmp_path / "cover_letter.txt"
    monkeypatch.setattr("src.graph.COVER_LETTERS_FILE", str(test_file))
    
    initial_state = {
        "job_title": "test",
        "scraped_jobs_df": pd.DataFrame(),
        "matches": ["remaining job"],
        "job_description": "Test job description",
        "cover_letter": "Test cover letter",
        "call_script": "Test interview script",
        "num_matches": 1
    }
    
    result = automation.save_job_application_content(initial_state)
    
    # Verify state is maintained and updated correctly
    assert "job_title" in result
    assert "scraped_jobs_df" in result
    assert "matches" in result
    assert "job_description" in result
    assert "cover_letter" in result
    assert "call_script" in result
    assert "num_matches" in result
    
    # Verify file was created with correct content
    assert test_file.exists()
    content = test_file.read_text()
    assert "Test job description" in content
    assert "Test cover letter" in content
    assert "Test interview script" in content
    
    # Verify job was removed from matches
    assert len(result["matches"]) == 0
    assert result["matches"] == []
    
    # Verify other state fields were preserved
    assert result["job_title"] == "test"
    assert isinstance(result["scraped_jobs_df"], pd.DataFrame)
    assert result["job_description"] == "Test job description"
    assert result["cover_letter"] == "Test cover letter"
    assert result["call_script"] == "Test interview script"

@patch('src.utils.scrape_upwork_data')
@patch('src.utils.score_scaped_jobs')
@patch('src.utils.convert_jobs_matched_to_string_list')
@patch('src.utils.generate_cover_letter')
@patch('src.utils.generate_interview_script_content')
def test_full_workflow(
    mock_script,
    mock_letter,
    mock_convert,
    mock_score,
    mock_scrape,
    automation,
    sample_jobs_df,
    tmp_path,
    monkeypatch
):
    """Test the full workflow end-to-end"""
    # Setup mocks
    mock_scrape.return_value = sample_jobs_df
    scored_df = sample_jobs_df.copy()
    scored_df["score"] = [8.0]  # Score >= 7 for matching
    mock_score.return_value = scored_df
    mock_convert.return_value = ["Test job match"]
    # Ensure mocks return dictionaries with expected structure
    mock_letter.return_value = {"letter": "Hello, I'm excited about this opportunity... Best, Aymen"}
    mock_script.return_value = {"script": "# Introduction\nHi [Client Name]...\n\n# Key Points\n...\n\n# Client Questions\n...\n\n# Questions to Ask\n..."}
    
    # Set up test file path
    test_file = tmp_path / "cover_letter.txt"
    monkeypatch.setattr("src.graph.COVER_LETTERS_FILE", str(test_file))
    
    # Run the workflow
    final_state = automation.run(job_title="test")
    
    # Verify state was properly maintained
    assert "job_title" in final_state
    assert "scraped_jobs_df" in final_state
    assert "matches" in final_state
    assert "job_description" in final_state
    assert "cover_letter" in final_state
    assert "call_script" in final_state
    assert "num_matches" in final_state
    
    # Verify file was created with correct content
    assert test_file.exists()
    content = test_file.read_text()
    assert "Test job match" in content
    assert "Hello, I'm excited about this opportunity" in content
    assert "# Introduction" in content
    assert "# Key Points" in content
    assert "# Client Questions" in content
    assert "# Questions to Ask" in content
    
    # Verify all steps were called in order
    mock_scrape.assert_called_once()
    mock_score.assert_called_once()
    mock_convert.assert_called_once()
    mock_letter.assert_called_once()
    mock_script.assert_called_once()
    
    # Verify mock calls received correct state
    mock_scrape.assert_called_with("test", automation.number_of_jobs)
    mock_score.assert_called_with(sample_jobs_df, automation.profile)

if __name__ == '__main__':
    pytest.main([__file__])
