import pandas as pd
from datetime import datetime
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict
from typing import List
from colorama import Fore, Style
import logging
from .utils import (
    scrape_upwork_data,
    score_scaped_jobs,
    convert_jobs_matched_to_string_list,
    generate_cover_letter,
    generate_interview_script_content,
    save_scraped_jobs_to_csv,
)

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

logger = setup_logger('graph')

COVER_LETTERS_FILE = "./files/cover_letter.txt"

class GraphState(TypedDict):
    job_title: str
    scraped_jobs_df: pd.DataFrame
    matches: List[str]
    job_description: str
    cover_letter: str
    call_script: str
    num_matches: int

class UpworkAutomation:
    def __init__(self, profile, num_jobs=20):
        logger.info("Initializing UpworkAutomation")
        # Freelancer profile/resume
        self.profile = profile
        logger.debug(f"Freelancer profile: {profile}")

        # Number of jobs to collect
        self.number_of_jobs = num_jobs
        logger.debug(f"Number of jobs to collect: {num_jobs}")

        # Build graph
        self.graph = self.build_graph()
        logger.info("UpworkAutomation initialized")

    def scrape_upwork_jobs(self, state):
        """
        Scrape jobs based on job title provided

        @param state: The current state of the application.
        @return: Updated state with scraped jobs.
        """
        logger.info(f"Scraping Upwork jobs for: {state['job_title']}")
        job_title = state["job_title"]

        print(
            Fore.YELLOW
            + f"----- Scraping Upwork jobs for: {job_title} -----\n"
            + Style.RESET_ALL
        )
        job_listings_df = scrape_upwork_data(job_title, self.number_of_jobs)
        logger.debug(f"Scraped job listings: {job_listings_df}")

        print(
            Fore.GREEN
            + f"----- Scraped {len(job_listings_df)} jobs -----\n"
            + Style.RESET_ALL
        )
        logger.info(f"Scraped {len(job_listings_df)} jobs")
        return {**state, "scraped_jobs_df": job_listings_df}

    def score_scraped_jobs(self, state):
        logger.info("Scoring scraped jobs")
        print(Fore.YELLOW + "----- Scoring scraped jobs -----\n" + Style.RESET_ALL)
        jobs_df = score_scaped_jobs(state["scraped_jobs_df"], self.profile)
        jobs_matched = jobs_df[jobs_df["score"] >= 7]
        matches = convert_jobs_matched_to_string_list(jobs_matched)
        logger.debug(f"Matched jobs: {matches}")
        logger.info("Scoring of scraped jobs completed")
        return {
            "scraped_jobs_df": jobs_df,
            "matches": matches,
            "num_matchs": len(matches),
        }

    def check_for_job_matches(self, state):
        logger.info("Checking for remaining job matches")
        print(
            Fore.YELLOW
            + "----- Checking for remaining job matches -----\n"
            + Style.RESET_ALL
        )
        logger.info("Finished checking for remaining job matches")
        return state

    def need_to_process_matches(self, state):
        """
        Check if there are any job matches.

        @param state: The current state of the application.
        @return: "empty" if no job matches, otherwise "process".
        """
        logger.info("Checking if there are any job matches")
        if len(state["matches"]) == 0:
            logger.info("No job matches remaining")
            print(Fore.RED + "No job matches remaining\n" + Style.RESET_ALL)
            save_scraped_jobs_to_csv(state["scraped_jobs_df"])
            return "No matches"
        else:
            logger.info(f"There are {len(state['matches'])} Job matches remaining to process")
            print(
                Fore.GREEN
                + f"There are {len(state['matches'])} Job matches remaining to process\n"
                + Style.RESET_ALL
            )
            return "Process jobs"

    def generate_job_application_content(self, state):
        logger.info("Generating job application content")
        logger.info("Job application content generated")
        return state

    def generate_cover_letter(self, state):
        """
        Generate cover letter based on the job description and the profile.

        @param state: The current state of the application.
        @return: Updated state with generated cover letter.
        """
        logger.info("Generating cover letter")
        print(Fore.YELLOW + "----- Generating cover letter -----\n" + Style.RESET_ALL)
        matches = state["matches"]
        job_description = str(matches[-1])
        cover_letter = generate_cover_letter(job_description, self.profile)
        logger.debug(f"Generated cover letter: {cover_letter}")
        logger.info("Cover letter generated")
        return {"job_description": job_description, "cover_letter": cover_letter}

    def generate_interview_script_content(self, state):
        logger.info("Generating interview script content")
        print(Fore.YELLOW + "----- Generating call script -----\n" + Style.RESET_ALL)
        matches = state["matches"]
        job_description = str(matches[-1])
        call_script = generate_interview_script_content(job_description)
        logger.debug(f"Generated call script: {call_script}")
        logger.info("Interview script content generated")
        return {"call_script": call_script}

    def save_job_application_content(self, state):
        logger.info("Saving job application content")
        print(
            Fore.YELLOW + "----- Saving cover letter & script -----\n" + Style.RESET_ALL
        )
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(COVER_LETTERS_FILE, "a") as file:
            file.write("\n" + "=" * 80 + "\n")
            file.write(f"DATE: {timestamp}\n")
            file.write("=" * 80 + "\n\n")

            # Job Description Section
            file.write("### Job Description ###\n")
            file.write(state["job_description"] + "\n\n")

            # Cover Letter Section
            file.write("### Cover Letter ###\n")
            file.write(state["cover_letter"] + "\n\n")

            # Call Script Section
            file.write("### Call Script ###\n")
            file.write(state["call_script"] + "\n")

            file.write("\n" + "/" * 100 + "\n")

        # Remove already processed job
        state["matches"].pop()
        logger.info("Job application content saved")
        return {"matches": state["matches"]}

    def build_graph(self):
        logger.info("Building graph")
        graph = StateGraph(GraphState)

        # create all required nodes
        graph.add_node("scrape_upwork_jobs", self.scrape_upwork_jobs)
        graph.add_node("score_scraped_jobs", self.score_scraped_jobs)
        graph.add_node("check_for_job_matches", self.check_for_job_matches)
        graph.add_node(
            "generate_job_application_content", self.generate_job_application_content
        )
        graph.add_node("generate_cover_letter", self.generate_cover_letter)
        graph.add_node(
            "generate_interview_script_content",
            self.generate_interview_script_content,
        )
        graph.add_node(
            "save_job_application_content", self.save_job_application_content
        )

        # Link nodes to complete workflow
        graph.set_entry_point("scrape_upwork_jobs")
        graph.add_edge("scrape_upwork_jobs", "score_scraped_jobs")
        graph.add_edge("score_scraped_jobs", "check_for_job_matches")
        graph.add_conditional_edges(
            "check_for_job_matches",
            self.need_to_process_matches,
            {"Process jobs": "generate_job_application_content", "No matches": END},
        )
        graph.add_edge("generate_job_application_content", "generate_cover_letter")
        graph.add_edge(
            "generate_job_application_content", "generate_interview_script_content"
        )
        graph.add_edge("generate_cover_letter", "save_job_application_content")
        graph.add_edge(
            "generate_interview_script_content", "save_job_application_content"
        )
        graph.add_edge("save_job_application_content", "check_for_job_matches")
        logger.info("Graph built")
        return graph.compile()

    def run(self, job_title):
        logger.info("Running Upwork Jobs Automation")
        print(
            Fore.BLUE + "----- Running Upwork Jobs Automation -----\n" + Style.RESET_ALL
        )
        config = {"recursion_limit": 1000}
        state = self.graph.invoke({"job_title": job_title}, config)
        logger.info("Upwork Jobs Automation completed")
        return state
