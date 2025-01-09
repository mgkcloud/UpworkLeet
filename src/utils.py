import os, re, time, json, hashlib
import html2text
import pandas as pd
from datetime import datetime
from tqdm import tqdm
from playwright.sync_api import sync_playwright
import google.generativeai as genai
import logging
from typing import List, Optional
from dataclasses import dataclass

@dataclass
class TurnstileResult:
    turnstile_value: Optional[str]
    elapsed_time_seconds: float
    status: str
    reason: Optional[str] = None

class TurnstileSolver:
    HTML_TEMPLATE = """
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>Turnstile Solver</title>
        <script
          src="https://challenges.cloudflare.com/turnstile/v0/api.js?onload=onloadTurnstileCallback"
          async=""
          defer=""
        ></script>
      </head>
      <body>
        <!-- cf turnstile -->
      </body>
    </html>
    """

    def __init__(self, debug: bool = False):
        self.debug = debug
        self.log = logger  # Use existing logger
        self.browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--window-position=2000,2000",
        ]

    def _setup_page(self, context, url: str, sitekey: str):
        """Set up the page with Turnstile widget."""
        page = context.new_page()
        url_with_slash = url + "/" if not url.endswith("/") else url
        
        if self.debug:
            self.log.debug(f"Navigating to URL: {url_with_slash}")

        turnstile_div = f'<div class="cf-turnstile" data-sitekey="{sitekey}"></div>'
        page_data = self.HTML_TEMPLATE.replace("<!-- cf turnstile -->", turnstile_div)
        
        page.route(url_with_slash, lambda route: route.fulfill(body=page_data, status=200))
        page.goto(url_with_slash)
        
        if self.debug:
            self.log.debug("Getting window dimensions.")
        page.window_width = page.evaluate("window.innerWidth")
        page.window_height = page.evaluate("window.innerHeight")
        
        return page

    def _get_turnstile_response(self, page, max_attempts: int = 10) -> Optional[str]:
        """Attempt to retrieve Turnstile response."""
        attempts = 0
        
        if self.debug:
            self.log.debug("Starting Turnstile response retrieval loop.")
        
        while attempts < max_attempts:
            turnstile_check = page.eval_on_selector(
                "[name=cf-turnstile-response]", 
                "el => el.value"
            )

            if turnstile_check == "":
                if self.debug:
                    self.log.debug(f"Attempt {attempts + 1}: No Turnstile response yet.")
                
                # Calculate click position based on window dimensions
                x = page.window_width // 2
                y = page.window_height // 2
                
                page.evaluate("document.querySelector('.cf-turnstile').style.width = '70px'")
                page.mouse.click(x, y)
                time.sleep(0.5)
                attempts += 1
            else:
                turnstile_element = page.query_selector("[name=cf-turnstile-response]")
                if turnstile_element:
                    value = turnstile_element.get_attribute("value")
                    if self.debug:
                        self.log.debug(f"Turnstile response received: {value}")
                    return value
                break
        
        return None

    def solve(self, url: str, sitekey: str, headless: bool = False) -> TurnstileResult:
        """
        Solve the Turnstile challenge and return the result.
        
        Args:
            url: The URL where the Turnstile challenge is hosted
            sitekey: The Turnstile sitekey
            headless: Whether to run the browser in headless mode
            
        Returns:
            TurnstileResult object containing the solution details
        """
        start_time = time.time()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless, args=self.browser_args)
            context = browser.new_context()

            try:
                page = self._setup_page(context, url, sitekey)
                turnstile_value = self._get_turnstile_response(page)
                
                elapsed_time = round(time.time() - start_time, 3)
                
                if not turnstile_value:
                    result = TurnstileResult(
                        turnstile_value=None,
                        elapsed_time_seconds=elapsed_time,
                        status="failure",
                        reason="Max attempts reached without token retrieval"
                    )
                    self.log.error("Failed to retrieve Turnstile value.")
                else:
                    result = TurnstileResult(
                        turnstile_value=turnstile_value,
                        elapsed_time_seconds=elapsed_time,
                        status="success"
                    )
                    self.log.info(
                        f"Successfully solved captcha: {turnstile_value[:45]}..."
                    )

            finally:
                context.close()
                browser.close()

                if self.debug:
                    self.log.debug(f"Elapsed time: {result.elapsed_time_seconds} seconds")
                    self.log.debug("Browser closed. Returning result.")

        return result

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


def check_for_challenge(page, timeout=10):
    """Check if we're on a Cloudflare challenge page"""
    logger.info("Checking for Cloudflare challenge...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            # Check for challenge title
            title = page.title()
            if "Just a moment..." in title:
                logger.info("Found Cloudflare challenge page")
                return True
                
            # Check for challenge iframe
            if page.locator('iframe[src*="challenges.cloudflare.com"]').count() > 0:
                logger.info("Found Cloudflare challenge iframe")
                return True
                
        except Exception as e:
            logger.error(f"Error checking for challenge: {str(e)}")
            return False
            
        time.sleep(0.5)
    logger.info("No Cloudflare challenge detected")
    return False

def solve_challenge(page):
    """Solve Cloudflare challenge using TurnstileSolver"""
    try:
        # Extract sitekey from URL
        sitekey = None
        url_params = page.evaluate("""() => {
            const iframe = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
            return iframe ? new URL(iframe.src).searchParams.get('sitekey') : null;
        }""")
        
        if not url_params:
            logger.error("Could not find sitekey")
            return False
            
        sitekey = url_params
        logger.info(f"Found sitekey: {sitekey}")
        
        # Solve challenge
        solver = TurnstileSolver(debug=True)
        result = solver.solve(url=page.url, sitekey=sitekey, headless=False)
        
        if result.status != "success":
            logger.error("Failed to solve challenge")
            return False
            
        # Apply solution to original page
        success = page.evaluate("""
            token => {
                const input = document.querySelector('[name="cf-turnstile-response"]');
                if (input) {
                    input.value = token;
                    const form = input.closest('form');
                    if (form) {
                        form.submit();
                        return true;
                    }
                }
                return false;
            }
        """, result.turnstile_value)
        
        if not success:
            logger.error("Failed to apply solution")
            return False
            
        # Wait for navigation
        logger.info("Waiting for page to load after solution...")
        time.sleep(3)  # Give time for form submission
        
        # Check if we're past the challenge
        if "Just a moment..." not in page.title():
            logger.info("Successfully bypassed Cloudflare challenge")
            return True
            
        logger.warning("Still on challenge page after solution")
        return False
        
    except Exception as e:
        logger.error(f"Error solving challenge: {str(e)}")
        return False

def scrape_job_questions(apply_url: str) -> dict:
    """Scrape additional questions from the job application page"""
    logger.info(f"Scraping questions from: {apply_url}")
    try:
        # Use special handling for apply pages
        with sync_playwright() as playwright:
            # Launch browser with anti-detection arguments
            browser = playwright.chromium.launch(
                headless=False,  # Show browser for better challenge handling
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-background-networking",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--window-position=2000,2000",
                ]
            )
            
            # Set up context with realistic user agent
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
            )

            # Load and verify authentication cookies
            cookies = load_cookies()
            if not cookies:
                logger.error("No authentication cookies found")
                return {"questions": []}
                
            # Verify required cookies are present
            required_cookies = [
                'master_access_token',
                'oauth2_global_js_token',
                'XSRF-TOKEN',
                'console_user',
                'user_uid',
                'recognized'
            ]
            cookie_names = {cookie['name'] for cookie in cookies}
            missing_cookies = set(required_cookies) - cookie_names
            if missing_cookies:
                logger.error(f"Missing required cookies: {missing_cookies}")
                return {"questions": []}
                
            context.add_cookies(cookies)
            page = context.new_page()
            
            # Navigate to apply page with proper error handling
            try:
                response = page.goto(apply_url, wait_until="networkidle", timeout=30000)
                if response.status == 401 or response.status == 403:
                    logger.error(f"Authentication failed for URL: {apply_url}")
                    return {"questions": []}
            except Exception as e:
                logger.error(f"Error navigating to {apply_url}: {str(e)}")
                return {"questions": []}
                
            # Check for and handle Cloudflare challenge
            if check_for_challenge(page):
                logger.info("Detected Cloudflare challenge...")
                if not solve_challenge(page):
                    logger.error("Failed to bypass Cloudflare challenge")
                    return {"questions": []}
            
            # Wait for page to fully load and stabilize
            page.wait_for_load_state("networkidle", timeout=30000)
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            
            # Wait for either questions area or cover letter section
            try:
                # First wait for the cover letter section which is always present
                page.wait_for_selector(".air3-card-outline", timeout=15000)
                
                # Then check for questions area
                questions_area = page.locator(".fe-proposal-job-questions")
                if questions_area.count() > 0:
                    # Wait for all question elements to be loaded
                    questions_area.wait_for(timeout=10000)
                    
                    # Extract questions directly using Playwright
                    questions = []
                    question_elements = questions_area.locator(".form-group")
                    count = question_elements.count()
                    
                    for i in range(count):
                        element = question_elements.nth(i)
                        label = element.locator(".label").text_content()
                        if label:
                            label = label.strip()
                            questions.append({
                                "text": label,
                                "type": "text"  # Default to text type
                            })
                    
                    logger.info(f"Found {len(questions)} questions using direct extraction")
                    return {"questions": questions}
                else:
                    logger.info("No questions found in apply page (cover letter only)")
                    return {"questions": []}
                    
            except Exception as e:
                logger.error(f"Error waiting for page elements: {str(e)}")
                return {"questions": []}
            
            # Get full page content as backup
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

def generate_question_answers(job_description: str, questions: List[dict]) -> dict:
    """Generate answers for job application questions"""
    logger.info("Generating answers for application questions")
    try:
        # Read background information
        with open("files/background/technical_experience.md", "r") as f:
            technical_background = f.read()
        with open("files/background/work_approach.md", "r") as f:
            work_approach = f.read()
            
        # Format questions for prompt
        formatted_questions = []
        for q in questions:
            question_type = q.get("type", "text")
            question_data = {
                "text": q["text"],
                "type": question_type
            }
            if question_type == "multiple_choice" and "options" in q:
                question_data["options"] = q["options"]
            formatted_questions.append(question_data)
            
        prompt = ANSWER_QUESTIONS_PROMPT_TEMPLATE.format(
            job_description=job_description,
            technical_background=technical_background,
            work_approach=work_approach,
            questions=json.dumps(formatted_questions, indent=2)
        )
        
        completion, _ = call_gemini_api(prompt, None)  # Don't use schema validation for flexibility
        
        # Handle potential markdown code block wrapping
        if isinstance(completion, str) and "```json" in completion:
            # Extract JSON from markdown code block
            json_str = completion.split("```json")[1].split("```")[0].strip()
            try:
                completion = json.loads(json_str)
            except json.JSONDecodeError:
                logger.error("Failed to parse JSON from markdown response")
                return {"answers": []}
                
        if isinstance(completion, dict) and "answers" in completion:
            answers = completion["answers"]
            # Validate and format each answer
            formatted_answers = []
            for answer, question in zip(answers, questions):
                if isinstance(answer, dict) and "answer" in answer:
                    formatted_answer = {
                        "question": question["text"],  # Use original question text
                        "answer": answer["answer"],
                        "type": question.get("type", "text")  # Use original question type
                    }
                    formatted_answers.append(formatted_answer)
            
            if formatted_answers:
                logger.debug(f"Generated {len(formatted_answers)} answers")
                return {"answers": formatted_answers}
            
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
