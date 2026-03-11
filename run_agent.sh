#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Tejas Job Agent v4 — Daemon
# Runs every 4 hours: scrape → apply → monitor Gmail
# Auto-starts on login via ~/.bashrc or Windows Task Scheduler
# ─────────────────────────────────────────────────────────────────────────────

AGENT_DIR="$HOME/PROJECTS/ai_agent/tejas-job-agent-v3/tejas-agent"
VENV="$HOME/PROJECTS/venv/bin/activate"
LOG="$AGENT_DIR/logs/daemon.log"
INTERVAL=14400  # 4 hours in seconds

# ── SET YOUR GROQ KEY HERE ──────────────────────────────────────────────────
export GROQ_API_KEY="gsk_PASTE_YOUR_KEY_HERE"

# ──────────────────────────────────────────────────────────────────────────────
echo "═══════════════════════════════════════════" >> "$LOG"
echo "🤖 Daemon started: $(date)" >> "$LOG"
echo "═══════════════════════════════════════════" >> "$LOG"

run_cycle() {
  echo "" >> "$LOG"
  echo "── Cycle start: $(date) ──" >> "$LOG"

  source "$VENV"
  cd "$AGENT_DIR"

  echo "[RUN] Applying to jobs..." >> "$LOG"
  python3 main.py run >> "$LOG" 2>&1

  echo "[MONITOR] Checking Gmail..." >> "$LOG"
  python3 main.py monitor >> "$LOG" 2>&1

  echo "[PROJECTS] Checking GitHub..." >> "$LOG"
  python3 main.py projects >> "$LOG" 2>&1

  echo "── Cycle done: $(date) ──" >> "$LOG"
}

# Run immediately on start
run_cycle

# Then loop every 4 hours
while true; do
  sleep $INTERVAL
  run_cycle
done
