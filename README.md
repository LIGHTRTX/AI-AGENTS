# TEJAS Job Agent v4

An **AI-powered autonomous job application agent** that scrapes job listings, generates tailored resumes and cover letters using LLMs, and prepares application packages automatically.

The system searches multiple job platforms, filters new opportunities, and generates personalized application documents ready for submission.

---

# Overview

Applying to hundreds of jobs manually is slow and inefficient.
**TEJAS Job Agent v4** automates the process by:

1. Scraping jobs from multiple platforms
2. Filtering new opportunities
3. Generating tailored resumes
4. Writing custom cover letters using AI
5. Packaging applications for quick submission

The system is designed to act like a **personal AI job-search assistant**.

---

# Key Features

* Multi-source job scraping
* Automatic filtering of new job listings
* AI-generated personalized cover letters
* Resume generation for each job
* Application package creation
* Offline storage of application outputs
* Modular scraper architecture

---

# Job Sources

The agent currently collects jobs from:

* RemoteOK
* LinkedIn
* Arbeitnow
* Remotive
* Jobicy
* Wellfound
* Y Combinator job board

---

# System Pipeline

Job Scraping
→ Job Filtering (new jobs only)
→ AI Cover Letter Generation
→ Resume Generation
→ Application Package Creation
→ Output Folder

---

# Example Output

Each processed job generates a folder containing:

* `cover_letter.txt`
* `resume.pdf`
* job metadata

Example output structure:

```
output/
 ├── job_1/
 │   ├── cover_letter.txt
 │   ├── resume.pdf
 │   └── job_info.json
 ├── job_2/
 │   ├── cover_letter.txt
 │   ├── resume.pdf
 │   └── job_info.json
```

---

# AI Cover Letter Generation

The agent uses **Groq LLM API** to generate personalized cover letters based on:

* Job title
* Company
* Candidate experience
* Project highlights

Example generated section:

> The Applied Machine Learning Engineer role emphasizes real-time data processing and model deployment, which aligns with my work in building a 110 FPS computer vision tracking system and a large-scale fraud detection pipeline.

---

# Project Structure

```
agent_v4/
│
├── main.py
├── requirements.txt
│
├── scrapers/
│   ├── scrape_jobs.py
│   └── job_sources.py
│
├── logs/
│   └── seen_jobs.json
│
├── output/
│   └── generated_applications
│
├── utils/
│   ├── cover_letter_generator.py
│   ├── resume_builder.py
│   └── helpers.py
│
└── README.md
```

---

# Installation

Clone the repository:

```
git clone https://github.com/LIGHTRTX/tejas-job-agent.git
cd tejas-job-agent/agent_v4
```

Install dependencies:

```
pip install -r requirements.txt
```

---

# Setup API Key

Save your Groq API key:

```
python3 main.py savekey YOUR_GROQ_KEY
```

This stores the key for future runs.

---

# Test Mode

Test the pipeline with a few jobs:

```
python3 main.py test
```

This will scrape a small set of jobs and generate sample application packages.

---

# Full Run Mode

Run the full job processing pipeline:

```
python3 main.py run
```

The agent will:

* scrape jobs
* filter new listings
* generate cover letters
* build resumes
* store application packages

---

# Logs

The system tracks previously processed jobs in:

```
logs/seen_jobs.json
```

Reset to process jobs again:

```
echo "[]" > logs/seen_jobs.json
```

---

# Technologies Used

* Python
* Web scraping
* Groq LLM API
* JSON-based job tracking
* Automated document generation

---

# Applications

* Automated job search assistants
* AI-powered productivity tools
* LLM workflow automation
* Agent-based task automation

---

# Future Improvements

* Automatic job application submission
* Gmail integration for sending applications
* Skill-based job ranking
* AI resume optimization
* Multi-agent orchestration for job search

---

# Author

**Tejas Mani P**

Machine Learning Engineer
GitHub: https://github.com/LIGHTRTX
LinkedIn: https://linkedin.com/in/tejasmani
