#!/usr/bin/env python3
"""Claude Code token usage report. Scans local JSONL session files.

Single-file, no dependencies beyond Python 3.9+ stdlib.
Install: save anywhere on PATH, chmod +x.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_JSONL_SIZE = 100 * 1024 * 1024  # 100 MB

PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICING_FILE = Path.home() / ".claude" / "price-check-rates.json"


def _fetch_pricing() -> dict:
    req = urllib.request.Request(PRICING_URL, headers={"User-Agent": "price-check/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode()

    # Find the model pricing table (has "Base Input Tokens" header)
    tables = re.findall(r"<table.*?</table>", html, re.DOTALL)
    pricing_table = None
    for table in tables:
        if "Base Input" in table and "Cache Hits" in table:
            pricing_table = table
            break
    if not pricing_table:
        raise RuntimeError("Could not find model pricing table on page")

    rows = re.findall(r"<tr.*?>(.*?)</tr>", pricing_table, re.DOTALL)

    def parse_price(cell: str) -> float | None:
        m = re.search(r"\$([0-9.]+)", cell)
        return float(m.group(1)) if m else None

    def strip_html(s: str) -> str:
        return re.sub(r"<[^>]+>", "", s).strip()

    models = {}
    for row in rows[1:]:  # skip header
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(cells) < 6:
            continue
        name_raw = strip_html(cells[0])
        if "retired" in name_raw.lower():
            continue

        input_price = parse_price(cells[1])
        cache_write = parse_price(cells[2])
        cache_read = parse_price(cells[4])
        output_price = parse_price(cells[5])

        if not all(v is not None for v in [input_price, cache_write, cache_read, output_price]):
            continue

        # Clean name: remove parentheticals, "through/starting" date qualifiers
        name_clean = re.sub(r"\(.*?\)", "", name_raw).strip()
        name_clean = re.sub(r"\s*through\s+.*", "", name_clean, flags=re.IGNORECASE).strip()
        name_clean = re.sub(r"\s*starting\s+.*", "", name_clean, flags=re.IGNORECASE).strip()

        label = name_clean.replace("Claude ", "")
        # Convert "Claude Opus 4.6" -> "claude-opus-4-6"
        model_id = re.sub(r"(\d+)\.(\d+)", r"\1-\2", name_clean.lower().replace(" ", "-"))

        if model_id not in models:
            models[model_id] = {
                "input": input_price,
                "cache_read": cache_read,
                "cache_write": cache_write,
                "output": output_price,
                "label": label,
            }

    if not models:
        raise RuntimeError("Failed to parse any models from pricing page")
    return models


def update_pricing():
    print("Fetching latest pricing from Anthropic...")
    try:
        models = _fetch_pricing()
    except (urllib.error.URLError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    PRICING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PRICING_FILE.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": PRICING_URL,
        "models": models,
    }, indent=2))

    print(f"Saved {len(models)} models to {PRICING_FILE}")
    print()
    for mid, p in sorted(models.items()):
        print(f"  {p['label']:20s}  in=${p['input']:<6}  out=${p['output']:<6}  "
              f"crd=${p['cache_read']:<6}  cwr=${p['cache_write']}")


def print_rates():
    _ensure_pricing()
    if not MODEL_PRICING:
        print("No pricing data. Restart Claude Code or run --update-pricing.")
        return

    W = [14, 8, 8, 8, 8]
    bar, row = _table_helpers(W)

    print()
    updated = _PRICING_UPDATED[:10] if _PRICING_UPDATED else "unknown"
    disc_pct = int(_DISCOUNT * 100)
    print(f"  \U0001f4b2 {bold(c(75, 'Model Rates'))}  {dim(f'($/MTok, {disc_pct}% discount, updated {updated})')}")
    print()

    hdr_c = [252] * 5
    print(f"  {bar('┌', '┬', '┐')}")
    print(f"  {row('Model', 'Input', 'Output', 'CacheRd', 'CacheWr', colors=hdr_c, is_bold=True)}")
    print(f"  {bar('├', '┼', '┤')}")

    for mid in sorted(MODEL_PRICING, key=lambda m: MODEL_PRICING[m]["output"], reverse=True):
        p = MODEL_PRICING[mid]
        label = p.get("label") or mid
        if len(label) > 14:
            label = label[:12] + ".."
        inp, out, crd, cwr = p["input"], p["output"], p["cache_read"], p["cache_write"]
        print(f"  {row(label, f'${inp}', f'${out}', f'${crd}', f'${cwr}', colors=[117, 183, 209, 72, 136])}")

    print(f"  {bar('└', '┴', '┘')}")
    print()


def print_rates_footer(model_ids: set[str]):
    _ensure_pricing()
    if not MODEL_PRICING:
        print(f"  {dim('⚠ No pricing data. Restart Claude Code or run --update-pricing.')}")
        return
    seen_labels = []
    for mid in sorted(model_ids, key=lambda m: get_pricing(m).get("output", 0), reverse=True):
        p = get_pricing(mid)
        if p is _NO_PRICING:
            continue
        label = model_label(mid)
        if label in seen_labels:
            continue
        seen_labels.append(label)
    if not seen_labels:
        return
    print(f"  {dim('Rates ($/MTok):')}")
    for label in seen_labels:
        mid = next(m for m in model_ids if model_label(m) == label)
        p = get_pricing(mid)
        inp, out, crd, cwr = p["input"], p["output"], p["cache_read"], p["cache_write"]
        print(f"    {dim(f'{label:14s}  in=${inp:<6}  out=${out:<6}  crd=${crd:<6}  cwr={cwr}')}")
    updated = _PRICING_UPDATED[:10] if _PRICING_UPDATED else "unknown"
    print(f"  {dim(f'Updated: {updated}')}")


def _auto_update_pricing():
    try:
        models = _fetch_pricing()
        PRICING_FILE.parent.mkdir(parents=True, exist_ok=True)
        PRICING_FILE.write_text(json.dumps({
            "updated": datetime.now(timezone.utc).isoformat(),
            "source": PRICING_URL,
            "models": models,
        }, indent=2))
    except Exception:
        pass


def _load_pricing() -> tuple[dict, str]:
    if not PRICING_FILE.exists():
        return {}, ""
    try:
        data = json.loads(PRICING_FILE.read_text())
        return data["models"], data.get("updated", "unknown")
    except (json.JSONDecodeError, KeyError, ValueError):
        return {}, ""


MODEL_PRICING, _PRICING_UPDATED = None, None

PROJECTS_DIR = Path.home() / ".claude/projects"

# ── ANSI helpers ──────────────────────────────────────────────────────

def c(code: int, text: str) -> str:
    return f"\033[38;5;{code}m{text}\033[0m"

def bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"

def dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"

# ── Helpers ───────────────────────────────────────────────────────────

def derive_project_name(cwd: str) -> str:
    parts = Path(cwd).parts
    for i, part in enumerate(parts):
        if part == '.claude' and i > 0 and i + 2 < len(parts) and parts[i + 1] == 'worktrees':
            return parts[i - 1]
    return Path(cwd).name


def resolve_date(date_str: str) -> str:
    if date_str == "today":
        return datetime.now().strftime("%Y-%m-%d")
    if date_str == "yesterday":
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return date_str


def _ensure_pricing():
    global MODEL_PRICING, _PRICING_UPDATED
    if MODEL_PRICING is None:
        MODEL_PRICING, _PRICING_UPDATED = _load_pricing()


_NO_PRICING = {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0, "label": None}


def get_pricing(model: str) -> dict:
    _ensure_pricing()
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    for key, pricing in MODEL_PRICING.items():
        if model.startswith(key.rsplit("-", 1)[0]):
            return pricing
    return _NO_PRICING


def model_label(model: str) -> str:
    return get_pricing(model).get("label") or model


def _has_pricing() -> bool:
    _ensure_pricing()
    return bool(MODEL_PRICING)


def _empty_bucket() -> dict:
    return {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0}


_DISCOUNT = 0.13


def cost_for_model(d: dict, model: str) -> float | None:
    p = get_pricing(model)
    if p is _NO_PRICING:
        return None
    raw = (
        d["input"] * p["input"]
        + d["output"] * p["output"]
        + d["cache_read"] * p["cache_read"]
        + d["cache_write"] * p["cache_write"]
    ) / 1_000_000
    return raw * (1 - _DISCOUNT)


def cost_for_buckets(by_model: dict[str, dict]) -> float | None:
    costs = [cost_for_model(d, m) for m, d in by_model.items()]
    if any(c is None for c in costs):
        return None
    return sum(costs)


def merge_buckets(target: dict, source: dict):
    for k in ("calls", "input", "output", "cache_read", "cache_write"):
        target[k] += source[k]


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def total_tokens(d: dict) -> int:
    return d["input"] + d["output"] + d["cache_read"] + d["cache_write"]


def prompt_tokens(d: dict) -> int:
    return d["input"] + d["cache_read"]


def cost_color(c_val: float | None) -> int:
    if c_val is None: return 245
    if c_val < 1:  return 78
    if c_val < 5:  return 228
    if c_val < 20: return 214
    return 196


def tier_color(tok: int) -> int:
    m = tok / 1_000_000
    if m >= 50: return 196
    if m >= 12: return 214
    if m >= 4:  return 228
    if m >= 1:  return 114
    return 245


def cache_pct(d: dict) -> float:
    p = prompt_tokens(d)
    if p == 0:
        return 0.0
    return (d["cache_read"] / p) * 100


def fmt_cost(v: float | None) -> str:
    if v is None: return "n/a"
    if v < 0.005: return "<$0.01"
    if v < 1:     return f"${v:.2f}"
    return f"${v:.1f}"


def fmt_cost_col(v: float | None) -> str:
    if v is None: return "n/a"
    return f"${v:.2f}"


MODEL_COLORS = {
    "Opus 4.6":   196,
    "Opus 4.5":   196,
    "Sonnet 4.5": 214,
    "Haiku 4.5":  78,
    "Fable 5":    135,
    "Unknown":    245,
}

def model_color(label: str) -> int:
    return MODEL_COLORS.get(label, 245)


# ── Scanners ──────────────────────────────────────────────────────────

def scan_jsonl_files(days: int) -> dict[str, dict[str, dict]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ts = cutoff.timestamp()

    daily: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(_empty_bucket))
    seen: set[str] = set()

    for jsonl in PROJECTS_DIR.rglob("*.jsonl"):
        try:
            stat = jsonl.stat()
        except OSError:
            continue
        if stat.st_mtime < cutoff_ts or stat.st_size > MAX_JSONL_SIZE:
            continue
        with jsonl.open() as f:
            for line in f:
                if '"usage"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                req_id = obj.get("requestId")
                if not req_id or req_id in seen:
                    continue
                msg = obj.get("message") or {}
                usage = msg.get("usage")
                if not usage or "output_tokens" not in usage:
                    continue
                seen.add(req_id)
                ts_str = obj.get("timestamp")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                day = ts.astimezone().strftime("%Y-%m-%d")
                model = msg.get("model", "unknown")
                daily[day][model]["calls"] += 1
                daily[day][model]["input"] += usage.get("input_tokens", 0)
                daily[day][model]["output"] += usage.get("output_tokens", 0)
                daily[day][model]["cache_read"] += usage.get("cache_read_input_tokens", 0)
                daily[day][model]["cache_write"] += usage.get("cache_creation_input_tokens", 0)

    return dict(daily)


def scan_session_data(days: int, date_filter: str = None) -> dict[str, dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ts = cutoff.timestamp()

    sessions: dict[str, dict] = defaultdict(lambda: {
        "project": None, "date": None, "title": None,
        "by_model": defaultdict(_empty_bucket),
    })
    seen: set[str] = set()

    for jsonl in PROJECTS_DIR.rglob("*.jsonl"):
        try:
            stat = jsonl.stat()
        except OSError:
            continue
        if stat.st_mtime < cutoff_ts or stat.st_size > MAX_JSONL_SIZE:
            continue
        parts = jsonl.relative_to(PROJECTS_DIR).parts
        if len(parts) < 2:
            continue
        session_id = parts[1].removesuffix('.jsonl') if parts[1].endswith('.jsonl') else parts[1]

        with jsonl.open() as f:
            for line in f:
                if '"ai-title"' in line:
                    try:
                        obj = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if obj.get("type") == "ai-title" and obj.get("aiTitle"):
                        sessions[session_id]["title"] = obj["aiTitle"]
                    continue
                if '"usage"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                req_id = obj.get("requestId")
                if not req_id or req_id in seen:
                    continue
                msg = obj.get("message") or {}
                usage = msg.get("usage")
                if not usage or "output_tokens" not in usage:
                    continue
                seen.add(req_id)
                ts_str = obj.get("timestamp")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                day = ts.astimezone().strftime("%Y-%m-%d")
                if date_filter and day != date_filter:
                    continue
                s = sessions[session_id]
                s["date"] = s["date"] or day
                model = msg.get("model", "unknown")
                s["by_model"][model]["calls"] += 1
                s["by_model"][model]["input"] += usage.get("input_tokens", 0)
                s["by_model"][model]["output"] += usage.get("output_tokens", 0)
                s["by_model"][model]["cache_read"] += usage.get("cache_read_input_tokens", 0)
                s["by_model"][model]["cache_write"] += usage.get("cache_creation_input_tokens", 0)
                if not s["project"]:
                    cwd = obj.get("cwd")
                    if cwd:
                        s["project"] = derive_project_name(cwd)

    return {k: v for k, v in sessions.items() if v["by_model"]}


def _session_totals(s: dict) -> dict:
    totals = _empty_bucket()
    for d in s["by_model"].values():
        merge_buckets(totals, d)
    return totals


def _session_total_tokens(s: dict) -> int:
    return total_tokens(_session_totals(s))


def _session_cost(s: dict) -> float:
    return cost_for_buckets(s["by_model"])


# ── Table rendering ───────────────────────────────────────────────────

def _table_helpers(widths):
    def bar(left, mid, right, fill="─"):
        return dim(left + mid.join(fill * (w + 2) for w in widths) + right)

    def row(*cells, colors=None, is_bold=False):
        parts = []
        for i, (cell, w) in enumerate(zip(cells, widths)):
            txt = str(cell).rjust(w) if i > 0 else str(cell).ljust(w)
            if colors and colors[i]:
                txt = c(colors[i], txt)
            if is_bold:
                txt = bold(txt)
            parts.append(f" {txt} ")
        return dim("│") + dim("│").join(parts) + dim("│")

    return bar, row


def _print_model_breakdown(by_model: dict[str, dict], indent: str = "    "):
    for model, d in sorted(by_model.items(), key=lambda kv: total_tokens(kv[1]), reverse=True):
        label = model_label(model)
        mc = model_color(label)
        c_val = cost_for_model(d, model)
        tok = total_tokens(d)
        print(f"{indent}{c(mc, f'{label:11s}')}  "
              f"{dim('calls=')}{ d['calls']:<4}  "
              f"{dim('rd=')}{fmt_tokens(d['cache_read']):>6}  "
              f"{dim('wr=')}{fmt_tokens(d['cache_write']):>6}  "
              f"{dim('out=')}{fmt_tokens(d['output']):>6}  "
              f"{dim('tok=')}{fmt_tokens(tok):>6}  "
              f"{dim('cost=')}{c(cost_color(c_val), fmt_cost_col(c_val))}")


def print_sessions(session_data: dict[str, dict], date_str: str):
    W = [30, 14, 12, 9, 9, 8, 9, 9]
    bar, row = _table_helpers(W)

    sorted_sessions = sorted(
        session_data.items(),
        key=lambda kv: _session_total_tokens(kv[1]),
        reverse=True,
    )

    print()
    print(f"  \U0001f52c {bold(c(75, 'Sessions'))}  {dim(f'({date_str})')}")
    print()

    hdr_c = [252] * 8
    print(f"  {bar('┌', '┬', '┐')}")
    print(f"  {row('Session', 'Project', 'Model(s)', 'CacheRd', 'CacheWr', 'LLM', 'Total', 'Cost', colors=hdr_c, is_bold=True)}")
    print(f"  {bar('├', '┼', '┤')}")

    grand_by_model: dict[str, dict] = defaultdict(_empty_bucket)
    total_cost_val = 0.0
    has_unknown_cost = False

    for sid, s in sorted_sessions:
        totals = _session_totals(s)
        c_val = _session_cost(s)
        tok = total_tokens(totals)
        tc = tier_color(tok)
        cc = cost_color(c_val)
        label = s.get("title") or sid[:8]
        if len(label) > 30:
            label = label[:28] + ".."
        project = (s.get("project") or "?")[:14]
        models_used = sorted(s["by_model"].keys(), key=lambda m: total_tokens(s["by_model"][m]), reverse=True)
        model_str = ", ".join(model_label(m) for m in models_used)
        if len(model_str) > 12:
            model_str = model_str[:10] + ".."
        print(f"  {row(label, project, model_str, fmt_tokens(totals['cache_read']), fmt_tokens(totals['cache_write']), fmt_tokens(totals['output']), fmt_tokens(tok), fmt_cost_col(c_val), colors=[117, 183, 75, 72, 136, 209, tc, cc])}")

        if len(s["by_model"]) > 1:
            _print_model_breakdown(s["by_model"], indent="     ")

        for model, d in s["by_model"].items():
            merge_buckets(grand_by_model[model], d)
        if c_val is not None:
            total_cost_val += c_val
        else:
            has_unknown_cost = True

    grand_totals = _empty_bucket()
    for d in grand_by_model.values():
        merge_buckets(grand_totals, d)
    tok_total = total_tokens(grand_totals)
    ttc = tier_color(tok_total)
    final_cost = None if has_unknown_cost else total_cost_val
    tc = cost_color(final_cost)
    print(f"  {bar('├', '┼', '┤')}")
    print(f"  {row(f'Total ({len(sorted_sessions)})', '', '', fmt_tokens(grand_totals['cache_read']), fmt_tokens(grand_totals['cache_write']), fmt_tokens(grand_totals['output']), fmt_tokens(tok_total), fmt_cost_col(final_cost), colors=[255, 0, 0, 72, 136, 209, ttc, tc], is_bold=True)}")
    print(f"  {bar('└', '┴', '┘')}")

    if len(grand_by_model) > 1:
        print()
        print(f"  {dim('Per-model totals:')}")
        _print_model_breakdown(grand_by_model, indent="    ")
    print()
    print_rates_footer(set(grand_by_model.keys()))
    print()


def print_top_projects(session_data: dict[str, dict], days: int):
    daily_projects: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {
        "sessions": 0, "by_model": defaultdict(_empty_bucket),
    }))

    for sid, s in session_data.items():
        day = s.get("date")
        project = s.get("project") or "?"
        if not day:
            continue
        dp = daily_projects[day][project]
        dp["sessions"] += 1
        for model, d in s["by_model"].items():
            merge_buckets(dp["by_model"][model], d)

    W = [18, 5, 12, 9, 9, 8, 9, 9]
    bar, row = _table_helpers(W)
    all_model_ids: set[str] = set()

    print()
    print(f"  \U0001f52c {bold(c(75, 'Top Projects by Day'))}  {dim(f'(last {days} days)')}")

    for day in sorted(daily_projects, reverse=True):
        projects = daily_projects[day]
        top5 = sorted(projects.items(), key=lambda kv: sum(total_tokens(d) for d in kv[1]["by_model"].values()), reverse=True)[:5]

        print()
        print(f"  {bold(c(117, f'── {day} ──'))}")
        print(f"  {bar('┌', '┬', '┐')}")

        hdr_c = [252] * 8
        print(f"  {row('Project', '#Ses', 'Model(s)', 'CacheRd', 'CacheWr', 'LLM', 'Total', 'Cost', colors=hdr_c, is_bold=True)}")
        print(f"  {bar('├', '┼', '┤')}")

        for project, pd in top5:
            totals = _empty_bucket()
            for d in pd["by_model"].values():
                merge_buckets(totals, d)
            c_val = cost_for_buckets(pd["by_model"])
            tok = total_tokens(totals)
            tc = tier_color(tok)
            cc = cost_color(c_val)
            plabel = project[:18]
            models_used = sorted(pd["by_model"].keys(), key=lambda m: total_tokens(pd["by_model"][m]), reverse=True)
            all_model_ids.update(models_used)
            model_str = ", ".join(model_label(m) for m in models_used)
            if len(model_str) > 12:
                model_str = model_str[:10] + ".."
            print(f"  {row(plabel, pd['sessions'], model_str, fmt_tokens(totals['cache_read']), fmt_tokens(totals['cache_write']), fmt_tokens(totals['output']), fmt_tokens(tok), fmt_cost_col(c_val), colors=[117, 183, 75, 72, 136, 209, tc, cc])}")

            if len(pd["by_model"]) > 1:
                _print_model_breakdown(pd["by_model"], indent="     ")

        print(f"  {bar('└', '┴', '┘')}")
    print()
    print_rates_footer(all_model_ids)
    print()


def print_projects_summary(session_data: dict[str, dict], days: int):
    projects: dict[str, dict] = defaultdict(lambda: {
        "sessions": 0, "by_model": defaultdict(_empty_bucket),
    })

    for sid, s in session_data.items():
        project = s.get("project") or "?"
        p = projects[project]
        p["sessions"] += 1
        for model, d in s["by_model"].items():
            merge_buckets(p["by_model"][model], d)

    sorted_projects = sorted(
        projects.items(),
        key=lambda kv: sum(total_tokens(d) for d in kv[1]["by_model"].values()),
        reverse=True,
    )

    W = [20, 5, 12, 9, 9, 8, 9, 9]
    bar, row = _table_helpers(W)

    print()
    print(f"  \U0001f52c {bold(c(75, 'Projects Summary'))}  {dim(f'(last {days} days)')}")
    print()

    hdr_c = [252] * 8
    print(f"  {bar('┌', '┬', '┐')}")
    print(f"  {row('Project', '#Ses', 'Model(s)', 'CacheRd', 'CacheWr', 'LLM', 'Total', 'Cost', colors=hdr_c, is_bold=True)}")
    print(f"  {bar('├', '┼', '┤')}")

    grand_by_model: dict[str, dict] = defaultdict(_empty_bucket)
    total_sessions = 0
    total_cost_val = 0.0
    has_unknown_cost = False

    for project, pd in sorted_projects:
        totals = _empty_bucket()
        for d in pd["by_model"].values():
            merge_buckets(totals, d)
        c_val = cost_for_buckets(pd["by_model"])
        tok = total_tokens(totals)
        tc = tier_color(tok)
        cc = cost_color(c_val)
        plabel = project[:20]
        models_used = sorted(pd["by_model"].keys(), key=lambda m: total_tokens(pd["by_model"][m]), reverse=True)
        model_str = ", ".join(model_label(m) for m in models_used)
        if len(model_str) > 12:
            model_str = model_str[:10] + ".."
        print(f"  {row(plabel, pd['sessions'], model_str, fmt_tokens(totals['cache_read']), fmt_tokens(totals['cache_write']), fmt_tokens(totals['output']), fmt_tokens(tok), fmt_cost_col(c_val), colors=[117, 183, 75, 72, 136, 209, tc, cc])}")

        if len(pd["by_model"]) > 1:
            _print_model_breakdown(pd["by_model"], indent="     ")

        for model, d in pd["by_model"].items():
            merge_buckets(grand_by_model[model], d)
        total_sessions += pd["sessions"]
        if c_val is not None:
            total_cost_val += c_val
        else:
            has_unknown_cost = True

    grand_totals = _empty_bucket()
    for d in grand_by_model.values():
        merge_buckets(grand_totals, d)
    tok_total = total_tokens(grand_totals)
    ttc = tier_color(tok_total)
    final_cost = None if has_unknown_cost else total_cost_val
    tc = cost_color(final_cost)
    print(f"  {bar('├', '┼', '┤')}")
    print(f"  {row(f'Total ({len(sorted_projects)})', total_sessions, '', fmt_tokens(grand_totals['cache_read']), fmt_tokens(grand_totals['cache_write']), fmt_tokens(grand_totals['output']), fmt_tokens(tok_total), fmt_cost_col(final_cost), colors=[255, 183, 0, 72, 136, 209, ttc, tc], is_bold=True)}")
    print(f"  {bar('└', '┴', '┘')}")

    if len(grand_by_model) > 1:
        print()
        print(f"  {dim('Per-model totals:')}")
        _print_model_breakdown(grand_by_model, indent="    ")
    print()
    print_rates_footer(set(grand_by_model.keys()))
    print()


def print_daily(daily: dict[str, dict[str, dict]], days: int):
    W = [12, 6, 12, 9, 9, 8, 6, 8, 9]
    bar, row = _table_helpers(W)

    print()
    print(f"  \U0001f52c {bold(c(75, 'Claude Code Token Usage'))}  {dim(f'(last {days} days)')}")
    print()

    hdr_c = [252] * 9
    print(f"  {bar('┌', '┬', '┐')}")
    print(f"  {row('Date', 'Calls', 'Model(s)', 'CacheRd', 'CacheWr', 'LLM', 'Hit%', 'Total', 'Cost', colors=hdr_c, is_bold=True)}")
    print(f"  {bar('├', '┼', '┤')}")

    grand_by_model: dict[str, dict] = defaultdict(_empty_bucket)
    total_cost_val = 0.0
    has_unknown_cost = False
    total_tok = 0

    for day in sorted(daily):
        by_model = daily[day]
        day_totals = _empty_bucket()
        for d in by_model.values():
            merge_buckets(day_totals, d)
        c_val = cost_for_buckets(by_model)
        cc = cost_color(c_val)
        tok = total_tokens(day_totals)
        tc_col = tier_color(tok)
        cp = cache_pct(day_totals)
        cp_c = 78 if cp >= 80 else (228 if cp >= 50 else 196)
        models_used = sorted(by_model.keys(), key=lambda m: total_tokens(by_model[m]), reverse=True)
        model_str = ", ".join(model_label(m) for m in models_used)
        if len(model_str) > 12:
            model_str = model_str[:10] + ".."
        print(f"  {row(day, day_totals['calls'], model_str, fmt_tokens(day_totals['cache_read']), fmt_tokens(day_totals['cache_write']), fmt_tokens(day_totals['output']), f'{cp:.0f}%', fmt_tokens(tok), fmt_cost_col(c_val), colors=[117, 183, 75, 72, 136, 209, cp_c, tc_col, cc])}")

        if len(by_model) > 1:
            _print_model_breakdown(by_model, indent="     ")

        for model, d in by_model.items():
            merge_buckets(grand_by_model[model], d)
        if c_val is not None:
            total_cost_val += c_val
        else:
            has_unknown_cost = True
        total_tok += tok

    grand_totals = _empty_bucket()
    for d in grand_by_model.values():
        merge_buckets(grand_totals, d)
    final_cost = None if has_unknown_cost else total_cost_val
    tc = cost_color(final_cost)
    cp_total = cache_pct(grand_totals)
    cp_tc = 78 if cp_total >= 80 else (228 if cp_total >= 50 else 196)
    ttc = tier_color(total_tok)
    print(f"  {bar('├', '┼', '┤')}")
    print(f"  {row('Total', grand_totals['calls'], '', fmt_tokens(grand_totals['cache_read']), fmt_tokens(grand_totals['cache_write']), fmt_tokens(grand_totals['output']), f'{cp_total:.0f}%', fmt_tokens(total_tok), fmt_cost_col(final_cost), colors=[255, 183, 0, 72, 136, 209, cp_tc, ttc, tc], is_bold=True)}")
    print(f"  {bar('└', '┴', '┘')}")

    print()
    print(f"  {dim('Per-model totals:')}")
    _print_model_breakdown(grand_by_model, indent="    ")
    print()
    print_rates_footer(set(grand_by_model.keys()))
    print()


def print_markdown(daily: dict[str, dict[str, dict]], days: int) -> str:
    lines = []
    lines.append(f"## Token Usage (last {days} days)")
    lines.append("")
    lines.append("| Date | Calls | Model(s) | CacheRd | CacheWr | LLM | Hit% | Total | Cost |")
    lines.append("|------|-------|----------|---------|---------|-----|------|-------|------|")

    grand_by_model: dict[str, dict] = defaultdict(_empty_bucket)
    total_cost_val = 0.0
    has_unknown_cost = False
    total_tok = 0

    for day in sorted(daily):
        by_model = daily[day]
        day_totals = _empty_bucket()
        for d in by_model.values():
            merge_buckets(day_totals, d)
        c_val = cost_for_buckets(by_model)
        tok = total_tokens(day_totals)
        cp = cache_pct(day_totals)
        models_used = sorted(by_model.keys(), key=lambda m: total_tokens(by_model[m]), reverse=True)
        model_str = ", ".join(model_label(m) for m in models_used)
        cost_str = f"${c_val:.2f}" if c_val is not None else "n/a"
        lines.append(f"| {day} | {day_totals['calls']} | {model_str} | {fmt_tokens(day_totals['cache_read'])} "
                     f"| {fmt_tokens(day_totals['cache_write'])} | {fmt_tokens(day_totals['output'])} | {cp:.0f}% "
                     f"| {fmt_tokens(tok)} | {cost_str} |")
        for model, d in by_model.items():
            merge_buckets(grand_by_model[model], d)
        if c_val is not None:
            total_cost_val += c_val
        else:
            has_unknown_cost = True
        total_tok += tok

    grand_totals = _empty_bucket()
    for d in grand_by_model.values():
        merge_buckets(grand_totals, d)
    cp_total = cache_pct(grand_totals)
    final_cost = None if has_unknown_cost else total_cost_val
    total_cost_str = f"${final_cost:.2f}" if final_cost is not None else "n/a"
    lines.append(f"| **Total** | **{grand_totals['calls']}** | | **{fmt_tokens(grand_totals['cache_read'])}** "
                 f"| **{fmt_tokens(grand_totals['cache_write'])}** | **{fmt_tokens(grand_totals['output'])}** | **{cp_total:.0f}%** "
                 f"| **{fmt_tokens(total_tok)}** | **{total_cost_str}** |")
    lines.append("")
    lines.append("### Per-model breakdown")
    lines.append("")
    lines.append("| Model | Calls | CacheRd | CacheWr | LLM | Total | Cost |")
    lines.append("|-------|-------|---------|---------|-----|-------|------|")
    for model in sorted(grand_by_model, key=lambda m: total_tokens(grand_by_model[m]), reverse=True):
        d = grand_by_model[model]
        label = model_label(model)
        c_val = cost_for_model(d, model)
        tok = total_tokens(d)
        cost_str = f"${c_val:.2f}" if c_val is not None else "n/a"
        lines.append(f"| {label} | {d['calls']} | {fmt_tokens(d['cache_read'])} "
                     f"| {fmt_tokens(d['cache_write'])} | {fmt_tokens(d['output'])} "
                     f"| {fmt_tokens(tok)} | {cost_str} |")

    output = "\n".join(lines)
    print(output)
    return output


def copy_to_clipboard(text: str):
    system = platform.system()
    if system == "Darwin":
        cmd = ["pbcopy"]
    elif system == "Linux" and shutil.which("xclip"):
        cmd = ["xclip", "-selection", "clipboard"]
    elif system == "Linux" and shutil.which("xsel"):
        cmd = ["xsel", "--clipboard", "--input"]
    elif system == "Windows":
        cmd = ["clip"]
    else:
        print("No clipboard command found (pbcopy/xclip/xsel/clip).", file=sys.stderr)
        return
    try:
        subprocess.run(cmd, input=text.encode(), check=True, timeout=5)
        print(dim("  \U0001f4cb Copied to clipboard"))
    except subprocess.TimeoutExpired:
        print("Clipboard command timed out.", file=sys.stderr)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Clipboard copy failed: {e}", file=sys.stderr)


# ── Stop hook ────────────────────────────────────────────────────────

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")


def _find_session_jsonl(session_id: str, cwd: str = "") -> Path | None:
    if not _SAFE_ID.match(session_id):
        return None
    if cwd:
        project_dir = cwd.replace("/", "-")
        candidate = PROJECTS_DIR / project_dir / f"{session_id}.jsonl"
        if candidate.exists() and not candidate.is_symlink():
            return candidate
    for f in PROJECTS_DIR.rglob(f"{session_id}.jsonl"):
        if not f.is_symlink():
            return f
    return None


def _new_model_bucket():
    return {**_empty_bucket(), "speeds": defaultdict(int), "efforts": defaultdict(int)}


def _accumulate(bucket: dict, usage: dict, speed: str = "", effort: str = ""):
    bucket["calls"] += 1
    bucket["input"] += usage.get("input_tokens", 0)
    bucket["output"] += usage.get("output_tokens", 0)
    bucket["cache_read"] += usage.get("cache_read_input_tokens", 0)
    bucket["cache_write"] += usage.get("cache_creation_input_tokens", 0)
    if speed:
        bucket["speeds"][speed] += 1
    if effort:
        bucket["efforts"][effort] += 1


def _scan_session_usage(jsonl_path: Path) -> tuple[dict, dict, dict, dict]:
    """Returns (by_model, by_agent, last_by_model, last_agents).

    by_model / by_agent: cumulative session totals.
    last_by_model / last_agents: totals for the latest prompt only,
    identified via promptId boundaries in the JSONL.
    by_agent / last_agents count subagent *files* (invocations), not API calls.
    """
    seen: set[str] = set()
    by_model: dict[str, dict] = defaultdict(_new_model_bucket)
    last_by_model: dict[str, dict] = defaultdict(_new_model_bucket)
    by_agent: dict[str, int] = defaultdict(int)
    last_agents: dict[str, int] = defaultdict(int)

    subagent_files: list[Path] = []
    subagents_dir = jsonl_path.parent / jsonl_path.stem / "subagents"
    if subagents_dir.is_dir():
        subagent_files = list(subagents_dir.rglob("agent-*.jsonl"))

    latest_prompt_id = None
    _SYSTEM_PREFIXES = ("<system-reminder", "<task-notification", "<command-message")
    system_pids: set[str] = set()

    # ── main session file ──
    try:
        fh = jsonl_path.open()
    except OSError:
        return {}, {}, {}, {}
    with fh:
        for line in fh:
            if '"usage"' not in line and '"promptId"' not in line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            pid = obj.get("promptId")
            if pid and pid != latest_prompt_id and pid not in system_pids:
                msg_content = (obj.get("message") or {}).get("content", "")
                if isinstance(msg_content, list):
                    msg_content = (msg_content[0].get("text", "")
                                   if msg_content and isinstance(msg_content[0], dict) else "")
                if isinstance(msg_content, str) and any(
                    msg_content.lstrip().startswith(p) for p in _SYSTEM_PREFIXES
                ):
                    system_pids.add(pid)
                else:
                    latest_prompt_id = pid
                    last_by_model = defaultdict(_new_model_bucket)
            req_id = obj.get("requestId")
            if not req_id or req_id in seen:
                continue
            msg = obj.get("message") or {}
            usage = msg.get("usage")
            if not usage or "output_tokens" not in usage:
                continue
            seen.add(req_id)
            model = msg.get("model", "unknown")
            speed = usage.get("speed", "")
            effort = obj.get("effort", "")
            for bucket in (by_model[model], last_by_model[model]):
                _accumulate(bucket, usage, speed, effort)

    # ── subagent files ──
    for sf in subagent_files:
        agent_type = ""
        file_prompt_ids: set[str] = set()
        file_usage: dict[str, dict] = defaultdict(_new_model_bucket)

        try:
            sfh = sf.open()
        except OSError:
            continue
        with sfh:
            for line in sfh:
                if '"usage"' not in line and '"promptId"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                pid = obj.get("promptId")
                if pid:
                    file_prompt_ids.add(pid)
                req_id = obj.get("requestId")
                if not req_id or req_id in seen:
                    continue
                msg = obj.get("message") or {}
                usage = msg.get("usage")
                if not usage or "output_tokens" not in usage:
                    continue
                seen.add(req_id)
                if not agent_type:
                    agent_type = obj.get("attributionAgent", "")
                model = msg.get("model", "unknown")
                speed = usage.get("speed", "")
                effort = obj.get("effort", "")
                for bucket in (by_model[model], file_usage[model]):
                    _accumulate(bucket, usage, speed, effort)

        is_current = (not latest_prompt_id) or (latest_prompt_id in file_prompt_ids)
        if agent_type:
            by_agent[agent_type] += 1
            if is_current:
                last_agents[agent_type] += 1
        if is_current:
            for model, fu in file_usage.items():
                lm = last_by_model[model]
                merge_buckets(lm, fu)
                for s, cnt in fu["speeds"].items():
                    lm["speeds"][s] += cnt
                for e, cnt in fu["efforts"].items():
                    lm["efforts"][e] += cnt

    return dict(by_model), dict(by_agent), dict(last_by_model), dict(last_agents)


def _safe_state_path(session_id: str) -> Path | None:
    if not _SAFE_ID.match(session_id):
        return None
    path = Path(tempfile.gettempdir()) / f"claude-cost-{session_id}"
    if path.is_symlink():
        return None
    return path


def _write_state(path: Path, data: str):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data.encode())
    finally:
        os.close(fd)


def _dominant(counts: dict) -> str:
    return max(counts, key=counts.get) if counts else ""


def run_session_start():
    _auto_update_pricing()


def run_hook():
    _ensure_pricing()
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    session_id = hook_input.get("session_id", "")
    if not session_id:
        sys.exit(0)

    jsonl_path = _find_session_jsonl(session_id, hook_input.get("cwd", ""))
    if not jsonl_path:
        sys.exit(0)

    by_model, by_agent, last_by_model, last_agents = _scan_session_usage(jsonl_path)
    if not by_model:
        sys.exit(0)

    state_file = _safe_state_path(session_id)
    if not state_file:
        sys.exit(0)

    def _build_display(raw: dict) -> dict:
        out = {}
        for m, d in raw.items():
            if d["calls"] <= 0:
                continue
            label = model_label(m)
            out[label] = {
                "cost": cost_for_model(d, m), "tokens": total_tokens(d),
                "calls": d["calls"], "speed": _dominant(d.get("speeds", {})),
                "effort": _dominant(d.get("efforts", {})),
            }
        return out

    session_models = _build_display(by_model)
    turn_models = _build_display(last_by_model)

    session_cost = sum(m["cost"] for m in session_models.values())
    session_tok = sum(m["tokens"] for m in session_models.values())
    turn_cost = sum(m["cost"] for m in turn_models.values())
    turn_tok = sum(m["tokens"] for m in turn_models.values())

    _write_state(state_file, json.dumps({
        "cost": session_cost, "tokens": session_tok,
        "last_cost": turn_cost, "last_tok": turn_tok,
        "by_model": session_models,
        "last_by_model": turn_models,
        "agents": dict(by_agent),
        "last_agents": dict(last_agents),
    }))


def run_status_line():
    try:
        ctx = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    session_id = ctx.get("session_id", "")
    if not session_id:
        sys.exit(0)

    state_file = _safe_state_path(session_id)
    if not state_file:
        print("$0.00")
        return
    try:
        state = json.loads(state_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        print("$0.00")
        return

    def _fmt_model_line(models: dict, prefix: str, agents: dict | None = None) -> str:
        total_cost = sum(m.get("cost", 0) for m in models.values())
        parts = []
        for label in sorted(models, key=lambda m: models[m].get("tokens", 0), reverse=True):
            mc = models[label]
            tags = [t for t in [mc.get("speed", ""), mc.get("effort", "")] if t]
            tag_str = f" [{','.join(tags)}]" if tags else ""
            parts.append(f"{label}: {fmt_cost(mc['cost'])} ({fmt_tokens(mc['tokens'])}){tag_str}")
        if agents:
            agent_parts = []
            for atype in sorted(agents, key=lambda a: agents[a], reverse=True):
                count = agents[atype]
                agent_parts.append(f"{atype}×{count}")
            if agent_parts:
                parts.append(f"agents: {', '.join(agent_parts)}")
        return f"{prefix}: {' | '.join(parts)}" if parts else f"{prefix}: {fmt_cost(total_cost)}"

    last_by_model = state.get("last_by_model", {})
    by_model = state.get("by_model", {})
    last_agents = state.get("last_agents", {})
    session_agents = state.get("agents", {})

    print(_fmt_model_line(last_by_model, "Prompt", last_agents) if last_by_model else f"Prompt: {fmt_cost(state.get('last_cost', 0))}")
    print(_fmt_model_line(by_model, "Session", session_agents))


# ── Main ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Claude Code token usage (local JSONL files)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s              Daily summary (last 7 days)
  %(prog)s 30           Daily summary (last 30 days)
  %(prog)s --sessions today
  %(prog)s --sessions 2026-07-27
  %(prog)s --top-projects
  %(prog)s --projects 30
  %(prog)s --markdown --copy
""",
    )
    parser.add_argument("days", nargs="?", type=int, default=7, help="Number of days (default: 7)")
    parser.add_argument("--sessions", metavar="DATE",
        help="Show all sessions for DATE (YYYY-MM-DD, 'today', or 'yesterday')")
    parser.add_argument("--top-projects", action="store_true",
        help="Show top 5 projects per day")
    parser.add_argument("--projects", action="store_true",
        help="Show aggregated tokens per project")
    parser.add_argument("--hook", action="store_true",
        help="Run as Claude Code Stop hook (reads stdin, outputs JSON)")
    parser.add_argument("--status-line", action="store_true",
        help="Run as Claude Code status line (reads stdin, outputs cost)")
    parser.add_argument("--session-start", action="store_true",
        help="Run as Claude Code SessionStart hook (fetches latest pricing)")
    parser.add_argument("--rates", action="store_true",
        help="Show current model pricing rates")
    parser.add_argument("--update-pricing", action="store_true",
        help="Force-refresh model pricing from Anthropic")
    parser.add_argument("--markdown", action="store_true", help="Output as markdown table")
    parser.add_argument("--copy", action="store_true", help="Copy output to clipboard")
    args = parser.parse_args()

    if args.session_start:
        run_session_start()
        sys.exit(0)

    if args.rates:
        print_rates()
        sys.exit(0)

    if args.update_pricing:
        update_pricing()
        sys.exit(0)

    if args.days <= 0:
        print("Error: days must be a positive integer.", file=sys.stderr)
        sys.exit(1)

    if args.hook:
        run_hook()
        sys.exit(0)

    if args.status_line:
        run_status_line()
        sys.exit(0)

    if args.sessions:
        date_str = resolve_date(args.sessions)
        session_data = scan_session_data(args.days, date_filter=date_str)
        if not session_data:
            print(f"No sessions found for {date_str}.")
            sys.exit(0)
        print_sessions(session_data, date_str)
    elif args.top_projects:
        session_data = scan_session_data(args.days)
        if not session_data:
            print(f"No data found for the last {args.days} days.")
            sys.exit(0)
        print_top_projects(session_data, args.days)
    elif args.projects:
        session_data = scan_session_data(args.days)
        if not session_data:
            print(f"No data found for the last {args.days} days.")
            sys.exit(0)
        print_projects_summary(session_data, args.days)
    else:
        daily = scan_jsonl_files(args.days)
        if not daily:
            print(f"No data found for the last {args.days} days.")
            sys.exit(0)
        if args.markdown:
            output = print_markdown(daily, args.days)
            if args.copy:
                copy_to_clipboard(output)
        else:
            print_daily(daily, args.days)
            if args.copy:
                output = print_markdown(daily, args.days)
                copy_to_clipboard(output)
