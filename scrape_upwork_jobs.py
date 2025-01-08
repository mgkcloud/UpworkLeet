import logging
from src.utils import scrape_upwork_data

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

logger = setup_logger('scrape_upwork_jobs')

if __name__ == "__main__":
    logger.info("Starting Upwork job scraping")
    search_query = "AI agent developer"
    number_of_jobs = 10
    job_listings = scrape_upwork_data(search_query, number_of_jobs)
    logger.debug(f"Job listings: {job_listings}")
    print(job_listings)
    logger.info("Upwork job scraping completed")
