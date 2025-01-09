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
1. **Specificity & Detail**: Provide specific, detailed answers that demonstrate expertise.
2. **Relevant Experience**: Reference relevant experience from the background information.
3. **Conciseness**: Keep answers concise but comprehensive.
4. **Professional Tone**: Maintain a professional tone throughout.
5. **Multiple Choice Questions**:
   - Select the most relevant options based on the background information.
6. **Yes/No Questions**:
   - Provide a clear yes or no answer.
   - **Explanation**: Include reasoning or context behind the answer.
7. **Multi-part Questions**:
   - Address each part of the question clearly and separately.
   - Ensure coherence and logical flow between parts.
8. **Compound Questions**:
   - Break down compound questions into individual responses.
   - Ensure each sub-question is answered thoroughly.

**Example Handling:**
- For a question like "Tell us of your skills beyond VAPI. Are you a Python or JavaScript developer? Do you do ML work?", structure the answer to address each sub-question in separate paragraphs or sections.
- For contextual prompts, ensure the response acknowledges the context before answering the main question.

Return a JSON object with this structure:
{{
  "answers": [
    {{
      "answer": "your detailed answer here"
    }}
  ]
}}

Note: Return ONLY the answer content in the "answer" field. The question text and type will be handled by the system.

Example response:
{{
  "answers": [
    {{
      "answer": "I have 5+ years of experience developing AI solutions, specializing in LLMs and custom AI agents. My background includes..."
    }},
    {{
      "answer": "Yes, I can start right away. I currently have availability to fully commit to this project..."
    }},
    {{
      "answer": "Beyond VAPI, I am a full-stack developer with 8+ years of experience. I am proficient in both Python and JavaScript/TypeScript, often using Node.js for backend development. Additionally, I have extensive experience in ML development, specifically with LLMs, including GPT models, LangChain, and building custom AI agents."
    }},
    {{
      "answer": "I have extensive experience working with N8N, as described in my background. I have built custom nodes, integrated it with numerous APIs, and created full automation platforms using it. Additionally, I've used Make.com and understand the core concepts behind workflow automation, making the transition seamless. Therefore, N8N usage will absolutely not be an issue for me."
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
