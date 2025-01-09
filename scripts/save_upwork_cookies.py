#!/usr/bin/env python3
"""
Script to save Upwork authentication cookies from a browser session.
Run this script when you need to update the authentication cookies.
"""

import os
import json
import time
import logging
import argparse
from patchright.sync_api import sync_playwright
from twocaptcha import TwoCaptcha
from logmagix import Logger, Loader
from dataclasses import dataclass
from typing import Optional, List, Dict

# Set up logging
logger = Logger()
loader = Loader(desc="Processing...", timeout=0.05)

# Required cookies that indicate successful login
REQUIRED_COOKIES = [
    'master_access_token',
    'oauth2_global_js_token',
    'XSRF-TOKEN',
    'console_user',
    'user_uid',
    'recognized'
]

def verify_cookies(cookies: List[Dict]) -> bool:
    """Verify all required cookies are present and have values"""
    cookie_names = {cookie['name'] for cookie in cookies}
    missing_cookies = set(REQUIRED_COOKIES) - cookie_names
    
    if missing_cookies:
        logger.error(f"Missing required cookies: {missing_cookies}")
        return False
        
    # Check that required cookies have values
    for cookie in cookies:
        if cookie['name'] in REQUIRED_COOKIES and not cookie['value']:
            logger.error(f"Cookie {cookie['name']} has no value")
            return False
            
    return True

def check_login_success(page) -> bool:
    """Check if login was successful by verifying we're on a logged-in page"""
    try:
        # Wait for either the dashboard or find work page to load
        success_selectors = [
            'a[href="/nx/find-work"]',  # Find Work link in nav
            'a[href="/nx/workspace"]',   # My Jobs link in nav
            '.up-sidebar',               # Sidebar that's present on most logged-in pages
            '[data-qa="user-menu"]'      # User menu in header
        ]
        
        # Try each selector
        for selector in success_selectors:
            if page.locator(selector).count() > 0:
                logger.info(f"Found logged-in indicator: {selector}")
                return True
                
        # Check URL
        current_url = page.url
        if any(path in current_url for path in ['/nx/find-work', '/nx/workspace', '/home']):
            logger.info(f"On logged-in page: {current_url}")
            return True
            
        logger.error("Could not verify successful login")
        return False
        
    except Exception as e:
        logger.error(f"Error checking login success: {str(e)}")
        return False

def save_cookies_to_file(cookies: List[Dict], file_path: str):
    """Save cookies to file, creating directories if needed"""
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w') as f:
            json.dump(cookies, f, indent=2)
        logger.info(f"Cookies saved to {file_path}")
        return True
    except Exception as e:
        logger.error(f"Error saving cookies: {str(e)}")
        return False

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
        self.log = Logger()
        self.loader = Loader(desc="Solving captcha...", timeout=0.05)
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
        self.loader.start()
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
                    self.log.failure("Failed to retrieve Turnstile value.")
                else:
                    result = TurnstileResult(
                        turnstile_value=turnstile_value,
                        elapsed_time_seconds=elapsed_time,
                        status="success"
                    )
                    self.log.message(
                        "Cloudflare",
                        f"Successfully solved captcha: {turnstile_value[:45]}...",
                        start=start_time,
                        end=time.time()
                    )

            finally:
                context.close()
                browser.close()
                self.loader.stop()

                if self.debug:
                    self.log.debug(f"Elapsed time: {result.elapsed_time_seconds} seconds")
                    self.log.debug("Browser closed. Returning result.")

        return result

def solve_challenge(page, api_key):
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

def check_for_challenge(page, timeout=10):
    """Check if we're on a challenge page"""
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

def wait_for_password_field(page, timeout=30):
    """Wait for password field to become visible"""
    logger.info("Waiting for password field...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            if page.locator('#login_password').is_visible():
                logger.info("Password field is visible")
                return True
            if check_for_challenge(page):
                logger.info("Challenge detected while waiting for password field")
                return False
        except Exception as e:
            logger.error(f"Error checking password field: {str(e)}")
            return False
        time.sleep(1)
    logger.error("Timeout waiting for password field")
    return False

def handle_login_flow(page, email, password):
    """Handle the login flow including Cloudflare challenges"""
    try:
        # Wait for username field and enter email
        logger.info("Looking for username field...")
        username_input = page.wait_for_selector('#login_username', timeout=10000)
        if not username_input:
            logger.error("Could not find username input")
            return False
            
        logger.info("Entering email...")
        # Type the email character by character
        username_input.type(email, delay=100)
        
        # Find and click the continue button
        logger.info("Looking for continue button...")
        continue_button = page.wait_for_selector('#login_password_continue', timeout=10000)
        if not continue_button:
            logger.error("Could not find continue button")
            return False
            
        logger.info("Clicking continue button...")
        page.evaluate('document.querySelector("#login_password_continue").click()')
        
        # Wait for challenge or password field
        logger.info("Waiting for page to settle...")
        time.sleep(3)  # Give time for challenge to appear
        
        # Check for challenge
        if check_for_challenge(page):
            logger.info("Detected Cloudflare challenge after email entry...")
            if not solve_challenge(page, "39058676a8e74a81ce92b4a65d1d276a"):
                logger.error("Failed to bypass Cloudflare challenge")
                return False
        
        # Wait for password field
        if not wait_for_password_field(page):
            logger.error("Could not proceed to password step")
            return False
        
        # Now we should be on the password page
        logger.info("Looking for password field...")
        password_input = page.wait_for_selector('#login_password', timeout=10000, state='visible')
        if not password_input:
            logger.error("Could not find visible password input")
            return False
            
        logger.info("Entering password...")
        # Type the password character by character
        password_input.type(password, delay=100)
        
        # Find and click the login button
        logger.info("Looking for login button...")
        login_button = page.wait_for_selector('#login_control_continue', timeout=10000, state='visible')
        if not login_button:
            logger.error("Could not find visible login button")
            return False
            
        logger.info("Clicking login button...")
        page.evaluate('document.querySelector("#login_control_continue").click()')
        
        # Wait for challenge or success
        logger.info("Waiting for page to settle...")
        time.sleep(3)  # Give time for challenge to appear
        
        # Check for challenges after login
        if check_for_challenge(page):
            logger.info("Detected Cloudflare challenge after login...")
            if not solve_challenge(page, "39058676a8e74a81ce92b4a65d1d276a"):
                logger.error("Failed to bypass Cloudflare challenge")
                return False
                
        # Wait for login success indicators
        logger.info("Waiting for login success...")
        max_attempts = 10
        attempts = 0
        while attempts < max_attempts:
            if check_login_success(page):
                return True
            time.sleep(1)
            attempts += 1
            
        logger.error("Could not verify successful login")
        return False
        
    except Exception as e:
        logger.error(f"Error in login flow: {str(e)}")
        return False

def save_cookies(email, password, max_attempts=3):
    """Launch browser to get Upwork cookies from a logged-in session"""
    browser = None
    attempt = 0
    
    while attempt < max_attempts:
        attempt += 1
        logger.info(f"Login attempt {attempt}/{max_attempts}")
        
        try:
            with sync_playwright() as playwright:
                # Launch browser with specific arguments
                browser = playwright.chromium.launch(
                    headless=False,
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
                context = browser.new_context()
                page = context.new_page()
                
                # Start at login page
                logger.info("Navigating to Upwork login page...")
                page.goto("https://www.upwork.com/ab/account-security/login", timeout=60000)
                
                # Handle login flow including challenges
                if not handle_login_flow(page, email, password):
                    logger.error("Failed to handle login flow")
                    continue
                
                # Wait longer for all cookies to be set
                logger.info("Waiting for cookies to settle...")
                time.sleep(10)
                
                # Get cookies
                cookies = context.cookies()
                
                # Verify cookies
                if not verify_cookies(cookies):
                    logger.error("Cookie verification failed")
                    continue
                    
                # Save cookies
                if save_cookies_to_file(cookies, "./files/auth/cookies.json"):
                    logger.info("Login and cookie saving successful!")
                    return True
                    
        except Exception as e:
            logger.error(f"Error during login attempt {attempt}: {str(e)}")
            
        finally:
            if browser:
                try:
                    browser.close()
                except Exception as e:
                    logger.error(f"Error closing browser: {str(e)}")
                    
        # Wait before retrying
        if attempt < max_attempts:
            time.sleep(5)
            
    logger.error(f"Failed to login and save cookies after {max_attempts} attempts")
    return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Save Upwork authentication cookies')
    parser.add_argument('--email', required=True, help='Upwork account email')
    parser.add_argument('--password', required=True, help='Upwork account password')
    
    args = parser.parse_args()
    success = save_cookies(args.email, args.password)
    exit(0 if success else 1)
