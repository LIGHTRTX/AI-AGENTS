#!/usr/bin/env python3
"""
Tejas Job Agent v4 — COMPLETE SYSTEM
- Scrapes 7+ job boards
- Groq writes personalized cover letters (3 paragraphs, 180 words, with numbers)
- Builds DOCX + PDF resume tailored to each job
- Sends email applications automatically via Gmail
- Monitors replies: classifies as interview/rejection/follow-up-needed
- Auto-replies to interview invites with availability
- Sends follow-up after 4 days silence
- STOPS all emails after acceptance
- Creates desktop .txt notification on interview/acceptance
- Logs everything to dashboard-readable JSON
"""

import os, sys, json, time, re, subprocess, base64, traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ─── Deps ─────────────────────────────────────────────────────────────────────
try:
    from groq import Groq
except ImportError:
    print("Run: pip install groq"); sys.exit(1)

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    GMAIL_AVAILABLE = True
except ImportError:
    GMAIL_AVAILABLE = False

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# ─── Config ───────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
PROJECTS_FILE  = BASE_DIR / "core" / "projects.json"
LOGS_DIR       = BASE_DIR / "logs"
OUTPUT_DIR     = BASE_DIR / "output"
SCRAPERS_DIR   = BASE_DIR / "scrapers"
DESKTOP_DIR    = Path.home() / "Desktop"

LOGS_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

APPS_LOG    = LOGS_DIR / "applications.json"
SEEN_LOG    = LOGS_DIR / "seen_jobs.json"
STATS_FILE  = LOGS_DIR / "stats.json"
DAEMON_LOG  = LOGS_DIR / "daemon.log"

EMAIL_ADDRESS = "tejasmani17@gmail.com"
YOUR_NAME     = "Tejas Mani P"
YOUR_PHONE    = "+91-9445238427"
YOUR_LINKEDIN = "linkedin.com/in/tejasmani"
YOUR_GITHUB   = "github.com/LIGHTRTX"

GROQ_MODEL    = "llama-3.3-70b-versatile"
MAX_PER_RUN   = 30
DELAY_SECS    = 8

GMAIL_SCOPES  = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

# ─── Groq client (lazy init so shell export always works) ─────────────────────
_groq_client = None

def get_groq():
    global _groq_client
    if _groq_client is None:
        key = os.environ.get("GROQ_API_KEY", "")
        if key:
            _groq_client = Groq(api_key=key)
        else:
            # Try reading from .groq_key file in agent folder
            key_file = BASE_DIR / ".groq_key"
            if key_file.exists():
                key = key_file.read_text().strip()
                _groq_client = Groq(api_key=key)
    return _groq_client

def call_groq(prompt: str, max_tokens: int = 900, json_mode: bool = False) -> str:
    client = get_groq()
    if not client:
        print("  ⚠  GROQ_API_KEY not set! Run: export GROQ_API_KEY=gsk_...")
        print("     Or save it: echo 'gsk_YOUR_KEY' > .groq_key")
        return ""
    kwargs = dict(
        model=GROQ_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    r = client.chat.completions.create(**kwargs)
    return r.choices[0].message.content.strip()

# ─── JSON helpers ─────────────────────────────────────────────────────────────
def load_json(path, default):
    try:
        with open(path) as f: return json.load(f)
    except: return default

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def load_applications():
    return load_json(APPS_LOG, [])

def save_applications(apps):
    save_json(APPS_LOG, apps)

def add_application(app: dict):
    apps = load_applications()
    apps.append(app)
    save_applications(apps)
    _update_stats(apps)

def _update_stats(apps=None):
    if apps is None: apps = load_applications()
    stats = {
        "total": len(apps),
        "sent": sum(1 for a in apps if a.get("email_sent")),
        "interviews": sum(1 for a in apps if a.get("status") == "interview"),
        "rejections": sum(1 for a in apps if a.get("status") == "rejected"),
        "accepted": sum(1 for a in apps if a.get("status") == "accepted"),
        "pending": sum(1 for a in apps if a.get("status") in ("sent","saved","pending",None)),
        "last_run": datetime.now().isoformat(),
        "sources": {},
        "daily": {}
    }
    for a in apps:
        src = a.get("source", "unknown")
        stats["sources"][src] = stats["sources"].get(src, 0) + 1
        day = (a.get("applied_at") or "")[:10]
        if day: stats["daily"][day] = stats["daily"].get(day, 0) + 1
    save_json(STATS_FILE, stats)

# ─── Desktop notification ─────────────────────────────────────────────────────
def desktop_notify(title: str, body: str, emoji: str = "📋"):
    DESKTOP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    safe = re.sub(r'[^a-zA-Z0-9_]', '', title.replace(' ','_'))[:30]
    fname = DESKTOP_DIR / f"AGENT_{safe}_{ts}.txt"
    content = f"""{'='*60}
{emoji}  {title}
{'='*60}
{body}

Time: {datetime.now().strftime("%A %B %d, %Y at %I:%M %p")}
{'='*60}
"""
    try:
        fname.write_text(content)
        print(f"  📋 Desktop note: {fname.name}")
    except Exception as e:
        print(f"  ⚠  Desktop note failed: {e}")

# ─── Gmail ────────────────────────────────────────────────────────────────────
def get_gmail():
    if not GMAIL_AVAILABLE:
        return None
    creds = None
    token = BASE_DIR / "token.json"
    creds_file = BASE_DIR / "gmail_credentials.json"

    if token.exists():
        creds = Credentials.from_authorized_user_file(str(token), GMAIL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try: creds.refresh(Request())
            except: creds = None
        if not creds:
            if not creds_file.exists():
                return None
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), GMAIL_SCOPES)
            print("\n  🔐 Gmail Auth needed — open this URL in your Windows browser:")
            creds = flow.run_local_server(port=0)
        save_json(str(token), json.loads(creds.to_json()))
    return build("gmail", "v1", credentials=creds)

def gmail_send(svc, to: str, subject: str, body: str, attachments: list = []) -> bool:
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        for fp in attachments:
            fp = Path(fp)
            if fp.exists():
                with open(fp, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename={fp.name}")
                msg.attach(part)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True
    except Exception as e:
        print(f"  ❌ Email send failed: {e}")
        return False

def get_email_body(msg) -> str:
    payload = msg["payload"]
    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain":
                data = part["body"].get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    data = payload.get("body", {}).get("data", "")
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore") if data else ""

# ─── AI: cover letter + project selection ────────────────────────────────────
def ai_write_application(job: dict, projects: list) -> dict:
    proj_overview = "\n".join(
        f"ID:{p['id']} | {p['name']} | Stack:{p.get('stack','')} | Impact:{p.get('impact','')}"
        for p in projects
    )
    company = job.get('company', 'the company')
    prompt = f"""You are helping {YOUR_NAME} apply for a job. He is an ML/AI engineer in India seeking remote work.

JOB:
Title: {job.get('title','')}
Company: {company}
Description: {job.get('description','')[:1500]}

PROJECTS (pick 3 most relevant):
{proj_overview}

STACK: Python, PyTorch, TensorFlow, YOLOv8, ByteTrack, OpenCV, LangChain, RAG, Pandas, Scikit-learn, SQL, Docker

Return ONLY valid JSON, no markdown:
{{
  "selected_project_ids": ["id1","id2","id3"],
  "custom_summary": "2 sentences connecting Tejas to THIS role. Engineering terms only.",
  "cover_letter": "3 paragraphs max 180 words.\\nP1: Reference something specific from the job description or company.\\nP2: 2 projects with exact numbers: 110 FPS tracking, 6M+ record fraud pipeline (F1 +18%), 99% accuracy fake-news detector, 32% ID stability gain.\\nP3: End exactly with: I would love to show you what I can build for {company}.\\nNo: thrilled/passionate/excited/dynamic. Direct and specific.",
  "email_subject": "Application: {job.get('title','')} — {YOUR_NAME}"
}}"""
    try:
        text = call_groq(prompt, max_tokens=900, json_mode=True)
        return json.loads(text)
    except Exception as e:
        print(f"  ⚠  AI error: {e}")
        return {
            "selected_project_ids": [p["id"] for p in projects[:3]],
            "custom_summary": f"ML engineer with real-time CV and fraud detection experience. Ready to ship for {company}.",
            "cover_letter": (
                f"I'm applying for the {job.get('title','')} role at {company}.\n\n"
                f"I've built a real-time multi-camera tracking system at 110 FPS with 32% ID stability improvement, "
                f"and a fraud detection pipeline over 6M+ transactions with 18% F1 improvement. "
                f"Everything I ship comes with Docker and inference APIs.\n\n"
                f"I would love to show you what I can build for {company}."
            ),
            "email_subject": f"Application: {job.get('title','')} — {YOUR_NAME}"
        }

# ─── Resume builders ──────────────────────────────────────────────────────────
def build_resume_docx(selected_ids, summary, folder: Path) -> Optional[Path]:
    try:
        result = subprocess.run(
            ["node", "core/build_resume.js",
             json.dumps(selected_ids), summary, str(folder)],
            cwd=str(BASE_DIR), capture_output=True, text=True, timeout=30
        )
        p = folder / "Tejas_Mani_Resume.docx"
        return p if p.exists() else None
    except Exception as e:
        print(f"  ⚠  DOCX error: {e}")
        return None

def build_resume_pdf(docx_path: Path) -> Optional[Path]:
    if not docx_path: return None
    pdf = docx_path.parent / "Tejas_Mani_Resume.pdf"
    try:
        subprocess.run(
            ["libreoffice","--headless","--convert-to","pdf",
             "--outdir", str(docx_path.parent), str(docx_path)],
            capture_output=True, timeout=30
        )
        return pdf if pdf.exists() else None
    except:
        return None

# ─── Extract email from job ───────────────────────────────────────────────────
def extract_email(job: dict) -> Optional[str]:
    text = job.get("description","") + " " + job.get("url","")
    found = re.findall(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", text)
    if found:
        return found[0]
    url = job.get("url","")
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    if m:
        domain = m.group(1)
        skip = ["linkedin.com","remoteok.com","wellfound.com","remotive.com",
                "jobicy.com","arbeitnow.com","workatastartup.com","indeed.com"]
        if not any(s in domain for s in skip):
            return f"jobs@{domain}"
    return None

# ─── Process one job ──────────────────────────────────────────────────────────
def process_job(job: dict, projects: list, gmail_svc, dry_run: bool = False) -> dict:
    title   = job.get("title","Unknown Role")
    company = job.get("company","Company")
    source  = job.get("source","?")

    print(f"\n  🏢 {title} @ {company} ({source})")
    print(f"  ✍️  Writing cover letter...")
    ai = ai_write_application(job, projects)

    selected_ids = ai.get("selected_project_ids", [p["id"] for p in projects[:3]])
    summary      = ai.get("custom_summary","")
    cover        = ai.get("cover_letter","")
    subj         = ai.get("email_subject", f"Application: {title} — {YOUR_NAME}")

    # Folder
    ts = datetime.now().strftime("%m%d_%H%M")
    safe = re.sub(r'[^a-zA-Z0-9]','_', company)[:20]
    folder = OUTPUT_DIR / f"apply_{safe}_{ts}"
    folder.mkdir(exist_ok=True)

    # Resume
    print(f"  📄 Building resume...")
    docx = build_resume_docx(selected_ids, summary, folder)
    pdf  = build_resume_pdf(docx)

    email_to = extract_email(job)
    email_body = (
        f"{cover}\n\n"
        f"---\n{YOUR_NAME}\n{EMAIL_ADDRESS} | {YOUR_PHONE}\n"
        f"GitHub: {YOUR_GITHUB} | LinkedIn: {YOUR_LINKEDIN}\n"
    )

    # Save cover letter
    (folder / "cover_letter.txt").write_text(
        f"TO: {email_to or job.get('url','')}\nSUBJECT: {subj}\n\n{email_body}"
    )
    (folder / "job_info.json").write_text(json.dumps(job, indent=2))

    # Send email
    email_sent = False
    if gmail_svc and email_to and not dry_run:
        attachments = [p for p in [docx, pdf] if p]
        email_sent = gmail_send(gmail_svc, email_to, subj, email_body, attachments)
        if email_sent:
            print(f"  ✅ Email sent → {email_to}")
        else:
            print(f"  📁 Saved (email failed)")
    elif not email_to:
        print(f"  📁 Saved — apply manually: {job.get('url','')[:60]}")
    elif dry_run:
        print(f"  🧪 Would email → {email_to}")

    app = {
        "id": f"{safe}_{ts}",
        "title": title, "company": company, "source": source,
        "url": job.get("url",""),
        "applied_at": datetime.now().isoformat(),
        "email_to": email_to,
        "email_sent": email_sent,
        "folder": str(folder),
        "status": "sent" if email_sent else "saved",
        "follow_up_sent": False,
        "reply_received": False,
    }
    add_application(app)
    return app

# ─── Scrape jobs ──────────────────────────────────────────────────────────────
def scrape_jobs() -> list:
    scraper = SCRAPERS_DIR / "scrape_jobs.py"
    if not scraper.exists():
        print("  ⚠  scrapers/scrape_jobs.py not found")
        return []
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("scrape_jobs", str(scraper))
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "scrape_all"):
            return mod.scrape_all()
    except Exception as e:
        print(f"  ⚠  Scraper error: {e}")
    return []

def filter_new(jobs: list) -> list:
    seen = set(load_json(SEEN_LOG, []))
    new  = [j for j in jobs if j.get("url","") not in seen]
    save_json(SEEN_LOG, list(seen | {j.get("url","") for j in new})[-2000:])
    return new

# ─── Gmail monitor ────────────────────────────────────────────────────────────
def classify_email(subject: str, body: str) -> str:
    prompt = f"""Classify this email reply to a job application.
Subject: {subject}
Body: {body[:500]}
Reply with EXACTLY one word from: interview, accepted, rejected, info_request, auto_reply, unknown"""
    try: return call_groq(prompt, max_tokens=10).lower().strip().split()[0]
    except: return "unknown"

def monitor_gmail(svc) -> dict:
    if not svc:
        print("  ⚠  Gmail not connected")
        return {}

    apps = load_applications()

    # STOP if accepted
    if any(a.get("status") == "accepted" for a in apps):
        print("  🎉 Offer already accepted — agent in standby.")
        return {}

    updates = {"interviews": 0, "rejections": 0, "follow_ups": 0}

    try:
        result = svc.users().messages().list(
            userId="me",
            q=f"in:inbox newer_than:14d",
            maxResults=50
        ).execute()
        messages = result.get("messages", [])
        print(f"  📬 Checking {len(messages)} recent emails...")

        processed_ids = set()

        for ref in messages:
            try:
                msg = svc.users().messages().get(
                    userId="me", id=ref["id"], format="full"
                ).execute()
                headers = {h["name"]: h["value"] for h in msg["payload"].get("headers",[])}
                subject = headers.get("Subject","")
                sender  = headers.get("From","")
                body    = get_email_body(msg)

                # Match to application
                matched = None
                for app in apps:
                    co = app.get("company","").lower()
                    ti = app.get("title","").lower()
                    em = app.get("email_to","")
                    if (co and co in subject.lower()) or \
                       (ti and ti in subject.lower()) or \
                       (em and em.split("@")[-1] in sender):
                        matched = app
                        break

                if not matched:
                    continue

                app_id = matched.get("id","")
                if app_id in processed_ids:
                    continue
                processed_ids.add(app_id)

                label = classify_email(subject, body)
                print(f"  📧 {matched.get('company','?'):20} → {label.upper()}")

                matched["status"] = label
                matched["reply_received"] = True
                matched["last_reply_at"] = datetime.now().isoformat()
                company = matched.get("company","the company")

                if label == "interview":
                    updates["interviews"] += 1

                    desktop_notify(
                        f"INTERVIEW — {company}",
                        f"Company: {company}\nRole: {matched.get('title','')}\n"
                        f"From: {sender}\nSubject: {subject}\n\n"
                        f"✅ Auto-replying with your availability...\n"
                        f"Your hours: Mon-Fri 9am-6pm IST",
                        "🎯"
                    )

                    # Auto-reply
                    reply_prompt = f"""Write a short professional reply to an interview invitation from {company}.
Max 70 words. Say you're available Mon-Fri 9am-6pm IST. Ask them to send calendar invite.
Sign as {YOUR_NAME}. No emojis. No "thrilled"."""
                    reply = call_groq(reply_prompt, 150)
                    if reply:
                        sent = gmail_send(svc, sender, f"Re: {subject}",
                                          reply + f"\n\n— {YOUR_NAME}\n{EMAIL_ADDRESS}")
                        if sent:
                            matched["interview_reply_sent"] = True
                            print(f"  ✅ Auto-replied to {company}")

                elif label == "accepted":
                    updates["interviews"] += 1
                    matched["status"] = "accepted"

                    desktop_notify(
                        f"OFFER RECEIVED — {company}",
                        f"Company: {company}\nRole: {matched.get('title','')}\n"
                        f"From: {sender}\nSubject: {subject}\n\n"
                        f"⚠️  AGENT STOPPED — No more applications will be sent.\n"
                        f"Review the offer and respond within 48 hours.",
                        "🎉"
                    )
                    print(f"\n  🎉🎉 OFFER FROM {company.upper()}! Stopping agent.\n")

                elif label == "rejected":
                    updates["rejections"] += 1

            except Exception:
                continue

        save_applications(apps)

        # Send follow-ups for 4-day-old unanswered apps
        now = datetime.now()
        for app in apps:
            if any(a.get("status") == "accepted" for a in apps):
                break
            if (app.get("email_sent") and
                not app.get("reply_received") and
                not app.get("follow_up_sent") and
                app.get("status") not in ("interview","accepted","rejected")):
                try:
                    applied = datetime.fromisoformat(app.get("applied_at", now.isoformat()))
                    if (now - applied).days >= 4:
                        fu_prompt = f"""Write a follow-up email (max 80 words) for this job application with no reply.
Job: {app.get('title','')} at {app.get('company','')}
Applied: {applied.strftime('%B %d')}
Mention one metric: 110 FPS tracking OR 6M record pipeline OR 99% accuracy.
Ask if they need anything else. Professional, not desperate.
Sign: {YOUR_NAME}, {EMAIL_ADDRESS}"""
                        followup = call_groq(fu_prompt, 150)
                        if followup and app.get("email_to"):
                            sent = gmail_send(
                                svc, app["email_to"],
                                f"Following up: {app.get('title','')} Application",
                                followup
                            )
                            if sent:
                                app["follow_up_sent"] = True
                                app["follow_up_at"] = now.isoformat()
                                updates["follow_ups"] += 1
                                print(f"  📤 Follow-up → {app.get('company','')}")
                except Exception:
                    pass

        save_applications(apps)
        _update_stats(apps)

    except Exception as e:
        print(f"  ❌ Monitor error: {e}")
        traceback.print_exc()

    return updates

# ─── Dashboard ────────────────────────────────────────────────────────────────
def print_dashboard():
    apps  = load_applications()
    stats = load_json(STATS_FILE, {})
    print("\n" + "═"*58)
    print("  📊  TEJAS JOB AGENT — LIVE DASHBOARD")
    print("═"*58)
    print(f"  Total Applied   : {stats.get('total', len(apps))}")
    print(f"  Emails Sent     : {stats.get('sent', 0)}")
    print(f"  Interviews 🎯   : {stats.get('interviews', 0)}")
    print(f"  Pending ⏳       : {stats.get('pending', 0)}")
    print(f"  Rejections ❌   : {stats.get('rejections', 0)}")
    print(f"  Accepted 🎉     : {stats.get('accepted', 0)}")
    print(f"  Last Run        : {stats.get('last_run','never')[:19]}")
    src = stats.get("sources", {})
    if src:
        print("─"*58)
        print("  Sources: " + " | ".join(f"{k}:{v}" for k,v in src.items()))
    print("─"*58)
    if apps:
        print("  Recent (last 10):")
        for app in apps[-10:]:
            icon = {"interview":"🎯","accepted":"🎉","rejected":"❌","sent":"📤","saved":"📁"}.get(app.get("status",""),"⏳")
            print(f"  {icon} {app.get('company','?'):22} {app.get('title','?')[:28]}")
    print("═"*58)

# ─── Git + LinkedIn monitor for new project content ──────────────────────────
def check_new_projects():
    """Check GitHub for new commits/repos and suggest adding to projects.json"""
    print("\n🔍 Checking GitHub for new project activity...")
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--since=1 week ago"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path.home())
        )
        if result.stdout.strip():
            print("  📝 Recent git activity found:")
            for line in result.stdout.strip().split("\n")[:5]:
                print(f"     {line}")
            print("  💡 Consider updating core/projects.json with new work!")
        else:
            print("  No new git commits this week")
    except:
        print("  (Git check skipped — not in a repo)")

# ─── Main ────────────────────────────────────────────────────────────────────
def run(mode: str = "run"):
    print("\n" + "═"*58)
    print(f"  🤖  TEJAS JOB AGENT v4 — {mode.upper()}")
    print("═"*58)

    apps = load_applications()
    if any(a.get("status") == "accepted" for a in apps):
        print("\n  🎉 You have an accepted offer! Agent in standby.")
        print("  Delete logs/applications.json to restart.")
        return

    if not get_groq():
        print("  ❌ Set GROQ_API_KEY:  export GROQ_API_KEY=gsk_...")
        print("     Or save permanently: echo gsk_YOURKEY > .groq_key")
        sys.exit(1)

    gmail_svc = get_gmail() if GMAIL_AVAILABLE else None
    print(f"  Gmail: {'✅ connected' if gmail_svc else '📁 offline (saving to output/)'}")

    print("\n🔍 Scraping jobs...")
    jobs = scrape_jobs()
    print(f"  Found {len(jobs)} jobs total")

    new_jobs = filter_new(jobs)
    print(f"  {len(new_jobs)} new jobs")

    if not new_jobs:
        print("  Nothing new. Check back in 4 hours.")
        return

    projects = load_json(PROJECTS_FILE, [])
    if not projects:
        print("  ❌ No projects in core/projects.json")
        return

    limit = 2 if mode == "test" else MAX_PER_RUN
    batch = new_jobs[:limit]
    print(f"\n  Processing {len(batch)} jobs...\n")

    for i, job in enumerate(batch, 1):
        print(f"\n[{i}/{len(batch)}]", end="")
        try:
            process_job(job, projects, gmail_svc, dry_run=(mode=="test"))
        except Exception as e:
            print(f"\n  ❌ {job.get('company','?')}: {e}")
            if mode == "test": traceback.print_exc()
        if i < len(batch): time.sleep(DELAY_SECS)

    print(f"\n{'═'*58}")
    print(f"  ✅ Done! {len(batch)} applications processed.")
    print(f"  Check output/ folder for packages.")
    print("═"*58)
    _update_stats()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if   cmd == "test":      run("test")
    elif cmd == "run":       run("run")
    elif cmd == "monitor":
        print("\n📬 Checking Gmail...")
        svc = get_gmail()
        u = monitor_gmail(svc)
        print(f"  Interviews: {u.get('interviews',0)} | Follow-ups sent: {u.get('follow_ups',0)}")
    elif cmd == "dashboard":
        print_dashboard()
        import os as _os
        dash = BASE_DIR / "dashboard.html"
        if dash.exists():
            _os.system(f'powershell.exe Start "$(wslpath -w {dash})" 2>/dev/null || explorer.exe "$(wslpath -w {dash})" 2>/dev/null')
            print(f"  🌐 Opening dashboard in browser...")
    elif cmd == "projects":  check_new_projects()
    elif cmd == "savekey":
        if len(sys.argv) < 3:
            print("Usage: python3 main.py savekey gsk_YOUR_KEY_HERE")
        else:
            key = sys.argv[2]
            (BASE_DIR / ".groq_key").write_text(key)
            bashrc = Path.home() / ".bashrc"
            line = f'\nexport GROQ_API_KEY="{key}"\n'
            current = bashrc.read_text() if bashrc.exists() else ""
            if "GROQ_API_KEY" not in current:
                with open(bashrc, "a") as f: f.write(line)
            print("  ✅ Key saved permanently — no more export needed")
            print("  Now run: python3 main.py test")
    else:
        print("Usage: python3 main.py [test|run|monitor|dashboard|projects|savekey gsk_KEY]")#!/usr/bin/env python3
"""
Tejas Job Agent v4 — COMPLETE SYSTEM
- Scrapes 7+ job boards
- Groq writes personalized cover letters (3 paragraphs, 180 words, with numbers)
- Builds DOCX + PDF resume tailored to each job
- Sends email applications automatically via Gmail
- Monitors replies: classifies as interview/rejection/follow-up-needed
- Auto-replies to interview invites with availability
- Sends follow-up after 4 days silence
- STOPS all emails after acceptance
- Creates desktop .txt notification on interview/acceptance
- Logs everything to dashboard-readable JSON
"""

import os, sys, json, time, re, subprocess, base64, traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ─── Deps ─────────────────────────────────────────────────────────────────────
try:
    from groq import Groq
except ImportError:
    print("Run: pip install groq"); sys.exit(1)

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    GMAIL_AVAILABLE = True
except ImportError:
    GMAIL_AVAILABLE = False

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# ─── Config ───────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
PROJECTS_FILE  = BASE_DIR / "core" / "projects.json"
LOGS_DIR       = BASE_DIR / "logs"
OUTPUT_DIR     = BASE_DIR / "output"
SCRAPERS_DIR   = BASE_DIR / "scrapers"
DESKTOP_DIR    = Path.home() / "Desktop"

LOGS_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

APPS_LOG    = LOGS_DIR / "applications.json"
SEEN_LOG    = LOGS_DIR / "seen_jobs.json"
STATS_FILE  = LOGS_DIR / "stats.json"
DAEMON_LOG  = LOGS_DIR / "daemon.log"

EMAIL_ADDRESS = "tejasmani17@gmail.com"
YOUR_NAME     = "Tejas Mani P"
YOUR_PHONE    = "+91-9445238427"
YOUR_LINKEDIN = "linkedin.com/in/tejasmani"
YOUR_GITHUB   = "github.com/LIGHTRTX"

GROQ_MODEL    = "llama-3.3-70b-versatile"
MAX_PER_RUN   = 30
DELAY_SECS    = 8

GMAIL_SCOPES  = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

# ─── Groq client (lazy init so shell export always works) ─────────────────────
_groq_client = None

def get_groq():
    global _groq_client
    if _groq_client is None:
        key = os.environ.get("GROQ_API_KEY", "")
        if key:
            _groq_client = Groq(api_key=key)
        else:
            # Try reading from .groq_key file in agent folder
            key_file = BASE_DIR / ".groq_key"
            if key_file.exists():
                key = key_file.read_text().strip()
                _groq_client = Groq(api_key=key)
    return _groq_client

def call_groq(prompt: str, max_tokens: int = 900, json_mode: bool = False) -> str:
    client = get_groq()
    if not client:
        print("  ⚠  GROQ_API_KEY not set! Run: export GROQ_API_KEY=gsk_...")
        print("     Or save it: echo 'gsk_YOUR_KEY' > .groq_key")
        return ""
    kwargs = dict(
        model=GROQ_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    r = client.chat.completions.create(**kwargs)
    return r.choices[0].message.content.strip()

# ─── JSON helpers ─────────────────────────────────────────────────────────────
def load_json(path, default):
    try:
        with open(path) as f: return json.load(f)
    except: return default

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def load_applications():
    return load_json(APPS_LOG, [])

def save_applications(apps):
    save_json(APPS_LOG, apps)

def add_application(app: dict):
    apps = load_applications()
    apps.append(app)
    save_applications(apps)
    _update_stats(apps)

def _update_stats(apps=None):
    if apps is None: apps = load_applications()
    stats = {
        "total": len(apps),
        "sent": sum(1 for a in apps if a.get("email_sent")),
        "interviews": sum(1 for a in apps if a.get("status") == "interview"),
        "rejections": sum(1 for a in apps if a.get("status") == "rejected"),
        "accepted": sum(1 for a in apps if a.get("status") == "accepted"),
        "pending": sum(1 for a in apps if a.get("status") in ("sent","saved","pending",None)),
        "last_run": datetime.now().isoformat(),
        "sources": {},
        "daily": {}
    }
    for a in apps:
        src = a.get("source", "unknown")
        stats["sources"][src] = stats["sources"].get(src, 0) + 1
        day = (a.get("applied_at") or "")[:10]
        if day: stats["daily"][day] = stats["daily"].get(day, 0) + 1
    save_json(STATS_FILE, stats)

# ─── Desktop notification ─────────────────────────────────────────────────────
def desktop_notify(title: str, body: str, emoji: str = "📋"):
    DESKTOP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    safe = re.sub(r'[^a-zA-Z0-9_]', '', title.replace(' ','_'))[:30]
    fname = DESKTOP_DIR / f"AGENT_{safe}_{ts}.txt"
    content = f"""{'='*60}
{emoji}  {title}
{'='*60}
{body}

Time: {datetime.now().strftime("%A %B %d, %Y at %I:%M %p")}
{'='*60}
"""
    try:
        fname.write_text(content)
        print(f"  📋 Desktop note: {fname.name}")
    except Exception as e:
        print(f"  ⚠  Desktop note failed: {e}")

# ─── Gmail ────────────────────────────────────────────────────────────────────
def get_gmail():
    if not GMAIL_AVAILABLE:
        return None
    creds = None
    token = BASE_DIR / "token.json"
    creds_file = BASE_DIR / "gmail_credentials.json"

    if token.exists():
        creds = Credentials.from_authorized_user_file(str(token), GMAIL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try: creds.refresh(Request())
            except: creds = None
        if not creds:
            if not creds_file.exists():
                return None
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), GMAIL_SCOPES)
            print("\n  🔐 Gmail Auth needed — open this URL in your Windows browser:")
            creds = flow.run_local_server(port=0)
        save_json(str(token), json.loads(creds.to_json()))
    return build("gmail", "v1", credentials=creds)

def gmail_send(svc, to: str, subject: str, body: str, attachments: list = []) -> bool:
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        for fp in attachments:
            fp = Path(fp)
            if fp.exists():
                with open(fp, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename={fp.name}")
                msg.attach(part)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True
    except Exception as e:
        print(f"  ❌ Email send failed: {e}")
        return False

def get_email_body(msg) -> str:
    payload = msg["payload"]
    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain":
                data = part["body"].get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    data = payload.get("body", {}).get("data", "")
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore") if data else ""

# ─── AI: cover letter + project selection ────────────────────────────────────
def ai_write_application(job: dict, projects: list) -> dict:
    proj_overview = "\n".join(
        f"ID:{p['id']} | {p['name']} | Stack:{p.get('stack','')} | Impact:{p.get('impact','')}"
        for p in projects
    )
    company = job.get('company', 'the company')
    prompt = f"""You are helping {YOUR_NAME} apply for a job. He is an ML/AI engineer in India seeking remote work.

JOB:
Title: {job.get('title','')}
Company: {company}
Description: {job.get('description','')[:1500]}

PROJECTS (pick 3 most relevant):
{proj_overview}

STACK: Python, PyTorch, TensorFlow, YOLOv8, ByteTrack, OpenCV, LangChain, RAG, Pandas, Scikit-learn, SQL, Docker

Return ONLY valid JSON, no markdown:
{{
  "selected_project_ids": ["id1","id2","id3"],
  "custom_summary": "2 sentences connecting Tejas to THIS role. Engineering terms only.",
  "cover_letter": "3 paragraphs max 180 words.\\nP1: Reference something specific from the job description or company.\\nP2: 2 projects with exact numbers: 110 FPS tracking, 6M+ record fraud pipeline (F1 +18%), 99% accuracy fake-news detector, 32% ID stability gain.\\nP3: End exactly with: I would love to show you what I can build for {company}.\\nNo: thrilled/passionate/excited/dynamic. Direct and specific.",
  "email_subject": "Application: {job.get('title','')} — {YOUR_NAME}"
}}"""
    try:
        text = call_groq(prompt, max_tokens=900, json_mode=True)
        return json.loads(text)
    except Exception as e:
        print(f"  ⚠  AI error: {e}")
        return {
            "selected_project_ids": [p["id"] for p in projects[:3]],
            "custom_summary": f"ML engineer with real-time CV and fraud detection experience. Ready to ship for {company}.",
            "cover_letter": (
                f"I'm applying for the {job.get('title','')} role at {company}.\n\n"
                f"I've built a real-time multi-camera tracking system at 110 FPS with 32% ID stability improvement, "
                f"and a fraud detection pipeline over 6M+ transactions with 18% F1 improvement. "
                f"Everything I ship comes with Docker and inference APIs.\n\n"
                f"I would love to show you what I can build for {company}."
            ),
            "email_subject": f"Application: {job.get('title','')} — {YOUR_NAME}"
        }

# ─── Resume builders ──────────────────────────────────────────────────────────
def build_resume_docx(selected_ids, summary, folder: Path) -> Optional[Path]:
    try:
        result = subprocess.run(
            ["node", "core/build_resume.js",
             json.dumps(selected_ids), summary, str(folder)],
            cwd=str(BASE_DIR), capture_output=True, text=True, timeout=30
        )
        p = folder / "Tejas_Mani_Resume.docx"
        return p if p.exists() else None
    except Exception as e:
        print(f"  ⚠  DOCX error: {e}")
        return None

def build_resume_pdf(docx_path: Path) -> Optional[Path]:
    if not docx_path: return None
    pdf = docx_path.parent / "Tejas_Mani_Resume.pdf"
    try:
        subprocess.run(
            ["libreoffice","--headless","--convert-to","pdf",
             "--outdir", str(docx_path.parent), str(docx_path)],
            capture_output=True, timeout=30
        )
        return pdf if pdf.exists() else None
    except:
        return None

# ─── Extract email from job ───────────────────────────────────────────────────
def extract_email(job: dict) -> Optional[str]:
    text = job.get("description","") + " " + job.get("url","")
    found = re.findall(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", text)
    if found:
        return found[0]
    url = job.get("url","")
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    if m:
        domain = m.group(1)
        skip = ["linkedin.com","remoteok.com","wellfound.com","remotive.com",
                "jobicy.com","arbeitnow.com","workatastartup.com","indeed.com"]
        if not any(s in domain for s in skip):
            return f"jobs@{domain}"
    return None

# ─── Process one job ──────────────────────────────────────────────────────────
def process_job(job: dict, projects: list, gmail_svc, dry_run: bool = False) -> dict:
    title   = job.get("title","Unknown Role")
    company = job.get("company","Company")
    source  = job.get("source","?")

    print(f"\n  🏢 {title} @ {company} ({source})")
    print(f"  ✍️  Writing cover letter...")
    ai = ai_write_application(job, projects)

    selected_ids = ai.get("selected_project_ids", [p["id"] for p in projects[:3]])
    summary      = ai.get("custom_summary","")
    cover        = ai.get("cover_letter","")
    subj         = ai.get("email_subject", f"Application: {title} — {YOUR_NAME}")

    # Folder
    ts = datetime.now().strftime("%m%d_%H%M")
    safe = re.sub(r'[^a-zA-Z0-9]','_', company)[:20]
    folder = OUTPUT_DIR / f"apply_{safe}_{ts}"
    folder.mkdir(exist_ok=True)

    # Resume
    print(f"  📄 Building resume...")
    docx = build_resume_docx(selected_ids, summary, folder)
    pdf  = build_resume_pdf(docx)

    email_to = extract_email(job)
    email_body = (
        f"{cover}\n\n"
        f"---\n{YOUR_NAME}\n{EMAIL_ADDRESS} | {YOUR_PHONE}\n"
        f"GitHub: {YOUR_GITHUB} | LinkedIn: {YOUR_LINKEDIN}\n"
    )

    # Save cover letter
    (folder / "cover_letter.txt").write_text(
        f"TO: {email_to or job.get('url','')}\nSUBJECT: {subj}\n\n{email_body}"
    )
    (folder / "job_info.json").write_text(json.dumps(job, indent=2))

    # Send email
    email_sent = False
    if gmail_svc and email_to and not dry_run:
        attachments = [p for p in [docx, pdf] if p]
        email_sent = gmail_send(gmail_svc, email_to, subj, email_body, attachments)
        if email_sent:
            print(f"  ✅ Email sent → {email_to}")
        else:
            print(f"  📁 Saved (email failed)")
    elif not email_to:
        print(f"  📁 Saved — apply manually: {job.get('url','')[:60]}")
    elif dry_run:
        print(f"  🧪 Would email → {email_to}")

    app = {
        "id": f"{safe}_{ts}",
        "title": title, "company": company, "source": source,
        "url": job.get("url",""),
        "applied_at": datetime.now().isoformat(),
        "email_to": email_to,
        "email_sent": email_sent,
        "folder": str(folder),
        "status": "sent" if email_sent else "saved",
        "follow_up_sent": False,
        "reply_received": False,
    }
    add_application(app)
    return app

# ─── Scrape jobs ──────────────────────────────────────────────────────────────
def scrape_jobs() -> list:
    scraper = SCRAPERS_DIR / "scrape_jobs.py"
    if not scraper.exists():
        print("  ⚠  scrapers/scrape_jobs.py not found")
        return []
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("scrape_jobs", str(scraper))
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "scrape_all"):
            return mod.scrape_all()
    except Exception as e:
        print(f"  ⚠  Scraper error: {e}")
    return []

def filter_new(jobs: list) -> list:
    seen = set(load_json(SEEN_LOG, []))
    new  = [j for j in jobs if j.get("url","") not in seen]
    save_json(SEEN_LOG, list(seen | {j.get("url","") for j in new})[-2000:])
    return new

# ─── Gmail monitor ────────────────────────────────────────────────────────────
def classify_email(subject: str, body: str) -> str:
    prompt = f"""Classify this email reply to a job application.
Subject: {subject}
Body: {body[:500]}
Reply with EXACTLY one word from: interview, accepted, rejected, info_request, auto_reply, unknown"""
    try: return call_groq(prompt, max_tokens=10).lower().strip().split()[0]
    except: return "unknown"

def monitor_gmail(svc) -> dict:
    if not svc:
        print("  ⚠  Gmail not connected")
        return {}

    apps = load_applications()

    # STOP if accepted
    if any(a.get("status") == "accepted" for a in apps):
        print("  🎉 Offer already accepted — agent in standby.")
        return {}

    updates = {"interviews": 0, "rejections": 0, "follow_ups": 0}

    try:
        result = svc.users().messages().list(
            userId="me",
            q=f"in:inbox newer_than:14d",
            maxResults=50
        ).execute()
        messages = result.get("messages", [])
        print(f"  📬 Checking {len(messages)} recent emails...")

        processed_ids = set()

        for ref in messages:
            try:
                msg = svc.users().messages().get(
                    userId="me", id=ref["id"], format="full"
                ).execute()
                headers = {h["name"]: h["value"] for h in msg["payload"].get("headers",[])}
                subject = headers.get("Subject","")
                sender  = headers.get("From","")
                body    = get_email_body(msg)

                # Match to application
                matched = None
                for app in apps:
                    co = app.get("company","").lower()
                    ti = app.get("title","").lower()
                    em = app.get("email_to","")
                    if (co and co in subject.lower()) or \
                       (ti and ti in subject.lower()) or \
                       (em and em.split("@")[-1] in sender):
                        matched = app
                        break

                if not matched:
                    continue

                app_id = matched.get("id","")
                if app_id in processed_ids:
                    continue
                processed_ids.add(app_id)

                label = classify_email(subject, body)
                print(f"  📧 {matched.get('company','?'):20} → {label.upper()}")

                matched["status"] = label
                matched["reply_received"] = True
                matched["last_reply_at"] = datetime.now().isoformat()
                company = matched.get("company","the company")

                if label == "interview":
                    updates["interviews"] += 1

                    desktop_notify(
                        f"INTERVIEW — {company}",
                        f"Company: {company}\nRole: {matched.get('title','')}\n"
                        f"From: {sender}\nSubject: {subject}\n\n"
                        f"✅ Auto-replying with your availability...\n"
                        f"Your hours: Mon-Fri 9am-6pm IST",
                        "🎯"
                    )

                    # Auto-reply
                    reply_prompt = f"""Write a short professional reply to an interview invitation from {company}.
Max 70 words. Say you're available Mon-Fri 9am-6pm IST. Ask them to send calendar invite.
Sign as {YOUR_NAME}. No emojis. No "thrilled"."""
                    reply = call_groq(reply_prompt, 150)
                    if reply:
                        sent = gmail_send(svc, sender, f"Re: {subject}",
                                          reply + f"\n\n— {YOUR_NAME}\n{EMAIL_ADDRESS}")
                        if sent:
                            matched["interview_reply_sent"] = True
                            print(f"  ✅ Auto-replied to {company}")

                elif label == "accepted":
                    updates["interviews"] += 1
                    matched["status"] = "accepted"

                    desktop_notify(
                        f"OFFER RECEIVED — {company}",
                        f"Company: {company}\nRole: {matched.get('title','')}\n"
                        f"From: {sender}\nSubject: {subject}\n\n"
                        f"⚠️  AGENT STOPPED — No more applications will be sent.\n"
                        f"Review the offer and respond within 48 hours.",
                        "🎉"
                    )
                    print(f"\n  🎉🎉 OFFER FROM {company.upper()}! Stopping agent.\n")

                elif label == "rejected":
                    updates["rejections"] += 1

            except Exception:
                continue

        save_applications(apps)

        # Send follow-ups for 4-day-old unanswered apps
        now = datetime.now()
        for app in apps:
            if any(a.get("status") == "accepted" for a in apps):
                break
            if (app.get("email_sent") and
                not app.get("reply_received") and
                not app.get("follow_up_sent") and
                app.get("status") not in ("interview","accepted","rejected")):
                try:
                    applied = datetime.fromisoformat(app.get("applied_at", now.isoformat()))
                    if (now - applied).days >= 4:
                        fu_prompt = f"""Write a follow-up email (max 80 words) for this job application with no reply.
Job: {app.get('title','')} at {app.get('company','')}
Applied: {applied.strftime('%B %d')}
Mention one metric: 110 FPS tracking OR 6M record pipeline OR 99% accuracy.
Ask if they need anything else. Professional, not desperate.
Sign: {YOUR_NAME}, {EMAIL_ADDRESS}"""
                        followup = call_groq(fu_prompt, 150)
                        if followup and app.get("email_to"):
                            sent = gmail_send(
                                svc, app["email_to"],
                                f"Following up: {app.get('title','')} Application",
                                followup
                            )
                            if sent:
                                app["follow_up_sent"] = True
                                app["follow_up_at"] = now.isoformat()
                                updates["follow_ups"] += 1
                                print(f"  📤 Follow-up → {app.get('company','')}")
                except Exception:
                    pass

        save_applications(apps)
        _update_stats(apps)

    except Exception as e:
        print(f"  ❌ Monitor error: {e}")
        traceback.print_exc()

    return updates

# ─── Dashboard ────────────────────────────────────────────────────────────────
def print_dashboard():
    apps  = load_applications()
    stats = load_json(STATS_FILE, {})
    print("\n" + "═"*58)
    print("  📊  TEJAS JOB AGENT — LIVE DASHBOARD")
    print("═"*58)
    print(f"  Total Applied   : {stats.get('total', len(apps))}")
    print(f"  Emails Sent     : {stats.get('sent', 0)}")
    print(f"  Interviews 🎯   : {stats.get('interviews', 0)}")
    print(f"  Pending ⏳       : {stats.get('pending', 0)}")
    print(f"  Rejections ❌   : {stats.get('rejections', 0)}")
    print(f"  Accepted 🎉     : {stats.get('accepted', 0)}")
    print(f"  Last Run        : {stats.get('last_run','never')[:19]}")
    src = stats.get("sources", {})
    if src:
        print("─"*58)
        print("  Sources: " + " | ".join(f"{k}:{v}" for k,v in src.items()))
    print("─"*58)
    if apps:
        print("  Recent (last 10):")
        for app in apps[-10:]:
            icon = {"interview":"🎯","accepted":"🎉","rejected":"❌","sent":"📤","saved":"📁"}.get(app.get("status",""),"⏳")
            print(f"  {icon} {app.get('company','?'):22} {app.get('title','?')[:28]}")
    print("═"*58)

# ─── Git + LinkedIn monitor for new project content ──────────────────────────
def check_new_projects():
    """Check GitHub for new commits/repos and suggest adding to projects.json"""
    print("\n🔍 Checking GitHub for new project activity...")
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--since=1 week ago"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path.home())
        )
        if result.stdout.strip():
            print("  📝 Recent git activity found:")
            for line in result.stdout.strip().split("\n")[:5]:
                print(f"     {line}")
            print("  💡 Consider updating core/projects.json with new work!")
        else:
            print("  No new git commits this week")
    except:
        print("  (Git check skipped — not in a repo)")

# ─── Main ────────────────────────────────────────────────────────────────────
def run(mode: str = "run"):
    print("\n" + "═"*58)
    print(f"  🤖  TEJAS JOB AGENT v4 — {mode.upper()}")
    print("═"*58)

    apps = load_applications()
    if any(a.get("status") == "accepted" for a in apps):
        print("\n  🎉 You have an accepted offer! Agent in standby.")
        print("  Delete logs/applications.json to restart.")
        return

    if not get_groq():
        print("  ❌ Set GROQ_API_KEY:  export GROQ_API_KEY=gsk_...")
        print("     Or save permanently: echo gsk_YOURKEY > .groq_key")
        sys.exit(1)

    gmail_svc = get_gmail() if GMAIL_AVAILABLE else None
    print(f"  Gmail: {'✅ connected' if gmail_svc else '📁 offline (saving to output/)'}")

    print("\n🔍 Scraping jobs...")
    jobs = scrape_jobs()
    print(f"  Found {len(jobs)} jobs total")

    new_jobs = filter_new(jobs)
    print(f"  {len(new_jobs)} new jobs")

    if not new_jobs:
        print("  Nothing new. Check back in 4 hours.")
        return

    projects = load_json(PROJECTS_FILE, [])
    if not projects:
        print("  ❌ No projects in core/projects.json")
        return

    limit = 2 if mode == "test" else MAX_PER_RUN
    batch = new_jobs[:limit]
    print(f"\n  Processing {len(batch)} jobs...\n")

    for i, job in enumerate(batch, 1):
        print(f"\n[{i}/{len(batch)}]", end="")
        try:
            process_job(job, projects, gmail_svc, dry_run=(mode=="test"))
        except Exception as e:
            print(f"\n  ❌ {job.get('company','?')}: {e}")
            if mode == "test": traceback.print_exc()
        if i < len(batch): time.sleep(DELAY_SECS)

    print(f"\n{'═'*58}")
    print(f"  ✅ Done! {len(batch)} applications processed.")
    print(f"  Check output/ folder for packages.")
    print("═"*58)
    _update_stats()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if   cmd == "test":      run("test")
    elif cmd == "run":       run("run")
    elif cmd == "monitor":
        print("\n📬 Checking Gmail...")
        svc = get_gmail()
        u = monitor_gmail(svc)
        print(f"  Interviews: {u.get('interviews',0)} | Follow-ups sent: {u.get('follow_ups',0)}")
    elif cmd == "dashboard":
        print_dashboard()
        import os as _os
        dash = BASE_DIR / "dashboard.html"
        if dash.exists():
            _os.system(f'powershell.exe Start "$(wslpath -w {dash})" 2>/dev/null || explorer.exe "$(wslpath -w {dash})" 2>/dev/null')
            print(f"  🌐 Opening dashboard in browser...")
    elif cmd == "projects":  check_new_projects()
    elif cmd == "savekey":
        if len(sys.argv) < 3:
            print("Usage: python3 main.py savekey gsk_YOUR_KEY_HERE")
        else:
            key = sys.argv[2]
            (BASE_DIR / ".groq_key").write_text(key)
            bashrc = Path.home() / ".bashrc"
            line = f'\nexport GROQ_API_KEY="{key}"\n'
            current = bashrc.read_text() if bashrc.exists() else ""
            if "GROQ_API_KEY" not in current:
                with open(bashrc, "a") as f: f.write(line)
            print("  ✅ Key saved permanently — no more export needed")
            print("  Now run: python3 main.py test")
    else:
        print("Usage: python3 main.py [test|run|monitor|dashboard|projects|savekey gsk_KEY]")