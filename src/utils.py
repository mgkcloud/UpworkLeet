import os, re, time, json, hashlib
import html2text
import pandas as pd
from datetime import datetime
from tqdm import tqdm
from playwright.sync_api import sync_playwright
import google.generativeai as genai
import logging
from typing import List, Optional
from .structured_outputs import (
    UpworkJobs,
    JobInformation,
    JobScores,
    CoverLetter,
    CallScript,
    Questions,
    Answers,
)
from .prompts import *

# Initialize Gemini API
api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
    raise ValueError("GOOGLE_API_KEY environment variable is required")
genai.configure(api_key=api_key)

def truncate_content(content, max_length=200):
    """Truncate content for logging purposes"""
    if isinstance(content, str) and len(content) > max_length:
        return content[:max_length] + "..."
    elif isinstance(content, dict):
        return {k: truncate_content(v) for k, v in content.items()}
    elif isinstance(content, list):
        return [truncate_content(item) for item in content]
    return content

def setup_logger(name, level=logging.INFO):
    """Centralized logger setup with concise formatting"""
    # Prevent duplicate handlers
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
        
    logger.setLevel(level)
    
    # Create handler
    handler = logging.StreamHandler()
    handler.setLevel(level)
    
    # Create minimal formatter
    formatter = logging.Formatter('%(asctime)s [%(name)s] %(levelname).1s: %(message)s', 
                                datefmt='%H:%M:%S')
    handler.setFormatter(formatter)
    
    # Add handler
    logger.addHandler(handler)
    return logger

logger = setup_logger('utils')

SCRAPED_JOBS_FOLDER = "./files/upwork_job_listings/"

def load_cookies():
    """Load authentication cookies from file"""
    cookie_file = "./files/auth/cookies.json"
    try:
        if os.path.exists(cookie_file):
            with open(cookie_file, 'r') as f:
                return json.load(f)
        else:
            logger.warning(f"Cookie file not found at {cookie_file}")
            return []
    except Exception as e:
        logger.error(f"Error loading cookies: {e}")
        return []

def save_cookies(cookies):
    """Save authentication cookies to file"""
    cookie_file = "./files/auth/cookies.json"
    os.makedirs(os.path.dirname(cookie_file), exist_ok=True)
    try:
        with open(cookie_file, 'w') as f:
            json.dump(cookies, f, indent=2)
        logger.info(f"Cookies saved to {cookie_file}")
    except Exception as e:
        logger.error(f"Error saving cookies: {e}")

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
                logger.debug(f"API response: {truncate_content(output)}")
            except json.JSONDecodeError:
                output = completion.text
                logger.debug(f"API response: {truncate_content(output)}")
                
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

    # Determine cache directory based on URL type
    if "/apply/" in url:
        cache_dir = "./files/cache/apply_pages"
    else:
        cache_dir = "./files/cache/search_pages"
    os.makedirs(cache_dir, exist_ok=True)
    
    # Create a filename based on a hash of the URL
    url_hash = hashlib.md5(url.encode()).hexdigest()
    filename = os.path.join(cache_dir, f"{url_hash}.md")
    
    # Check if the file exists
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as file:
            logger.debug(f"Using cached content: {filename}")
            return file.read()
    
    # If not, scrape the page
    with sync_playwright() as playwright:
        browser = playwright.firefox.launch(headless=True)
        
        # Set up context with authentication cookies for Upwork
        context = browser.new_context(user_agent=USER_AGENT)
        
        # Load and add authentication cookies
        cookies = load_cookies()
        if cookies:
            context.add_cookies(cookies)
        else:
            logger.warning("No authentication cookies found")

        page = context.new_page()
        
        try:
            # Navigate to the URL and wait for the page to load
            response = page.goto(url, wait_until="networkidle")
            if response.status == 401 or response.status == 403:
                logger.error(f"Authentication failed for URL: {url}")
                return ""
                
            # Wait for any dynamic content to load
            page.wait_for_load_state("networkidle")
            
            # Get the page content
            html_content = page.content()
            logger.debug(f"Retrieved content from {url}")
            
            # If this is the first successful request, save the cookies for future use
            if not cookies:
                new_cookies = context.cookies()
                save_cookies(new_cookies)
            
        except Exception as e:
            logger.error(f"Error scraping URL {url}: {str(e)}")
            return ""
        finally:
            browser.close()

    # Convert HTML to markdown
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.ignore_tables = False
    markdown_content = h.handle(html_content)

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
        logger.debug(f"Found {len(jobs_links_list)} job links")

        jobs_data = []
        for link in tqdm(jobs_links_list, desc="Scraping job pages"):
            try:
                full_link = f"https://www.upwork.com{link}"
                
                # Create cache filename using MD5 hash
                url_hash = hashlib.md5(full_link.encode()).hexdigest()
                cache_path = os.path.join("./files/cache/search_pages", f"{url_hash}.md")
                
                job_page_content = scrape_website_to_markdown(full_link)
                prompt = SCRAPER_PROMPT_TEMPLATE.format(markdown_content=job_page_content)
                completion, _ = call_gemini_api(prompt, JobInformation)
                
                if isinstance(completion, dict):
                    # Extract Upwork job ID from URL
                    job_id_match = re.search(r'_~([^/]+)/', full_link)
                    if job_id_match:
                        upwork_id = job_id_match.group(1)
                        completion['url'] = full_link  # Add the full URL to the job data
                        completion['apply_url'] = f"https://www.upwork.com/nx/proposals/job/~{upwork_id}/apply/"  # Add apply URL
                        completion['upwork_id'] = upwork_id  # Store the Upwork ID for matching
                        logger.debug(f"Extracted Upwork ID: {upwork_id}")
                    else:
                        logger.warning(f"Could not extract Upwork ID from URL: {full_link}")
                    jobs_data.append(completion)
                    logger.debug(f"Scraped job: {truncate_content(completion.get('title', 'Unknown'))}")
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
        logger.debug(f"Processing batch of {len(formatted_jobs)} jobs")
        
        try:
            completion, _ = call_gemini_api(score_jobs_prompt, JobScores)
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
                                "score": float(match["score"])
                            })
                    jobs_final_score.extend(valid_matches)
                    logger.debug(f"Scored {len(valid_matches)} jobs")
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
    try:
        logger.debug(f"Job description length: {len(job_desc)}")
        logger.debug(f"Profile length: {len(profile)}")
        
        cover_letter_prompt = GENERATE_COVER_LETTER_PROMPT_TEMPLATE.format(
            profile=profile, job_description=job_desc
        )
        logger.debug("Generated cover letter prompt")
        
        completion, _ = call_gemini_api(cover_letter_prompt, CoverLetter)
        logger.debug(f"Gemini API response: {truncate_content(str(completion))}")
        
        if not isinstance(completion, dict) or "letter" not in completion:
            logger.error(f"Invalid cover letter response format: {completion}")
            return {"letter": "Error generating cover letter"}
            
        logger.info("Cover letter generated successfully")
        return {"letter": completion["letter"]}
    except Exception as e:
        logger.error(f"Error generating cover letter: {truncate_content(str(e))}")
        return {"letter": f"Error generating cover letter: {str(e)}"}


def scrape_job_questions(apply_url: str) -> dict:
    """Scrape additional questions from the job application page"""
    logger.info(f"Scraping questions from: {apply_url}")
    try:
        # Use special handling for apply pages
        with sync_playwright() as playwright:
            browser = playwright.firefox.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
            )

            # Load and add authentication cookies
            cookies = load_cookies()
            if cookies:
                context.add_cookies(cookies)
            else:
                logger.warning("No authentication cookies found")

            page = context.new_page()
            page.goto(apply_url, wait_until="networkidle")
            
            # Wait for application form to load
            page.wait_for_selector("form", timeout=10000)
            html_content = page.content()
            logger.debug(f"Retrieved content from {apply_url}")

            browser.close()

        # Convert HTML to markdown with special handling for forms
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.ignore_tables = False
        h.body_width = 0  # Don't wrap lines
        markdown_content = h.handle(html_content)

        # Save to apply pages cache
        cache_dir = "./files/cache/apply_pages"
        os.makedirs(cache_dir, exist_ok=True)
        url_hash = hashlib.md5(apply_url.encode()).hexdigest()
        cache_path = os.path.join(cache_dir, f"{url_hash}.md")
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        logger.debug(f"Apply page content saved to cache: {cache_path}")

        # Extract questions using dedicated prompt
        prompt = SCRAPE_QUESTIONS_PROMPT_TEMPLATE.format(markdown_content=markdown_content)
        completion, _ = call_gemini_api(prompt, None)  # Don't use schema validation for questions
        
        if isinstance(completion, dict):
            questions = completion.get("questions", [])
            logger.debug(f"Found {len(questions)} questions")
            # Convert to expected format
            formatted_questions = []
            for q in questions:
                if isinstance(q, dict) and "text" in q:
                    formatted_questions.append({
                        "text": q["text"],
                        "type": q.get("type", "text"),
                        "options": q.get("options", []) if q.get("type") == "multiple_choice" else None
                    })
            return {"questions": formatted_questions}
        else:
            logger.warning("No questions found in apply page")
            return {"questions": []}
            
    except Exception as e:
        logger.error(f"Error scraping questions: {truncate_content(str(e))}")
        return {"questions": []}

def generate_question_answers(job_data: dict, questions: List[dict]) -> dict:
    """Generate answers for job application questions"""
    logger.info("Generating answers for application questions")
    try:
        # Read background information
        with open("files/background/technical_experience.md", "r") as f:
            technical_background = f.read()
        with open("files/background/work_approach.md", "r") as f:
            work_approach = f.read()
            
        prompt = ANSWER_QUESTIONS_PROMPT_TEMPLATE.format(
            job_description=job_data["description"],
            technical_background=technical_background,
            work_approach=work_approach,
            questions=json.dumps(questions, indent=2)
        )
        
        completion, _ = call_gemini_api(prompt, Answers)
        if isinstance(completion, dict) and "answers" in completion:
            logger.debug(f"Generated {len(completion['answers'])} answers")
            return completion
        else:
            logger.error(f"Invalid answer response format: {completion}")
            return {"answers": []}
            
    except Exception as e:
        logger.error(f"Error generating answers: {truncate_content(str(e))}")
        return {"answers": []}

def generate_interview_script_content(job_desc):
    logger.info("Generating interview script content")
    try:
        logger.debug(f"Job description length: {len(job_desc)}")
        
        # Read background information
        with open("files/background/technical_experience.md", "r") as f:
            technical_background = f.read()
        with open("files/background/work_approach.md", "r") as f:
            work_approach = f.read()
        
        call_script_writer_prompt = GENERATE_CALL_SCRIPT_PROMPT_TEMPLATE.format(
            job_description=job_desc,
            technical_background=technical_background,
            work_approach=work_approach
        )
        logger.debug("Generated interview script prompt")
        
        completion, _ = call_gemini_api(call_script_writer_prompt, CallScript)
        logger.debug(f"Gemini API response: {truncate_content(str(completion))}")
        
        if not isinstance(completion, dict) or "script" not in completion:
            logger.error(f"Invalid interview script response format: {completion}")
            return {"script": "Error generating interview script"}
            
        logger.info("Interview script generated successfully")
        return {"script": completion["script"]}
    except Exception as e:
        logger.error(f"Error generating interview script: {truncate_content(str(e))}")
        return {"script": f"Error generating interview script: {str(e)}"}


def save_scraped_jobs_to_csv(scraped_jobs_df):
    logger.info("Saving scraped jobs to CSV")
    os.makedirs(SCRAPED_JOBS_FOLDER, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{SCRAPED_JOBS_FOLDER}scraped_jobs_{date_str}.csv"
    scraped_jobs_df.to_csv(filename, index=False)
    logger.info(f"Scraped jobs saved to CSV: {filename}")
