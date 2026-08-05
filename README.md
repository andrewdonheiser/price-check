# price-check

A CLI tool that scans local Claude Code JSONL session files and reports token usage and estimated costs, broken down by model, speed, and reasoning effort.

## Features

- **Per-model cost tracking** with correct rates for all Claude models (Opus, Sonnet, Haiku, Fable, Mythos)
- **Dynamic pricing** — fetches latest rates from Anthropic on session start, no hardcoded values
- **Daily usage summary** with token breakdown (cache read, cache write, LLM output) and cost estimates
- **Per-session drill-down** for any given date, with per-model sub-rows for multi-model sessions
- **Project-level aggregation** across all sessions
- **Top projects per day** view
- **Subagent tracking** — picks up Haiku/Sonnet subagent calls from the `subagents/` directory
- **Claude Code status line** showing per-model prompt and session costs with speed and effort level
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
- **Stop hook** — records per-model token usage after each turn
- **Status line** — shows per-model cost breakdown:

  ```
  Prompt: Opus 4.6: 15c (253.2K) [standard,high] | Haiku 4.5: 2c (80K) [standard]
  Session: Opus 4.6: $4.8 (5.2M) [standard,high] | Haiku 4.5: 5c (300K) [standard]
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

  ┌──────────────┬────────┬──────────────┬───────────┬───────────┬──────────┬────────┬──────────┬───────────┐
  │ Date         │  Calls │     Model(s) │   CacheRd │   CacheWr │      LLM │   Hit% │    Total │      Cost │
  ├──────────────┼────────┼──────────────┼───────────┼───────────┼──────────┼────────┼──────────┼───────────┤
  │ 2026-08-03   │    395 │     Opus 4.6 │     44.1M │      2.6M │   121.0K │   100% │    46.8M │    $41.27 │
  │ 2026-08-04   │    557 │ Opus 4.6, .. │     54.0M │      1.9M │   196.8K │   100% │    56.0M │    $40.73 │
     Opus 4.6     calls=501   rd= 53.1M  wr=  1.4M  out=177.6K  tok= 54.8M  cost=$40.03
     Haiku 4.5    calls=56    rd=820.4K  wr=415.3K  out= 19.3K  tok=  1.3M  cost=$0.70
  ├──────────────┼────────┼──────────────┼───────────┼───────────┼──────────┼────────┼──────────┼───────────┤
  │ Total        │    952 │              │     98.1M │      4.4M │   317.8K │   100% │   102.8M │    $82.00 │
  └──────────────┴────────┴──────────────┴───────────┴───────────┴──────────┴────────┴──────────┴───────────┘

  Per-model totals:
    Opus 4.6     calls=896   rd= 97.3M  wr=  4.0M  out=298.5K  tok=101.6M  cost=$81.30
    Haiku 4.5    calls=56    rd=820.4K  wr=415.3K  out= 19.3K  tok=  1.3M  cost=$0.70

  Rates ($/MTok):
    Opus 4.6        in=$5.0     out=$25.0    crd=$0.5     cwr=6.25
    Haiku 4.5       in=$1.0     out=$5.0     crd=$0.1     cwr=1.25
  Updated: 2026-08-05
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
  💲 Model Rates  ($/MTok, updated 2026-08-05)

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

Force-refresh with `--update-pricing`. View current rates with `--rates`.

## Acknowledgments

Based on [claude-usage](https://gist.github.com/rhuss/67a7d9d300285350ff12563b6074a9e4) by [Roland Huss](https://github.com/rhuss). The original script provides the core token scanning and table rendering. This fork adds per-model cost tracking, dynamic pricing, subagent support, speed/effort tracking, the Claude Code hook and status line integration, and security hardening.
