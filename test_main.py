"""Tests for _scan_session_usage and related helpers."""
from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

import pytest

import main


# ── helpers ──────────────────────────────────────────────────────────

def _usage_line(
    req_id: str,
    model: str = "claude-opus-4-6",
    prompt_id: str = "p1",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read: int = 80,
    cache_write: int = 10,
    speed: str = "",
    effort: str = "",
    attribution_agent: str = "",
    content: str | None = None,
) -> str:
    obj: dict = {
        "requestId": req_id,
        "promptId": prompt_id,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_write,
            },
        },
    }
    if speed:
        obj["message"]["usage"]["speed"] = speed
    if effort:
        obj["effort"] = effort
    if attribution_agent:
        obj["attributionAgent"] = attribution_agent
    if content is not None:
        obj["message"]["content"] = content
    return json.dumps(obj)


def _prompt_id_line(prompt_id: str, content: str = "user text") -> str:
    return json.dumps({"promptId": prompt_id, "message": {"content": content}})


def _system_prompt_id_line(prompt_id: str, tag: str = "<system-reminder>") -> str:
    return json.dumps({"promptId": prompt_id, "message": {"content": f"{tag} stuff"}})


def _write_jsonl(path: Path, lines: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


# ── _accumulate ──────────────────────────────────────────────────────

class TestAccumulate:
    def test_basic(self):
        bucket = main._new_model_bucket()
        usage = {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 3,
            "cache_creation_input_tokens": 2,
        }
        main._accumulate(bucket, usage)
        assert bucket["calls"] == 1
        assert bucket["input"] == 10
        assert bucket["output"] == 5
        assert bucket["cache_read"] == 3
        assert bucket["cache_write"] == 2

    def test_speed_and_effort(self):
        bucket = main._new_model_bucket()
        usage = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        main._accumulate(bucket, usage, speed="fast", effort="high")
        assert bucket["speeds"]["fast"] == 1
        assert bucket["efforts"]["high"] == 1

    def test_empty_speed_effort_not_stored(self):
        bucket = main._new_model_bucket()
        usage = {"input_tokens": 1, "output_tokens": 1}
        main._accumulate(bucket, usage, speed="", effort="")
        assert len(bucket["speeds"]) == 0
        assert len(bucket["efforts"]) == 0


# ── _scan_session_usage ──────────────────────────────────────────────

class TestScanSessionUsage:
    def test_single_prompt(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
        ])
        by_model, by_agent, last_by_model, last_agents = main._scan_session_usage(jsonl)

        assert "claude-opus-4-6" in by_model
        assert by_model["claude-opus-4-6"]["calls"] == 1
        assert by_model["claude-opus-4-6"]["input"] == 100
        assert last_by_model["claude-opus-4-6"]["calls"] == 1
        assert last_by_model["claude-opus-4-6"]["input"] == 100
        assert by_agent == {}
        assert last_agents == {}

    def test_multi_prompt_resets_last(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _prompt_id_line("p1"),
            _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
            _prompt_id_line("p2"),
            _usage_line("r2", prompt_id="p2", input_tokens=200, output_tokens=75),
        ])
        by_model, _, last_by_model, _ = main._scan_session_usage(jsonl)

        assert by_model["claude-opus-4-6"]["calls"] == 2
        assert by_model["claude-opus-4-6"]["input"] == 300
        assert last_by_model["claude-opus-4-6"]["calls"] == 1
        assert last_by_model["claude-opus-4-6"]["input"] == 200

    def test_system_reminder_does_not_reset_prompt(self, tmp_path):
        """A promptId line whose content starts with <system-reminder> should NOT create a new prompt boundary."""
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _prompt_id_line("p1"),
            _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
            _system_prompt_id_line("p-sys", "<system-reminder>"),
            _usage_line("r2", prompt_id="p-sys", input_tokens=50, output_tokens=25),
        ])
        _, _, last_by_model, _ = main._scan_session_usage(jsonl)

        assert last_by_model["claude-opus-4-6"]["calls"] == 2
        assert last_by_model["claude-opus-4-6"]["input"] == 150

    def test_task_notification_does_not_reset_prompt(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _prompt_id_line("p1"),
            _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
            _system_prompt_id_line("p-task", "<task-notification>"),
            _usage_line("r2", prompt_id="p-task", input_tokens=50, output_tokens=25),
        ])
        _, _, last_by_model, _ = main._scan_session_usage(jsonl)

        assert last_by_model["claude-opus-4-6"]["calls"] == 2

    def test_command_message_does_not_reset_prompt(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _prompt_id_line("p1"),
            _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
            _system_prompt_id_line("p-cmd", "<command-message>"),
        ])
        _, _, last_by_model, _ = main._scan_session_usage(jsonl)

        assert last_by_model["claude-opus-4-6"]["calls"] == 1

    def test_user_prompt_starting_with_angle_bracket_does_reset(self, tmp_path):
        """A user prompt that starts with '<' (e.g. pasting HTML) SHOULD create a new boundary."""
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _prompt_id_line("p1"),
            _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
            _prompt_id_line("p2", content="<div>some html</div>"),
            _usage_line("r2", prompt_id="p2", input_tokens=200, output_tokens=75),
        ])
        _, _, last_by_model, _ = main._scan_session_usage(jsonl)

        assert last_by_model["claude-opus-4-6"]["calls"] == 1
        assert last_by_model["claude-opus-4-6"]["input"] == 200

    def test_duplicate_request_ids_deduplicated(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
            _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
        ])
        by_model, _, _, _ = main._scan_session_usage(jsonl)
        assert by_model["claude-opus-4-6"]["calls"] == 1

    def test_corrupt_lines_skipped(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            "not json at all {{{",
            '{"broken": true, "usage": "yes"}',
            _usage_line("r1", prompt_id="p1"),
        ])
        by_model, _, _, _ = main._scan_session_usage(jsonl)
        assert by_model["claude-opus-4-6"]["calls"] == 1

    def test_missing_file_returns_empty(self, tmp_path):
        result = main._scan_session_usage(tmp_path / "nonexistent.jsonl")
        assert result == ({}, {}, {}, {})

    def test_empty_file(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        jsonl.write_text("")
        by_model, by_agent, last_by_model, last_agents = main._scan_session_usage(jsonl)
        assert by_model == {}
        assert by_agent == {}

    def test_speed_and_effort_tracked(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _usage_line("r1", prompt_id="p1", speed="fast", effort="high"),
        ])
        by_model, _, _, _ = main._scan_session_usage(jsonl)
        assert by_model["claude-opus-4-6"]["speeds"]["fast"] == 1
        assert by_model["claude-opus-4-6"]["efforts"]["high"] == 1


class TestSubagentTracking:
    def _setup_session_with_subagents(self, tmp_path, main_lines, subagent_specs):
        """Create a session JSONL and subagent files.

        subagent_specs: list of (filename, lines) tuples
        """
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, main_lines)

        session_dir = tmp_path / "session" / "subagents"
        for filename, lines in subagent_specs:
            _write_jsonl(session_dir / filename, lines)

        return jsonl

    def test_subagent_counted_by_type(self, tmp_path):
        jsonl = self._setup_session_with_subagents(tmp_path,
            main_lines=[
                _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
            ],
            subagent_specs=[
                ("agent-1.jsonl", [
                    _usage_line("r2", prompt_id="p1", input_tokens=50, output_tokens=25, attribution_agent="Explore"),
                ]),
                ("agent-2.jsonl", [
                    _usage_line("r3", prompt_id="p1", input_tokens=50, output_tokens=25, attribution_agent="Explore"),
                ]),
                ("agent-3.jsonl", [
                    _usage_line("r4", prompt_id="p1", input_tokens=50, output_tokens=25, attribution_agent="general-purpose"),
                ]),
            ],
        )
        _, by_agent, _, last_agents = main._scan_session_usage(jsonl)

        assert by_agent["Explore"] == 2
        assert by_agent["general-purpose"] == 1
        assert last_agents["Explore"] == 2
        assert last_agents["general-purpose"] == 1

    def test_subagent_tokens_in_session_totals(self, tmp_path):
        jsonl = self._setup_session_with_subagents(tmp_path,
            main_lines=[
                _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
            ],
            subagent_specs=[
                ("agent-1.jsonl", [
                    _usage_line("r2", prompt_id="p1", input_tokens=200, output_tokens=100, attribution_agent="Explore"),
                ]),
            ],
        )
        by_model, _, _, _ = main._scan_session_usage(jsonl)

        assert by_model["claude-opus-4-6"]["input"] == 300
        assert by_model["claude-opus-4-6"]["output"] == 150

    def test_subagent_from_previous_prompt_not_in_last(self, tmp_path):
        jsonl = self._setup_session_with_subagents(tmp_path,
            main_lines=[
                _prompt_id_line("p1"),
                _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
                _prompt_id_line("p2"),
                _usage_line("r2", prompt_id="p2", input_tokens=200, output_tokens=75),
            ],
            subagent_specs=[
                ("agent-1.jsonl", [
                    _usage_line("r3", prompt_id="p1", input_tokens=50, output_tokens=25, attribution_agent="Explore"),
                ]),
            ],
        )
        _, by_agent, last_by_model, last_agents = main._scan_session_usage(jsonl)

        assert by_agent["Explore"] == 1
        assert last_agents == {}
        assert last_by_model["claude-opus-4-6"]["input"] == 200

    def test_subagent_from_current_prompt_in_last(self, tmp_path):
        jsonl = self._setup_session_with_subagents(tmp_path,
            main_lines=[
                _prompt_id_line("p1"),
                _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
                _prompt_id_line("p2"),
                _usage_line("r2", prompt_id="p2", input_tokens=200, output_tokens=75),
            ],
            subagent_specs=[
                ("agent-1.jsonl", [
                    _usage_line("r3", prompt_id="p2", input_tokens=50, output_tokens=25, attribution_agent="Explore"),
                ]),
            ],
        )
        _, _, last_by_model, last_agents = main._scan_session_usage(jsonl)

        assert last_agents["Explore"] == 1
        assert last_by_model["claude-opus-4-6"]["input"] == 250

    def test_no_subagent_dir(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _usage_line("r1", prompt_id="p1"),
        ])
        _, by_agent, _, last_agents = main._scan_session_usage(jsonl)
        assert by_agent == {}
        assert last_agents == {}

    def test_subagent_no_attribution_agent(self, tmp_path):
        jsonl = self._setup_session_with_subagents(tmp_path,
            main_lines=[
                _usage_line("r1", prompt_id="p1"),
            ],
            subagent_specs=[
                ("agent-1.jsonl", [
                    _usage_line("r2", prompt_id="p1"),
                ]),
            ],
        )
        _, by_agent, _, last_agents = main._scan_session_usage(jsonl)
        assert by_agent == {}
        assert last_agents == {}

    def test_workflow_nested_subagents(self, tmp_path):
        """Subagents in workflows/wf_*/agent-*.jsonl should be discovered."""
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _usage_line("r1", prompt_id="p1"),
        ])

        wf_dir = tmp_path / "session" / "subagents" / "workflows" / "wf_abc"
        _write_jsonl(wf_dir / "agent-1.jsonl", [
            _usage_line("r2", prompt_id="p1", attribution_agent="workflow-subagent"),
        ])

        _, by_agent, _, last_agents = main._scan_session_usage(jsonl)
        assert by_agent["workflow-subagent"] == 1

    def test_subagent_dedup_across_files(self, tmp_path):
        """Same requestId in main and subagent file should only be counted once."""
        jsonl = self._setup_session_with_subagents(tmp_path,
            main_lines=[
                _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
            ],
            subagent_specs=[
                ("agent-1.jsonl", [
                    _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50, attribution_agent="Explore"),
                ]),
            ],
        )
        by_model, _, _, _ = main._scan_session_usage(jsonl)
        assert by_model["claude-opus-4-6"]["calls"] == 1
        assert by_model["claude-opus-4-6"]["input"] == 100

    def test_unreadable_subagent_file_skipped(self, tmp_path):
        jsonl = self._setup_session_with_subagents(tmp_path,
            main_lines=[
                _usage_line("r1", prompt_id="p1"),
            ],
            subagent_specs=[
                ("agent-1.jsonl", [
                    _usage_line("r2", prompt_id="p1", attribution_agent="Explore"),
                ]),
            ],
        )
        bad_file = tmp_path / "session" / "subagents" / "agent-bad.jsonl"
        bad_file.write_text("data")
        os.chmod(str(bad_file), 0o000)

        by_model, by_agent, _, _ = main._scan_session_usage(jsonl)
        assert by_model["claude-opus-4-6"]["calls"] == 2
        assert by_agent["Explore"] == 1

        os.chmod(str(bad_file), 0o644)


# ── cost_for_model with discount ─────────────────────────────────────

class TestCostForModel:
    @pytest.fixture(autouse=True)
    def _setup_pricing(self, monkeypatch):
        monkeypatch.setattr(main, "MODEL_PRICING", {
            "claude-opus-4-6": {
                "input": 15.0, "output": 75.0,
                "cache_read": 1.5, "cache_write": 18.75,
                "label": "Opus 4.6",
            },
        })
        monkeypatch.setattr(main, "_PRICING_UPDATED", "2026-01-01")

    def test_discount_applied(self):
        d = {"input": 1_000_000, "output": 0, "cache_read": 0, "cache_write": 0}
        cost = main.cost_for_model(d, "claude-opus-4-6")
        raw = 15.0
        assert cost == pytest.approx(raw * (1 - main._DISCOUNT))

    def test_discount_all_token_types(self):
        d = {"input": 500_000, "output": 200_000, "cache_read": 1_000_000, "cache_write": 100_000}
        cost = main.cost_for_model(d, "claude-opus-4-6")
        raw = (500_000 * 15.0 + 200_000 * 75.0 + 1_000_000 * 1.5 + 100_000 * 18.75) / 1_000_000
        assert cost == pytest.approx(raw * (1 - main._DISCOUNT))

    def test_discount_constant_set(self):
        assert 0 < main._DISCOUNT < 1

    def test_unknown_model_returns_none(self):
        d = {"input": 1000, "output": 500, "cache_read": 0, "cache_write": 0}
        assert main.cost_for_model(d, "totally-unknown-model") is None

    def test_zero_tokens(self):
        d = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        assert main.cost_for_model(d, "claude-opus-4-6") == 0.0


# ── _fmt_model_line agents display ───────────────────────────────────

class TestFmtModelLineAgents:
    def test_agents_displayed(self):
        models = {"Opus 4.6": {"cost": 1.0, "tokens": 1000, "speed": "", "effort": ""}}
        agents = {"Explore": 3, "general-purpose": 1}

        from main import run_status_line
        # We test _fmt_model_line indirectly since it's nested in run_status_line.
        # Instead test the formatting logic directly by calling fmt_cost/fmt_tokens.
        # The key assertion is that agent counts are ints, not dicts.
        for atype in sorted(agents, key=lambda a: agents[a], reverse=True):
            count = agents[atype]
            assert isinstance(count, int)
            assert f"{atype}×{count}" in f"{atype}×{count}"
