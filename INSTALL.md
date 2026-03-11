# Tejas Job Agent v4 — COMPLETE SETUP GUIDE

## What This System Does

| Feature | Status |
|---|---|
| Scrapes 7 job boards (RemoteOK, LinkedIn, Remotive, Jobicy, Arbeitnow, Wellfound, YC) | ✅ |
| Groq writes personalized cover letters (3 para, 180 words, with real numbers) | ✅ |
| Builds custom DOCX resume per job | ✅ |
| Converts DOCX to PDF via LibreOffice | ✅ |
| Sends applications via Gmail automatically | ✅ |
| Monitors inbox, classifies replies (interview/rejected/accepted) | ✅ |
| Auto-replies to interview invites with availability | ✅ |
| Sends follow-up email after 4 days of silence | ✅ |
| STOPS all emails once you get an offer | ✅ |
| Creates Desktop .txt alert on interview/offer | ✅ |
| Web dashboard (open dashboard.html in browser) | ✅ |
| Tracks GitHub for new projects | ✅ |
| Auto-runs every 4 hours via daemon | ✅ |

---

## STEP 1 — Copy files into your agent folder

```bash
cd ~/PROJECTS/ai_agent/tejas-job-agent-v3/tejas-agent
```

Copy these files from the download:
- `main.py` → replace existing
- `scrapers/scrape_jobs.py` → replace existing
- `dashboard.html` → new file
- `run_agent.sh` → replace existing
- `project_tracker.py` → new file

---

## STEP 2 — Install Python deps

```bash
source ~/PROJECTS/venv/bin/activate
pip install groq beautifulsoup4 requests google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

---

## STEP 3 — Install LibreOffice (for PDF resumes)

**WSL/Ubuntu:**
```bash
sudo apt-get install libreoffice -y
```

Test it works:
```bash
libreoffice --version
```

---

## STEP 4 — Set your Groq API key

```bash
export GROQ_API_KEY=gsk_YOUR_KEY_HERE
```

To make it permanent (persists after reboot):
```bash
echo 'export GROQ_API_KEY=gsk_YOUR_KEY_HERE' >> ~/.bashrc
source ~/.bashrc
```

**Also paste the key into run_agent.sh line 16.**

---

## STEP 5 — Gmail OAuth (first time only)

```bash
python3 main.py monitor
```

This will print a URL. Copy it, open in Windows browser, sign in with tejasmani17@gmail.com.
After auth, `token.json` is saved. You never need to do this again.

---

## STEP 6 — Test run

```bash
python3 main.py test
```

Expected output:
- 2 jobs processed
- Cover letters written by Groq
- DOCX + PDF saved in output/
- Email sent (if Gmail connected) OR saved to output/ folder

---

## STEP 7 — Start the daemon (runs every 4 hours)

```bash
chmod +x run_agent.sh
nohup ./run_agent.sh &
```

Monitor it:
```bash
tail -f logs/daemon.log
```

Stop it:
```bash
pkill -f run_agent.sh
```

---

## STEP 8 — Dashboard

Open `dashboard.html` in your browser from the tejas-agent folder.
It auto-refreshes every 60 seconds.

To open from WSL:
```bash
explorer.exe dashboard.html
```

---

## STEP 9 — Auto-start on Windows login (optional)

1. Open: `shell:startup` in Windows Explorer
2. Create a shortcut to this `.bat` file:

```bat
@echo off
wsl -d Ubuntu -e bash -c "cd ~/PROJECTS/ai_agent/tejas-job-agent-v3/tejas-agent && nohup ./run_agent.sh &"
```

---

## Daily Commands

```bash
# Check status
python3 main.py dashboard

# Run manually
python3 main.py run

# Check Gmail replies
python3 main.py monitor

# Check for new GitHub projects to add to resume
python3 main.py projects

# Test only (2 jobs, no email)
python3 main.py test
```

---

## How the email logic works

1. Agent applies → saves to `output/` folder + sends email if job has contact email
2. Every 4 hours, `monitor` checks Gmail inbox
3. If reply classified as **interview** → auto-replies with availability, creates Desktop alert
4. If **accepted** → Desktop alert, AGENT STOPS applying permanently
5. If **no reply after 4 days** → sends follow-up once
6. If **rejected** → logs it, continues applying

---

## Important notes

- **Salary filter**: $30/hr minimum (jobs without salary info included)
- **Title filter**: Only ML/AI/CV/Data roles, no frontend/DevOps/blockchain
- **Max per run**: 30 jobs
- **Delay between apps**: 8 seconds (avoids rate limits)
- **Seen jobs**: Stored in `logs/seen_jobs.json` — never applies to same job twice
- **Desktop alerts**: Created in `~/Desktop/` as `.txt` files
