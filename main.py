import os
from dotenv import load_dotenv
from src.utils import read_text_file, setup_logger, truncate_content
from src.graph import UpworkAutomation
import google.generativeai as genai

logger = setup_logger('main')

# Load environment variables from a .env file
load_dotenv()

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

if __name__ == "__main__":
    logger.info("Starting Upwork automation")
    # Job title to look for
    job_title = "AI agent Developer"

    # load the freelancer profile
    profile = read_text_file("./files/profile.md")
    logger.debug(f"Freelancer profile loaded: {truncate_content(profile)}")

    # run automation
    automation = UpworkAutomation(profile)
    automation.run(job_title=job_title)
    logger.info("Upwork automation completed")
