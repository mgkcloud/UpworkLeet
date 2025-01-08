import os
from dotenv import load_dotenv
from src.utils import read_text_file
from src.graph import UpworkAutomation
import google.generativeai as genai
import logging

def setup_logger(name, level=logging.DEBUG):
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Create handlers
    c_handler = logging.StreamHandler()
    c_handler.setLevel(level)

    # Create formatters and add it to handlers
    c_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    c_handler.setFormatter(c_format)

    # Add handlers to the logger
    logger.addHandler(c_handler)
    return logger

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
    logger.debug(f"Freelancer profile loaded: {profile}")

    # run automation
    automation = UpworkAutomation(profile)
    automation.run(job_title=job_title)
    logger.info("Upwork automation completed")
