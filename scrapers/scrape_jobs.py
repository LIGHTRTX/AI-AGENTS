#!/usr/bin/env python3
"""
Tejas Job Agent — Scraper v3
Sources: RemoteOK, Remotive, Jobicy, Arbeitnow, LinkedIn, Wellfound, YCombinator
Usage: python3 scrape_jobs.py          → prints job count
       python3 scrape_jobs.py --json   → prints JSON array on last line
"""

import requests, json, time, re, sys
from datetime import datetime
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

TITLE_KEYWORDS = [
    "machine learning", "ml engineer", "computer vision", "cv engineer",
    "ai engineer", "data scientist", "data analyst", "deep learning",
    "llm", "nlp engineer", "pytorch", "applied ml", "analytics engineer",
    "mlops", "ml ops", "artificial intelligence", "python developer",
    "ai researcher", "yolo", "vision engineer",
]

EXCLUDE_TITLE = [
    "frontend", "ios developer", "android", "devops", "blockchain",
    "defense", "marketing", "editor", "10+ years", "staff engineer",
    "principal engineer", "vp of", "director of", "head of",
]

def is_relevant(title: str, desc: str = "") -> bool:
    text = (title + " " + desc[:300]).lower()
    if any(ex in text for ex in EXCLUDE_TITLE):
        return False
    return any(kw in text for kw in TITLE_KEYWORDS)

def clean(t: str) -> str:
    return re.sub(r'\s+', ' ', t or "").strip()

def job(src, title, company, url, desc=""):
    return {
        "source": src, "title": clean(title), "company": clean(company),
        "url": url, "location": "Remote",
        "description": clean(desc)[:800],
        "scraped_at": datetime.now().isoformat()
    }

# ── RemoteOK ─────────────────────────────────────────────────────────────────
def scrape_remoteok():
    jobs, seen = [], set()
    for tag in ["machine-learning","ai","python","deep-learning","data-science","computer-vision"]:
        try:
            r = requests.get(f"https://remoteok.com/api?tag={tag}",
                             headers={**HEADERS,"Accept":"application/json"}, timeout=15)
            for j in r.json()[1:]:
                url = j.get("url","")
                if url in seen: continue
                title = j.get("position","")
                desc  = BeautifulSoup(j.get("description",""),"html.parser").get_text()
                if is_relevant(title, desc):
                    seen.add(url)
                    jobs.append(job("RemoteOK", title, j.get("company","?"), url, desc))
            time.sleep(2)
        except Exception as e:
            pass
    return jobs

# ── Remotive ─────────────────────────────────────────────────────────────────
def scrape_remotive():
    jobs, seen = [], set()
    for q in ["machine learning","data science","artificial intelligence","computer vision"]:
        try:
            r = requests.get("https://remotive.com/api/remote-jobs",
                             params={"search": q, "limit": 20},
                             headers=HEADERS, timeout=15)
            for j in r.json().get("jobs",[]):
                url = j.get("url","")
                if url in seen: continue
                title = j.get("title","")
                desc  = BeautifulSoup(j.get("description",""),"html.parser").get_text()
                if is_relevant(title, desc):
                    seen.add(url)
                    jobs.append(job("Remotive", title, j.get("company_name","?"), url, desc))
            time.sleep(1)
        except Exception as e:
            pass
    return jobs

# ── Jobicy ───────────────────────────────────────────────────────────────────
def scrape_jobicy():
    jobs = []
    for tag in ["machine-learning","data-science","artificial-intelligence"]:
        try:
            r = requests.get("https://jobicy.com/api/v2/remote-jobs",
                             params={"count":50,"tag":tag},
                             headers=HEADERS, timeout=15)
            for j in r.json().get("jobs",[]):
                url   = j.get("url","")
                title = j.get("jobTitle","")
                desc  = j.get("jobDescription","")
                if is_relevant(title, desc) and not any(x["url"]==url for x in jobs):
                    jobs.append(job("Jobicy", title, j.get("companyName","?"), url, desc))
            time.sleep(1)
        except: pass
    return jobs

# ── Arbeitnow ────────────────────────────────────────────────────────────────
def scrape_arbeitnow():
    jobs = []
    try:
        r = requests.get("https://www.arbeitnow.com/api/job-board-api",
                         params={"remote":"true"}, headers=HEADERS, timeout=15)
        for j in r.json().get("data",[])[:60]:
            title = j.get("title","")
            tags  = " ".join(j.get("tags",[]))
            desc  = j.get("description","")
            if is_relevant(title, desc+" "+tags):
                jobs.append(job("Arbeitnow", title, j.get("company_name","?"),
                                j.get("url",""), desc))
    except: pass
    return jobs

# ── LinkedIn ─────────────────────────────────────────────────────────────────
def scrape_linkedin():
    jobs, seen = [], set()
    searches = [
        ("machine learning engineer","Worldwide"),
        ("computer vision engineer","Worldwide"),
        ("AI engineer remote","Worldwide"),
        ("data scientist remote","Worldwide"),
        ("data analyst remote","Worldwide"),
        ("MLOps engineer","Worldwide"),
        ("NLP engineer remote","Worldwide"),
    ]
    for keyword, location in searches:
        try:
            params = {
                "keywords": keyword, "location": location,
                "f_WT": "2", "f_E": "1,2", "sortBy": "DD"
            }
            r = requests.get("https://www.linkedin.com/jobs/search",
                             params=params, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.find_all("div", class_=re.compile(r"job-search-card|base-card"))
            for card in cards:
                try:
                    t_el = card.find(["h3","h4"], class_=re.compile(r"title"))
                    c_el = card.find(["h4","a"],  class_=re.compile(r"company"))
                    l_el = card.find("a", href=True)
                    title   = clean(t_el.text) if t_el else ""
                    company_raw = clean(c_el.text) if c_el else ""
                    # Strip location/extra text after newline
                    company = company_raw.split("\n")[0].strip() if company_raw else "Company"
                    link    = l_el["href"].split("?")[0] if l_el else ""
                    if title and link not in seen and is_relevant(title):
                        seen.add(link)
                        jobs.append(job("LinkedIn", title, company, link))
                except: pass
            time.sleep(3)
        except Exception as e:
            pass
    return jobs

# ── Wellfound ────────────────────────────────────────────────────────────────
def scrape_wellfound():
    jobs = []
    for slug in ["ml-engineer","data-scientist","ai-engineer"]:
        try:
            r = requests.get(f"https://wellfound.com/role/r/{slug}",
                             headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            script = soup.find("script", id="__NEXT_DATA__")
            if script:
                data = json.loads(script.string)
                listings = (data.get("props",{}).get("pageProps",{})
                              .get("jobListings",[]))
                for item in listings[:15]:
                    title   = item.get("role",{}).get("name", slug.replace("-"," ").title())
                    company = item.get("startup",{}).get("name","Startup")
                    s       = item.get("slug","")
                    url     = f"https://wellfound.com/jobs/{s}" if s else "https://wellfound.com/jobs"
                    if is_relevant(title):
                        jobs.append(job("Wellfound", title, company, url))
            time.sleep(2)
        except: pass
    return jobs

# ── YCombinator ──────────────────────────────────────────────────────────────
def scrape_ycombinator():
    jobs = []
    for q in ["machine learning","computer vision","data science"]:
        try:
            r = requests.get("https://www.workatastartup.com/jobs",
                             params={"q":q,"remote":"true","jobType":"fulltime"},
                             headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            script = soup.find("script", id="__NEXT_DATA__")
            if script:
                data = json.loads(script.string)
                job_list = (data.get("props",{}).get("pageProps",{})
                               .get("jobs",[]))
                for j in job_list[:20]:
                    title = j.get("title","")
                    company = j.get("company",{}).get("name","YC Startup")
                    jid   = j.get("id","")
                    url   = f"https://www.workatastartup.com/jobs/{jid}"
                    desc  = j.get("description","")
                    if is_relevant(title, desc):
                        jobs.append(job("YCombinator", title, company, url, desc))
            time.sleep(2)
        except: pass
    return jobs

# ── Master ───────────────────────────────────────────────────────────────────
SCRAPERS = {
    "remoteok":    scrape_remoteok,
    "remotive":    scrape_remotive,
    "jobicy":      scrape_jobicy,
    "arbeitnow":   scrape_arbeitnow,
    "linkedin":    scrape_linkedin,
    "wellfound":   scrape_wellfound,
    "ycombinator": scrape_ycombinator,
}

def scrape_all(sources=None):
    fns = {k:v for k,v in SCRAPERS.items() if not sources or k in sources}
    all_jobs = []
    for name, fn in fns.items():
        print(f"  Scraping {name}...", flush=True)
        try:
            found = fn()
            print(f"  → {len(found)} jobs on {name}", flush=True)
            all_jobs.extend(found)
        except Exception as e:
            print(f"  → {name} failed: {e}", flush=True)
        time.sleep(1)

    # Deduplicate
    seen, unique = set(), []
    for j in all_jobs:
        key = (j.get("url") or j.get("title",""))[:120]
        if key not in seen:
            seen.add(key)
            unique.append(j)
    return unique

if __name__ == "__main__":
    json_mode = "--json" in sys.argv
    src = [a for a in sys.argv[1:] if not a.startswith("-")]
    jobs = scrape_all(src if src else None)
    print(f"\nTotal unique jobs: {len(jobs)}", flush=True)
    if json_mode:
        print(json.dumps(jobs))
    else:
        for j in jobs[:5]:
            print(f"  {j['source']:12} {j['title'][:38]:40} @ {j['company'][:25]}")
