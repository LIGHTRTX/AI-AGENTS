#!/usr/bin/env python3
"""
Tejas Project Tracker
- Monitors GitHub repos for new commits
- Tracks project descriptions, stats, stack
- Suggests updates to projects.json for resume freshness
- Reads from ~/.gitconfig and local repos

Run: python3 project_tracker.py
"""

import os, json, subprocess, re
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
PROJECTS_FILE = BASE_DIR / "core" / "projects.json"
TRACKER_LOG   = BASE_DIR / "logs" / "project_tracker.json"

def run_git(cmd, cwd=None) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=10, cwd=cwd)
        return r.stdout.strip()
    except:
        return ""

def find_git_repos() -> list:
    """Find all git repos under home directory."""
    repos = []
    home = Path.home()
    for p in ["PROJECTS", "projects", "code", "dev", "work", "Desktop"]:
        base = home / p
        if base.exists():
            for d in base.rglob(".git"):
                repo_path = d.parent
                repos.append(repo_path)
    # Also check home directly
    for d in home.iterdir():
        if (d / ".git").exists():
            repos.append(d)
    return repos[:20]  # limit

def get_repo_info(repo_path: Path) -> dict:
    """Get recent activity from a git repo."""
    name = run_git(["git","remote","get-url","origin"], repo_path)
    name = name.split("/")[-1].replace(".git","") if name else repo_path.name

    recent_commits = run_git(
        ["git","log","--oneline","--since=30 days ago","--no-merges"],
        repo_path
    )

    last_commit_date = run_git(
        ["git","log","-1","--format=%ai"],
        repo_path
    )

    languages = run_git(["git","ls-files","--others","--exclude-standard","--cached"],
                        repo_path)

    all_files = run_git(["git","ls-files"], repo_path).split("\n")
    extensions = {}
    for f in all_files:
        ext = Path(f).suffix.lower()
        if ext:
            extensions[ext] = extensions.get(ext, 0) + 1

    top_langs = sorted(extensions.items(), key=lambda x: -x[1])[:5]
    stack = ", ".join(ext.lstrip(".") for ext, _ in top_langs)

    commit_lines = [c for c in recent_commits.split("\n") if c.strip()]

    return {
        "repo": str(repo_path),
        "name": name,
        "recent_commits": len(commit_lines),
        "last_commit": last_commit_date[:10] if last_commit_date else None,
        "stack_guess": stack,
        "recent_messages": [c.split(" ",1)[-1] for c in commit_lines[:5]]
    }

def check_projects_freshness(repos: list) -> list:
    """Compare repos to existing projects.json and flag new work."""
    existing = json.loads(PROJECTS_FILE.read_text()) if PROJECTS_FILE.exists() else []
    existing_names = {p.get("name","").lower() for p in existing}

    suggestions = []
    for repo in repos:
        if repo["recent_commits"] == 0:
            continue
        rname = repo["name"].lower().replace("-","_").replace(" ","_")
        is_new = not any(rname in n or n in rname for n in existing_names)

        suggestion = {
            "repo": repo["name"],
            "recent_commits": repo["recent_commits"],
            "last_commit": repo["last_commit"],
            "is_new": is_new,
            "stack_guess": repo["stack_guess"],
            "recent_messages": repo["recent_messages"],
        }
        if is_new:
            suggestion["action"] = "⚠️  NEW PROJECT — consider adding to projects.json"
        else:
            suggestion["action"] = "✅ Existing project — review if impact metrics changed"
        suggestions.append(suggestion)

    return suggestions

def main():
    print("\n🔍 Scanning GitHub repos...\n")
    repos = find_git_repos()

    if not repos:
        print("  No git repos found in common directories.")
        print("  Checked: ~/PROJECTS, ~/projects, ~/code, ~/dev\n")
        return

    print(f"  Found {len(repos)} repos\n")

    repo_data = []
    for rp in repos:
        info = get_repo_info(rp)
        if info["recent_commits"] > 0 or info["last_commit"]:
            repo_data.append(info)
            days_ago = ""
            if info["last_commit"]:
                try:
                    d = datetime.fromisoformat(info["last_commit"])
                    delta = (datetime.now() - d).days
                    days_ago = f"({delta}d ago)"
                except:
                    pass
            print(f"  📦 {info['name'][:30]:32} {info['recent_commits']:3} commits {days_ago}")
            for msg in info["recent_messages"][:2]:
                print(f"       └─ {msg[:60]}")

    suggestions = check_projects_freshness(repo_data)
    new_projects = [s for s in suggestions if s["is_new"] and s["recent_commits"] >= 2]

    print(f"\n{'─'*60}")
    if new_projects:
        print(f"\n⚠️  {len(new_projects)} NEW PROJECT(S) found — not in resume:\n")
        for p in new_projects:
            print(f"  📁 {p['repo']}")
            print(f"     Last commit: {p['last_commit']}")
            print(f"     Commits (30d): {p['recent_commits']}")
            print(f"     Stack guess: {p['stack_guess']}")
            print(f"     Recent: {', '.join(p['recent_messages'][:2])}")
            print()
        print("  💡 Add these to: core/projects.json")
        print("     Use this template:")
        for p in new_projects[:1]:
            template = {
                "id": p["repo"].lower().replace(" ","_")[:20],
                "name": p["repo"],
                "stack": p["stack_guess"],
                "impact": "TODO: Add specific metrics (latency, accuracy, throughput)",
                "description": "TODO: 2-sentence description for resume",
            }
            print(f"\n  {json.dumps(template, indent=4)}")
    else:
        print("\n  ✅ All recent repos are already in projects.json")

    # Save tracker log
    log = {
        "checked_at": datetime.now().isoformat(),
        "repos_found": len(repos),
        "active_repos": len(repo_data),
        "new_suggestions": new_projects
    }
    TRACKER_LOG.parent.mkdir(exist_ok=True)
    TRACKER_LOG.write_text(json.dumps(log, indent=2))

    print(f"\n  Log saved: logs/project_tracker.json")
    print("─"*60 + "\n")

if __name__ == "__main__":
    main()
