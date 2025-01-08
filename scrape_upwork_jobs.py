from src.utils import scrape_upwork_data, setup_logger, truncate_content

logger = setup_logger('scrape_upwork_jobs')

if __name__ == "__main__":
    logger.info("Starting Upwork job scraping")
    search_query = "AI agent developer"
    number_of_jobs = 10
    job_listings = scrape_upwork_data(search_query, number_of_jobs)
    logger.debug(f"Job listings: {truncate_content(str(job_listings))}")
    print(job_listings)
    logger.info("Upwork job scraping completed")
