import os, re, time, json
import html2text
import pandas as pd
from datetime import datetime
from tqdm import tqdm
from playwright.sync_api import sync_playwright
import google.generativeai as genai
import logging
from .structured_outputs import (
    UpworkJobs,
    JobInformation,
    JobScores,
    CoverLetter,
    CallScript,
)
from .prompts import *

def truncate_content(content, max_length=500):
    """Truncate content for logging purposes"""
    if isinstance(content, str) and len(content) > max_length:
        return content[:max_length] + "... [truncated]"
    return content

def setup_logger(name, level=logging.DEBUG):
    """Centralized logger setup with concise formatting"""
    # Prevent duplicate handlers
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
        
    logger.setLevel(level)
    
    # Create handler
    handler = logging.StreamHandler()
    handler.setLevel(level)
    
    # Create concise formatter
    formatter = logging.Formatter('%(asctime)s.%(msecs)03d [%(name)s] %(levelname).1s: %(message)s', 
                                datefmt='%H:%M:%S')
    handler.setFormatter(formatter)
    
    # Add handler
    logger.addHandler(handler)
    return logger

logger = setup_logger('utils')

SCRAPED_JOBS_FOLDER = "./files/upwork_job_listings/"


def call_gemini_api(
    prompt: str, response_schema=None, model="gemini-2.0-flash-exp", max_retries=5, base_delay=10
) -> tuple:
    logger.info(f"Calling Gemini API with model: {model}")
    
    for attempt in range(max_retries):
        try:
            # Add base delay between API calls to avoid rate limits
            if attempt > 0:
                delay = base_delay * (2 ** (attempt - 1))  # Exponential backoff
                logger.warning(f"API quota exhausted, retrying in {delay} seconds (attempt {attempt + 1}/{max_retries})...")
                time.sleep(delay)
            
            llm = genai.GenerativeModel(model)
            if response_schema is not None:
                if response_schema == UpworkJobs:
                    schema_dict = {
                        "type": "object",
                        "properties": {
                            "jobs": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "link": {"type": "string"}
                                    },
                                    "required": ["link"]
                                }
                            }
                        },
                        "required": ["jobs"]
                    }
                elif response_schema == JobInformation:
                    schema_dict = {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "job_type": {"type": "string", "enum": ["Fixed", "Hourly"]},
                            "experience_level": {"type": "string"},
                            "duration": {"type": "string"},
                            "rate": {"type": "string"},
                            "client_infomation": {"type": "string"}
                        },
                        "required": ["title", "description", "job_type", "experience_level", "duration"]
                    }
                elif response_schema == JobScores:
                    schema_dict = {
                        "type": "object",
                        "properties": {
                            "matches": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "job_id": {"type": "string"},
                                        "score": {"type": "integer"}
                                    },
                                    "required": ["job_id", "score"]
                                }
                            }
                        },
                        "required": ["matches"]
                    }
                elif response_schema == CoverLetter:
                    schema_dict = {
                        "type": "object",
                        "properties": {
                            "letter": {"type": "string"}
                        },
                        "required": ["letter"]
                    }
                elif response_schema == CallScript:
                    schema_dict = {
                        "type": "object",
                        "properties": {
                            "script": {"type": "string"}
                        },
                        "required": ["script"]
                    }
                else:
                    schema_dict = response_schema.model_json_schema()
                    
                    def remove_defs(d):
                        if isinstance(d, dict):
                            if "$defs" in d:
                                del d["$defs"]
                            for k, v in d.items():
                                remove_defs(v)
                        elif isinstance(d, list):
                            for item in d:
                                remove_defs(item)
                    
                    remove_defs(schema_dict)
                
                llm = genai.GenerativeModel(
                    model,
                    generation_config={
                        "response_mime_type": "application/json",
                        "response_schema": schema_dict,
                    },
                )

            completion = llm.generate_content(prompt)
            usage_metadata = completion.usage_metadata
            token_counts = {
                "input_tokens": usage_metadata.prompt_token_count,
                "output_tokens": usage_metadata.candidates_token_count,
            }
            
            try:
                output = json.loads(completion.text)
                # Handle array responses by taking first item
                if isinstance(output, list) and len(output) > 0:
                    output = output[0]
                logger.debug(f"Gemini API response (JSON): {output}")
            except json.JSONDecodeError:
                output = completion.text
                logger.debug(f"Gemini API response (text): {output}")
                
            logger.info("Gemini API call completed.")
            return output, token_counts
            
        except Exception as e:
            if attempt < max_retries - 1:
                if "Resource has been exhausted" in str(e):
                    # Delay is handled at the start of the next iteration
                    continue
                elif "500 An internal error has occurred" in str(e):
                    logger.warning("Internal server error, retrying...")
                    continue
                else:
                    logger.error(f"Unexpected error: {e}")
                    raise e
            else:
                logger.error(f"Failed after {max_retries} attempts: {e}")
                raise e


def read_text_file(filename):
    logger.info(f"Reading text file: {filename}")
    with open(filename, "r", encoding="utf-8") as file:
        lines = file.readlines()
        lines = [line.strip() for line in lines if line.strip()]
        logger.info(f"Text file read: {filename}")
        return "".join(lines)


def scrape_website_to_markdown(url: str) -> str:
    logger.info(f"Scraping website: {url}")
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"

    # Create a cache directory if it doesn't exist
    cache_dir = "./files/cache"
    os.makedirs(cache_dir, exist_ok=True)
    
    # Create a filename based on a hash of the URL
    import hashlib
    url_hash = hashlib.md5(url.encode()).hexdigest()
    filename = os.path.join(cache_dir, f"{url_hash}.md")
    
    # Check if the file exists
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as file:
            logger.debug(f"Markdown content loaded from cache: {filename}")
            return file.read()
    
    # If not, scrape the page
    with sync_playwright() as playwright:
        browser = playwright.firefox.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)

        page = context.new_page()
        page.goto(url)
        html_content = page.content()
        logger.debug(f"HTML content retrieved from {url}")

        browser.close()

    # Convert HTML to markdown
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.ignore_tables = False
    markdown_content = h.handle(html_content)
    logger.debug(f"HTML converted to markdown")

    # Clean up excess newlines
    markdown_content = re.sub(r"\n{3,}", "\n\n", markdown_content)
    markdown_content = markdown_content.strip()
    
    # Save the markdown content to the cache file
    with open(filename, "w", encoding="utf-8") as file:
        file.write(markdown_content)
    logger.debug(f"Markdown content saved to cache: {filename}")

    logger.info(f"Website scraping completed for: {url}")
    return markdown_content


def scrape_upwork_data(search_query, num_jobs=20, rate_limit_delay=5):
    logger.info(f"Scraping Upwork data with query: {search_query}, num_jobs: {num_jobs}")
    url = f"https://www.upwork.com/nx/search/jobs?q={search_query}&sort=recency&page=1&per_page={num_jobs}"

    try:
        markdown_content = scrape_website_to_markdown(url)
        prompt = SCRAPER_PROMPT_TEMPLATE.format(markdown_content=markdown_content)
        completion, _ = call_gemini_api(prompt, UpworkJobs)
        jobs_links_list = [job["link"] for job in completion["jobs"]]
        logger.debug(f"Job links found: {jobs_links_list}")

        jobs_data = []
        for link in tqdm(jobs_links_list, desc="Scraping job pages"):
            try:
                full_link = f"https://www.upwork.com{link}"
                
                # Create cache filename using MD5 hash
                import hashlib
                url_hash = hashlib.md5(full_link.encode()).hexdigest()
                cache_path = os.path.join("./files/cache", f"{url_hash}.md")
                
                job_page_content = scrape_website_to_markdown(full_link)
                prompt = SCRAPER_PROMPT_TEMPLATE.format(markdown_content=job_page_content)
                completion, _ = call_gemini_api(prompt, JobInformation)
                
                if isinstance(completion, dict):
                    jobs_data.append(completion)
                    logger.debug(f"Job data scraped for link: {full_link}")
                else:
                    logger.error(f"Error: Invalid response from Gemini API for job info: {completion}")
                
                # Always add a small delay between jobs to avoid rate limits
                time.sleep(rate_limit_delay)
                    
            except Exception as e:
                logger.error(f"Error processing link {link}: {e}")
                continue  # Skip failed jobs but continue processing others

        if not jobs_data:
            logger.warning("No valid job data was collected")
            return pd.DataFrame()  # Return empty DataFrame if no jobs were scraped

        jobs_df = process_job_info_data(jobs_data)
        logger.info(f"Upwork data scraping completed for query: {search_query}")
        return jobs_df

    except Exception as e:
        logger.error(f"Error scraping Upwork data: {e}")
        return pd.DataFrame()  # Return empty DataFrame on error


def process_job_info_data(jobs_data):
    logger.info("Processing job info data")
    def clean_client_info(text):
        if pd.isna(text):
            return text

        cleaned = (
            text.replace("\n\n", " | ")
            .replace("\n", " ")
            .replace("***", "")
            .replace("**", "")
            .replace("*", "")
            .strip()
        )

        # Remove multiple spaces
        cleaned = re.sub(r"\s+", " ", cleaned)
        # Remove multiple separators
        cleaned = re.sub(r"\|\s*\|", "|", cleaned)
        # Clean up spaces around separators
        cleaned = re.sub(r"\s*\|\s*", " | ", cleaned)

        return cleaned.strip()

    jobs_df = pd.DataFrame(jobs_data)
    # Explicitly create the 'rate' column if it doesn't exist
    if "rate" not in jobs_df.columns:
        jobs_df["rate"] = ""
    jobs_df["rate"] = jobs_df["rate"].astype(str).str.replace(
        r"\$?(\d+\.?\d*)\s*\n*-\n*\$?(\d+\.?\d*)", r"$\1-$\2", regex=True
    )
    # Explicitly create the 'client_infomation' column if it doesn't exist
    if "client_infomation" not in jobs_df.columns:
        jobs_df["client_infomation"] = ""
    # Explicitly create the 'experience_level' column if it doesn't exist
    if "experience_level" not in jobs_df.columns:
        jobs_df["experience_level"] = ""
    # Explicitly create the 'duration' column if it doesn't exist
    if "duration" not in jobs_df.columns:
        jobs_df["duration"] = ""
    # Explicitly create the 'job_id' column if it doesn't exist
    if "job_id" not in jobs_df.columns:
        jobs_df["job_id"] = jobs_df.index.astype(str)
    jobs_df["client_infomation"] = jobs_df["client_infomation"].astype(str).apply(clean_client_info)
    logger.info("Job info data processed")

    return jobs_df


def score_scaped_jobs(jobs_df, profile):
    logger.info("Scoring scraped jobs")
    
    # Convert jobs DataFrame to list of dictionaries
    jobs_dict_list = []
    for index, row in jobs_df.iterrows():
        # Use existing job_id if present, otherwise use index
        job_id = str(row.get("job_id", index))
        job_dict = {
            "job_id": job_id,
            "title": row.get("title", ""),
            "experience_level": row.get("experience_level", ""),
            "job_type": row.get("job_type", ""),
            "duration": row.get("duration", ""),
            "rate": row.get("rate", ""),
            "description": row.get("description", ""),
            "client_infomation": row.get("client_infomation", "")
        }
        jobs_dict_list.append(job_dict)

    # Process jobs in batches of 5
    jobs_list = [jobs_dict_list[i : i + 5] for i in range(0, len(jobs_dict_list), 5)]

    # Score each batch of jobs
    jobs_final_score = []
    for jobs_batch in jobs_list:
        # Format jobs data for the prompt
        formatted_jobs = []
        for job in jobs_batch:
            formatted_job = {
                "id": job["job_id"],
                "title": job["title"],
                "details": {
                    "experience_level": job["experience_level"],
                    "job_type": job["job_type"],
                    "duration": job["duration"],
                    "rate": job["rate"],
                    "description": job["description"],
                    "client_infomation": job["client_infomation"]
                }
            }
            formatted_jobs.append(formatted_job)

        # Create the prompt with formatted jobs data
        score_jobs_prompt = SCORE_JOBS_PROMPT_TEMPLATE.format(
            profile=profile,
            jobs=json.dumps(formatted_jobs, indent=2)
        )
        logger.debug(f"Jobs data being passed to the template: {json.dumps(formatted_jobs, indent=2)}")
        
        try:
            completion, _ = call_gemini_api(score_jobs_prompt, JobScores)
            logger.debug(f"Response from Gemini API: {completion}")
            
            if isinstance(completion, dict) and "matches" in completion:
                matches = completion.get("matches", [])
                if isinstance(matches, list):
                    # Validate each match has required fields
                    valid_matches = []
                    for match in matches:
                        if (isinstance(match, dict) 
                            and "job_id" in match 
                            and "score" in match
                            and isinstance(match["score"], (int, float))
                            and 1 <= match["score"] <= 10):
                            valid_matches.append({
                                "job_id": str(match["job_id"]),
                                "score": float(match["score"])  # Convert score to float
                            })
                    jobs_final_score.extend(valid_matches)
                    logger.debug(f"Valid scores from Gemini API: {valid_matches}")
                else:
                    logger.error(f"Error: 'matches' is not a list: {matches}")
            else:
                logger.error(f"Error: Invalid response format from Gemini API: {completion}")
        except Exception as e:
            logger.error(f"Error scoring jobs batch: {e}")
            continue

    # Create scores DataFrame and merge with jobs_df
    if jobs_final_score:
        scores_df = pd.DataFrame(jobs_final_score)
        scores_df["job_id"] = scores_df["job_id"].astype(str)  # Ensure job_id is string
        scores_df["score"] = scores_df["score"].astype(float)  # Ensure score is float64
        
        # Create score column if it doesn't exist
        if "score" not in jobs_df.columns:
            jobs_df["score"] = 0.0  # Initialize as float
        
        # Update scores using job_id mapping
        score_dict = dict(zip(scores_df["job_id"], scores_df["score"]))
        jobs_df["score"] = jobs_df["job_id"].map(score_dict).fillna(0.0).astype(float)
    
    logger.info("Scoring of scraped jobs completed")
    return jobs_df


def convert_jobs_matched_to_string_list(jobs_matched):
    logger.info("Converting matched jobs to string list")
    jobs = []
    for _, row in jobs_matched.iterrows():
        job = f"Title: {row['title']}\n"
        job += f"Description:\n{row['description']}\n"
        jobs.append(job)
    logger.info("Matched jobs converted to string list")
    return jobs


def generate_cover_letter(job_desc, profile):
    logger.info("Generating cover letter")
    cover_letter_prompt = GENERATE_COVER_LETTER_PROMPT_TEMPLATE.format(
        profile=profile, job_description=job_desc
    )
    completion, _ = call_gemini_api(cover_letter_prompt, CoverLetter)
    logger.info("Cover letter generated")
    return {"letter": completion["letter"]}


def generate_interview_script_content(job_desc):
    logger.info("Generating interview script content")
    call_script_writer_prompt = GENERATE_CALL_SCRIPT_PROMPT_TEMPLATE.format(
        job_description=job_desc
    )
    completion, _ = call_gemini_api(call_script_writer_prompt, CallScript)
    logger.info("Interview script content generated")
    return {"script": completion["script"]}


def save_scraped_jobs_to_csv(scraped_jobs_df):
    logger.info("Saving scraped jobs to CSV")
    os.makedirs(SCRAPED_JOBS_FOLDER, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{SCRAPED_JOBS_FOLDER}scraped_jobs_{date_str}.csv"
    scraped_jobs_df.to_csv(filename, index=False)
    logger.info(f"Scraped jobs saved to CSV: {filename}")
