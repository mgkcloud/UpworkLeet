SCRAPER_PROMPT_TEMPLATE = """
Extract the relevant data from this page content:

<content>
{markdown_content}
</content>

**Important Instructions**
1. For job listings pages:
   - Extract all job listing URLs
   - Return them in a JSON array under the "jobs" key
   - Each URL should be relative (starting with /jobs/)

2. For individual job pages:
   - Extract the following fields:
     * title: The job title (required)
     * description: The full job description (required)
     * job_type: Either "Fixed" or "Hourly" (required)
     * experience_level: The required experience level (required)
     * duration: The project duration (required)
     * rate: The payment rate/budget (optional)
     * client_infomation: Client details like location, history, etc. (optional)
   - Return a single JSON object with these fields
   - Do not return arrays of multiple jobs
   - Ensure all required fields are present

Example response for job listings page:
{{"jobs": [
  {{"link": "/jobs/example-job-1"}},
  {{"link": "/jobs/example-job-2"}}
]}}

Example response for individual job page:
{{
  "title": "AI Developer Needed",
  "description": "Full job description here...",
  "job_type": "Hourly",
  "experience_level": "Expert",
  "duration": "3-6 months",
  "rate": "$50-$70/hr",
  "client_infomation": "United States | $10k spent | 5 hires"
}}
"""

SCRAPE_QUESTIONS_PROMPT_TEMPLATE = """
You are an expert at analyzing Upwork job application forms. Your task is to extract any additional questions that appear after the cover letter section.

<content>
{markdown_content}
</content>

Look for these specific patterns:
1. Text fields with labels ending in "?"
2. Required/Optional field indicators
3. Radio button groups (Yes/No questions)
4. Checkbox lists (multiple choice)
5. Textareas for longer answers
6. Questions about:
   - Experience with specific technologies
   - Availability/Timeline
   - Rate expectations
   - Portfolio/Similar work examples
   - Certifications/Qualifications

Return a JSON object with this structure:
{{
  "questions": [
    {{
      "text": "The exact question text",
      "type": "text" or "multiple_choice" or "yes_no",
      "options": ["option1", "option2"] // Only for multiple_choice
    }}
  ]
}}

Example questions to look for:
- "What is your experience with [technology]?"
- "Are you available to start immediately?"
- "Which of these skills do you have?"
- "Have you worked on similar projects?"
- "What is your expected timeline?"
- "Do you have experience with [specific tool/framework]?"

If no questions are found, return: {{"questions": []}}

Remember:
- Extract the exact question text
- Determine the correct question type
- Include all options for multiple choice questions
- Look for both required and optional questions
"""

ANSWER_QUESTIONS_PROMPT_TEMPLATE = """
Generate answers for the following job application questions. Use the provided background information and job details to craft relevant, specific answers.

Job Description:
<job_description>
{job_description}
</job_description>

Technical Background:
<technical_background>
{technical_background}
</technical_background>

Work Approach:
<work_approach>
{work_approach}
</work_approach>

Questions to Answer:
{questions}

Guidelines:
1. Provide specific, detailed answers that demonstrate expertise
2. Reference relevant experience from the background information
3. Keep answers concise but comprehensive
4. Maintain a professional tone
5. For multiple choice questions, select the most relevant options
6. For yes/no questions, explain the reasoning behind the answer

Return a JSON object with this structure:
{{
  "answers": [
    {{
      "question": "original question text",
      "answer": "your answer here",
      "type": "question type from input"
    }}
  ]
}}
"""

SCORE_JOBS_PROMPT_TEMPLATE = """
You are a job matching expert specializing in pairing freelancers with the most suitable Upwork jobs. 
Your task is to evaluate each job based on the following criteria:

1. **Relevance to Freelancer Profile**: Assess how closely the job matches the skills, experience, and qualifications outlined in the freelancer's profile.
2. **Complexity of the Project**: Determine the complexity level of the job and how it aligns with the freelancer's expertise.
3. **Rate**: If the job's rate is provided evaluate the compensation compared to industry standards otherwise ignore it.
4. **Client History**: Consider the client's previous hiring history, totals amount spent, active jobs and longevity on the platform.

For each job, assign a score from 1 to 10 based on the above criteria, with 10 being the best match. 

Freelancer Profile:
<profile>
{profile}
</profile>

Jobs to evaluate:
{jobs}

**IMPORTANT** Return a JSON object with the following structure:
```json
{{"matches": [
  {{"job_id": "id from job", "score": integer between 1-10}}
]}}
```

Example response for 2 jobs:
```json
{{"matches": [
  {{"job_id": "0", "score": 8}},
  {{"job_id": "1", "score": 5}}
]}}
```

Note: Each job in the input has an "id" field - use this exact value for the job_id in your response.
"""

GENERATE_COVER_LETTER_PROMPT_TEMPLATE = """
You are an Upwork cover letter specialist, crafting targeted and personalized proposals. 
Create a persuasive cover letter that aligns with job requirements while highlighting the freelancer's skills and experience.

Freelancer Profile:
<profile>
{profile}
</profile>

Job Description:
<job_description>
{job_description}
</job_description>

Guidelines:
1. Address the client's needs from the job description; do not over-emphasize the freelancer's profile.
2. Illustrate how the freelancer can meet these needs based on their past experience.
3. Show enthusiasm for the job and its concept.
4. Keep the letter under 150 words, maintaining a friendly and concise tone.
5. Integrate job-related keywords naturally.
6. Briefly mention relevant past projects from the freelancer's profile if applicable.
7. End with "Best, Aymen"

IMPORTANT: Return a JSON object with a single "letter" field containing the cover letter text.
Example response format:
{{"letter": "Hey there!\\n\\nI'm excited about...[cover letter content]...\\n\\nBest,\\nAymen"}}
"""

GENERATE_CALL_SCRIPT_PROMPT_TEMPLATE = """
You are a freelance interview preparation coach. Create a tailored call script for a freelancer preparing for an interview with a client.

Job Description:
<job_description>
{job_description}
</job_description>

Technical Background:
<technical_background>
{technical_background}
</technical_background>

Work Approach:
<work_approach>
{work_approach}
</work_approach>

The script should include:
1. A brief introduction for the freelancer to use
2. Key points about relevant experience and skills
3. 10 potential client questions with suggested answers
4. 10 questions for the freelancer to ask
5. Maintain a friendly and professional tone

IMPORTANT: Return a JSON object with a single "script" field containing the formatted script.
Example response format:
{{"script": "# Introduction\\n[introduction content]\\n\\n# Key Points\\n[points content]\\n\\n# Client Questions\\n[questions content]\\n\\n# Questions to Ask\\n[questions content]"}}
"""
