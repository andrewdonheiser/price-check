# price-check

A CLI tool that scans local Claude Code JSONL session files and reports token usage and estimated costs, broken down by model, speed, and reasoning effort.

<img width="1637" height="192" alt="Screenshot 2026-08-06 at 11 37 36 AM" src="https://github.com/user-attachments/assets/0342a679-7af5-442a-9f5f-b7fc7a427266" />

## Features

- **Per-model cost tracking** with correct rates for all Claude models (Opus, Sonnet, Haiku, Fable, Mythos)
- **Dynamic pricing** — fetches latest rates from Anthropic on session start, no hardcoded values
- **Daily usage summary** with token breakdown (cache read, cache write, LLM output) and cost estimates
- **Period totals** — Today, Week, and Month cost aggregates with per-model breakdown in the status line
- **Turn tracking** — counts unique prompts (turns) per session and per day, shown in the status line and daily table
- **Period subtotals** — week and month subtotal rows inserted at boundaries in the daily table (week shown at 7+ days, month at 28+)
- **Per-session drill-down** for any given date, with per-model sub-rows for multi-model sessions
- **Project-level aggregation** across all sessions
- **Top projects per day** view
- **Volume discount** — applies a configurable volume discount (default 13%) to all cost calculations
- **Per-prompt cost tracking** — status line shows cost for the current prompt (not just the last API call increment), using `promptId` boundaries from the JSONL
- **Subagent tracking** — discovers subagent JSONL files (including nested `workflows/wf_*/` directories) and displays per-type invocation counts (e.g. `agents: Explore×3, general-purpose×2`)
- **Claude Code status line** showing per-model prompt, session, and period costs with speed, effort tags, and subagent counts
- **Live status line** — scans session JSONL directly when the Stop hook hasn't fired yet (e.g. plan mode), so costs are never stale
- **Rates table** — view current pricing for all models with `--rates`
- **Markdown export** with clipboard copy support (cross-platform: macOS, Linux, Windows)

## Requirements

- Python 3.9+
- No external dependencies (stdlib only)
- Claude Code installed (reads from `~/.claude/projects/`)

## Installation

### Option 1: Direct download

1. Save `main.py` somewhere on your PATH:

   ```bash
   cp main.py /usr/local/bin/price-check
   chmod +x /usr/local/bin/price-check
   ```

2. Verify it works:

   ```bash
   price-check
   ```

### Option 2: Run from the repo

1. Clone or download this repository:

   ```bash
   git clone <repo-url>
   cd price-check
   ```

2. Run directly:

   ```bash
   python3 main.py
   ```

### Setting up Claude Code hooks

Add the following to your Claude Code settings (`~/.claude/settings.json`):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/price-check/main.py --session-start",
            "timeout": 20
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/price-check/main.py --hook",
            "timeout": 10
          }
        ]
      }
    ]
  },
  "statusLine": {
    "type": "command",
    "command": "python3 /path/to/price-check/main.py --status-line"
  }
}
```

Replace `/path/to/price-check` with the actual path where you saved the script.

This gives you:

- **SessionStart hook** — fetches latest model pricing from Anthropic when Claude Code starts
- **Stop hook** — records per-model token usage after each prompt
- **Status line** — shows per-model cost breakdown with subagent counts, period totals, and turn counts:

  ```
  Prompt: Opus 4.6: 15c (253.2K) [std,hi] | Haiku 4.5: 2c (80K) [std] | agents: Explore×2
  Session: Opus 4.6: $4.8 (5.2M) [std,hi] | Haiku 4.5: 5c (300K) [std] | agents: Explore×5, general-purpose×3
  Today: Opus 4.6 [std,hi]: $12.30 (10M) | Opus 4.6 [std,med]: $3.20 (2M) | Haiku 4.5: 5c (150K)
  Week: Opus 4.6 [std,hi]: $70.00 (56M) | Opus 4.6 [std,med]: $15.20 (12M) | Haiku 4.5: 23c (850K)
  Month: Opus 4.6 [std,hi]: $280.00 (224M) | Opus 4.6 [std,med]: $62.10 (56M) | Haiku 4.5: 91c (3.4M)
  Turns: 5 (prompt) | 42 (session) | 128 (today) | 890 (week) | 3.2K (month)
  ```

## Usage

### Daily summary (default)

```bash
# Last 7 days (default)
python3 main.py

# Last 30 days
python3 main.py 30
```

```
  🔬 Claude Code Token Usage  (last 7 days)

  ┌──────────────┬────────┬────────┬──────────────┬───────────┬───────────┬──────────┬────────┬──────────┬───────────┐
  │ Date         │  Calls │  Turns │     Model(s) │   CacheRd │   CacheWr │      LLM │   Hit% │    Total │      Cost │
  ├──────────────┼────────┼────────┼──────────────┼───────────┼───────────┼──────────┼────────┼──────────┼───────────┤
  │ 2026-08-03   │    395 │     79 │     Opus 4.6 │     44.1M │      2.6M │   121.0K │   100% │    46.8M │    $35.91 │
  │ 2026-08-04   │    609 │     94 │ Opus 4.6, .. │     62.5M │      2.0M │   216.9K │   100% │    64.7M │    $40.16 │
     Opus 4.6     calls=553   rd= 61.7M  wr=  1.5M  out=197.6K  tok= 63.4M  cost=$39.55
     Haiku 4.5    calls=56    rd=820.4K  wr=415.3K  out= 19.3K  tok=  1.3M  cost=$0.61
  │ 2026-08-05   │    775 │    120 │ Opus 4.6, .. │     47.9M │      3.5M │   257.4K │   100% │    51.7M │    $35.04 │
  │ 2026-08-06   │    210 │     13 │ Opus 4.6, .. │     11.3M │    838.4K │    74.3K │   100% │    12.2M │     $9.92 │
  ├──────────────┼────────┼────────┼──────────────┼───────────┼───────────┼──────────┼────────┼──────────┼───────────┤
  │   2026-W32   │   1989 │    306 │              │    165.9M │      8.9M │   669.6K │   100% │   175.5M │   $121.03 │
  ├──────────────┼────────┼────────┼──────────────┼───────────┼───────────┼──────────┼────────┼──────────┼───────────┤
  │ Total        │   1989 │    306 │              │    165.9M │      8.9M │   669.6K │   100% │   175.5M │   $121.03 │
  └──────────────┴────────┴────────┴──────────────┴───────────┴───────────┴──────────┴────────┴──────────┴───────────┘

  Per-model totals:
    Opus 4.6     calls=1645  rd=159.4M  wr=  6.5M  out=586.4K  tok=166.5M  cost=$117.44
    Haiku 4.5    calls=344   rd=  6.5M  wr=  2.4M  out= 83.2K  tok=  9.0M  cost=$3.60

  Rates ($/MTok):
    Opus 4.6        in=$5.0     out=$25.0    crd=$0.5     cwr=6.25
    Haiku 4.5       in=$1.0     out=$5.0     crd=$0.1     cwr=1.25
  Updated: 2026-08-06
```

### Sessions for a specific date

```bash
python3 main.py --sessions today
python3 main.py --sessions yesterday
python3 main.py --sessions 2026-07-27
```

```
  🔬 Sessions  (2026-08-04)

  ┌────────────────────────────────┬────────────────┬──────────────┬───────────┬───────────┬──────────┬───────────┬───────────┐
  │ Session                        │        Project │     Model(s) │   CacheRd │   CacheWr │      LLM │     Total │      Cost │
  ├────────────────────────────────┼────────────────┼──────────────┼───────────┼───────────┼──────────┼───────────┼───────────┤
  │ Casual greeting conversation   │    price-check │ Opus 4.6, .. │     37.3M │    847.9K │    95.6K │     38.3M │    $24.00 │
     Opus 4.6     calls=225   rd= 36.7M  wr=491.4K  out= 79.9K  tok= 37.3M  cost=$23.41
     Haiku 4.5    calls=44    rd=661.1K  wr=356.5K  out= 15.8K  tok=  1.0M  cost=$0.59
  │ Follow PR deployment instruc.. │ REVIEW_WORK-ag │     Opus 4.6 │      7.0M │    236.7K │    32.3K │      7.3M │     $5.80 │
  │ Verify cluster prerequisites.. │ REVIEW_WORK-ag │     Opus 4.6 │      3.9M │    324.2K │    20.0K │      4.3M │     $4.50 │
  │ Show per-prompt cost in Clau.. │    price-check │ Opus 4.6, .. │      4.0M │    226.4K │    29.4K │      4.2M │     $3.70 │
     Opus 4.6     calls=53    rd=  3.8M  wr=167.7K  out= 25.9K  tok=  4.0M  cost=$3.60
     Haiku 4.5    calls=12    rd=159.2K  wr= 58.8K  out=  3.5K  tok=222.2K  cost=$0.11
  │ Resume from deployment test .. │ REVIEW_WORK-ag │     Opus 4.6 │      1.0M │    100.4K │     8.8K │      1.1M │     $1.35 │
  │ Review GitHub PR #264 changes  │ REVIEW_WORK-ag │     Opus 4.6 │    358.0K │     36.3K │     6.1K │    400.3K │     $0.56 │
  │ Install OpenShell CLI on RHO.. │ REVIEW_WORK-ag │     Opus 4.6 │    359.4K │     34.5K │     2.1K │    396.1K │     $0.45 │
  │ Review GitHub PR #295          │ REVIEW_WORK-ag │     Opus 4.6 │    196.9K │     35.2K │     2.6K │    234.8K │     $0.38 │
  │ Troubleshoot OpenShell insta.. │ REVIEW_WORK-ag │     Opus 4.6 │     15.3K │     16.3K │      282 │     31.9K │     $0.12 │
  ├────────────────────────────────┼────────────────┼──────────────┼───────────┼───────────┼──────────┼───────────┼───────────┤
  │ Total (9)                      │                │              │     54.2M │      1.9M │   197.3K │     56.3M │    $40.86 │
  └────────────────────────────────┴────────────────┴──────────────┴───────────┴───────────┴──────────┴───────────┴───────────┘

  Per-model totals:
    Opus 4.6     calls=502   rd= 53.4M  wr=  1.4M  out=178.0K  tok= 55.0M  cost=$40.16
    Haiku 4.5    calls=56    rd=820.4K  wr=415.3K  out= 19.3K  tok=  1.3M  cost=$0.70

  Rates ($/MTok):
    Opus 4.6        in=$5.0     out=$25.0    crd=$0.5     cwr=6.25
    Haiku 4.5       in=$1.0     out=$5.0     crd=$0.1     cwr=1.25
  Updated: 2026-08-05
```

### Project views

```bash
# Aggregated tokens per project
python3 main.py --projects

# Top 5 projects per day
python3 main.py --top-projects

# With a custom lookback window
python3 main.py --projects 30
```

```
  🔬 Projects Summary  (last 7 days)

  ┌──────────────────────┬───────┬──────────────┬───────────┬───────────┬──────────┬───────────┬───────────┐
  │ Project              │  #Ses │     Model(s) │   CacheRd │   CacheWr │      LLM │     Total │      Cost │
  ├──────────────────────┼───────┼──────────────┼───────────┼───────────┼──────────┼───────────┼───────────┤
  │ jira                 │     6 │     Opus 4.6 │     44.1M │      2.6M │   121.0K │     46.8M │    $41.27 │
  │ price-check          │     2 │ Opus 4.6, .. │     41.3M │      1.1M │   125.0K │     42.5M │    $27.70 │
     Opus 4.6     calls=278   rd= 40.5M  wr=659.1K  out=105.7K  tok= 41.2M  cost=$27.01
     Haiku 4.5    calls=56    rd=820.4K  wr=415.3K  out= 19.3K  tok=  1.3M  cost=$0.70
  │ REVIEW_WORK-agentic- │     7 │     Opus 4.6 │     12.9M │    783.7K │    72.3K │     13.8M │    $13.16 │
  ├──────────────────────┼───────┼──────────────┼───────────┼───────────┼──────────┼───────────┼───────────┤
  │ Total (3)            │    15 │              │     98.3M │      4.4M │   318.2K │    103.1M │    $82.14 │
  └──────────────────────┴───────┴──────────────┴───────────┴───────────┴──────────┴───────────┴───────────┘

  Per-model totals:
    Opus 4.6     calls=897   rd= 97.5M  wr=  4.0M  out=298.9K  tok=101.8M  cost=$81.44
    Haiku 4.5    calls=56    rd=820.4K  wr=415.3K  out= 19.3K  tok=  1.3M  cost=$0.70

  Rates ($/MTok):
    Opus 4.6        in=$5.0     out=$25.0    crd=$0.5     cwr=6.25
    Haiku 4.5       in=$1.0     out=$5.0     crd=$0.1     cwr=1.25
  Updated: 2026-08-05
```

### Model rates

```bash
python3 main.py --rates
```

```
  💲 Model Rates  ($/MTok, 13% discount, updated 2026-08-05)

  ┌────────────────┬──────────┬──────────┬──────────┬──────────┐
  │ Model          │    Input │   Output │  CacheRd │  CacheWr │
  ├────────────────┼──────────┼──────────┼──────────┼──────────┤
  │ Opus 4.1       │    $15.0 │    $75.0 │     $1.5 │   $18.75 │
  │ Fable 5        │    $10.0 │    $50.0 │     $1.0 │    $12.5 │
  │ Mythos 5       │    $10.0 │    $50.0 │     $1.0 │    $12.5 │
  │ Opus 5         │     $5.0 │    $25.0 │     $0.5 │    $6.25 │
  │ Opus 4.8       │     $5.0 │    $25.0 │     $0.5 │    $6.25 │
  │ Opus 4.7       │     $5.0 │    $25.0 │     $0.5 │    $6.25 │
  │ Opus 4.6       │     $5.0 │    $25.0 │     $0.5 │    $6.25 │
  │ Opus 4.5       │     $5.0 │    $25.0 │     $0.5 │    $6.25 │
  │ Sonnet 4.6     │     $3.0 │    $15.0 │     $0.3 │    $3.75 │
  │ Sonnet 4.5     │     $3.0 │    $15.0 │     $0.3 │    $3.75 │
  │ Sonnet 5       │     $2.0 │    $10.0 │     $0.2 │     $2.5 │
  │ Haiku 4.5      │     $1.0 │     $5.0 │     $0.1 │    $1.25 │
  └────────────────┴──────────┴──────────┴──────────┴──────────┘
```

### Markdown and clipboard

```bash
# Print as markdown table
python3 main.py --markdown

# Print as markdown and copy to clipboard
python3 main.py --markdown --copy

# Print the normal table view but also copy markdown to clipboard
python3 main.py --copy
```

## Pricing

Rates are fetched automatically from [Anthropic's pricing page](https://platform.claude.com/docs/en/about-claude/pricing) when Claude Code starts (via the `SessionStart` hook) and cached at `~/.claude/price-check-rates.json`. If the fetch fails (offline, etc.), cached data is used. If no pricing data exists at all, costs display as `n/a`.

A 13% volume discount is applied to all cost calculations (configurable via the `_DISCOUNT` constant in `main.py`). The discount percentage is shown in the `--rates` output header.

Force-refresh with `--update-pricing`. View current rates with `--rates`.

## Acknowledgments

Based on [claude-usage](https://gist.github.com/rhuss/67a7d9d300285350ff12563b6074a9e4) by [Roland Huss](https://github.com/rhuss). The original script provides the core token scanning and table rendering. This fork adds per-model cost tracking, dynamic pricing, subagent support, speed/effort tracking, the Claude Code hook and status line integration, and security hardening.
