"""Run Checkpoint 12 readiness suites and write a markdown report.

Usage:
  python scripts/run_readiness_report.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs" / "IMPLEMENTATION_READINESS_REPORT.md"
PYTHON = sys.executable

SUITES: list[tuple[str, list[str]]] = [
    (
        "Enterprise evaluations (Checkpoint 12)",
        ["-m", "pytest", "tests/test_enterprise_evals.py", "-q", "--tb=line"],
    ),
    (
        "Unit - replenishment / forecast / auth / approval / human review",
        [
            "-m",
            "pytest",
            "tests/test_replenishment_service.py",
            "tests/test_forecast_service.py",
            "tests/test_auth_service.py",
            "tests/test_approval_service.py",
            "tests/test_human_review_service.py",
            "tests/test_agent_schemas.py",
            "-q",
            "--tb=line",
        ],
    ),
    (
        "Integration - persistence / multiuser / order lifecycle / ERP / health",
        [
            "-m",
            "pytest",
            "tests/test_persistence.py",
            "tests/test_multiuser.py",
            "tests/test_order_lifecycle.py",
            "tests/test_erp_outbox.py",
            "tests/test_health.py",
            "tests/test_business_audit_trail.py",
            "tests/test_recommendation_evidence.py",
            "-q",
            "--tb=line",
        ],
    ),
    (
        "Streamlit AppTests",
        [
            "-m",
            "pytest",
            "tests/test_todays_queue_ui.py",
            "tests/test_follow_up_ui.py",
            "tests/test_policy_guardrails_ui.py",
            "-q",
            "--tb=line",
        ],
    ),
    (
        "Batch workflow tests",
        [
            "-m",
            "pytest",
            "tests/test_batch_run.py",
            "tests/test_run_trigger.py",
            "tests/test_queue_dispositions.py",
            "tests/test_queue_service.py",
            "-q",
            "--tb=line",
        ],
    ),
    (
        "Policy tests",
        [
            "-m",
            "pytest",
            "tests/test_policy_engine.py",
            "tests/test_policy_guardrails_ui.py",
            "-q",
            "--tb=line",
        ],
    ),
    (
        "Agent tests",
        [
            "-m",
            "pytest",
            "tests/test_agent_orchestration_role.py",
            "tests/test_agent_tools.py",
            "tests/test_agent_tool_contracts.py",
            "tests/test_agent_runner.py",
            "tests/test_agent_orchestrator.py",
            "tests/test_follow_up.py",
            "tests/test_follow_up_tools.py",
            "tests/test_follow_up_guardrails.py",
            "tests/test_follow_up_evals.py",
            "tests/test_evals.py",
            "tests/test_quantity_scenario.py",
            "tests/test_delay_scenario.py",
            "-q",
            "--tb=line",
        ],
    ),
    (
        "Full regression suite",
        ["-m", "pytest", "tests", "-q", "--tb=line"],
    ),
]


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        [PYTHON, *cmd],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def _parse_summary(output: str) -> str:
    for line in reversed(output.splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            if "====" in line or "passed" in line:
                return line.strip().strip("=").strip()
    return "no summary line"


def main() -> int:
    results: list[dict] = []
    started = datetime.now(timezone.utc)
    for name, cmd in SUITES:
        code, output = _run(cmd)
        summary = _parse_summary(output)
        results.append(
            {
                "name": name,
                "exit_code": code,
                "summary": summary,
                "passed": code == 0,
                "tail": "\n".join(output.splitlines()[-30:]),
            }
        )
        print(f"[{'PASS' if code == 0 else 'FAIL'}] {name}: {summary}")

    enterprise_code, enterprise_out = _run(
        ["-m", "pytest", "tests/test_enterprise_evals.py", "-q", "--tb=line"]
    )
    enterprise_summary = _parse_summary(enterprise_out)

    all_pass = all(r["passed"] for r in results)
    ended = datetime.now(timezone.utc)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Implementation Readiness Report",
        "",
        f"Generated: {ended.isoformat()}",
        f"Duration: {(ended - started).total_seconds():.1f}s",
        f"Python: `{PYTHON}`",
        "",
        "## Verdict",
        "",
        (
            "**READY FOR DEMO / PILOT** — all readiness suites passed."
            if all_pass
            else "**NOT READY** — one or more readiness suites failed."
        ),
        "",
        "## Checkpoint 12 — Enterprise evaluations",
        "",
        f"- Suite result: `{enterprise_summary}` (exit {enterprise_code})",
        "- Dataset: `tests/evals/enterprise_cases.json` (25 governed-workflow scenarios)",
        "- Runner asserts business outcomes only (quantities, dispositions, policy rules,",
        "  review/approval requirements, ERP behavior, prohibited actions) — not prose similarity.",
        "",
        "### Scenario coverage",
        "",
    ]
    cases_path = ROOT / "tests" / "evals" / "enterprise_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        lines.append(
            f"- `{case['id']}` — {case['scenario']} "
            f"(disposition={case['expected_disposition']}, "
            f"ERP={case['expected_erp_behavior']})"
        )

    lines.extend(
        [
            "",
            "## Suite results",
            "",
            "| Suite | Result | Summary |",
            "| --- | --- | --- |",
        ]
    )
    for row in results:
        mark = "PASS" if row["passed"] else "FAIL"
        lines.append(f"| {row['name']} | {mark} | `{row['summary']}` |")

    lines.extend(["", "## Failure tails (if any)", ""])
    any_fail = False
    for row in results:
        if row["passed"]:
            continue
        any_fail = True
        lines.append(f"### {row['name']}")
        lines.append("```")
        lines.append(row["tail"])
        lines.append("```")
        lines.append("")
    if not any_fail:
        lines.append("_None — all suites green._")
        lines.append("")

    lines.extend(
        [
            "## Readiness checklist",
            "",
            f"- [{'x' if all_pass else ' '}] Unit tests",
            f"- [{'x' if all_pass else ' '}] Integration tests",
            f"- [{'x' if all_pass else ' '}] Streamlit AppTests",
            f"- [{'x' if all_pass else ' '}] Batch workflow tests",
            f"- [{'x' if all_pass else ' '}] Policy tests",
            f"- [{'x' if all_pass else ' '}] Agent tests",
            f"- [{'x' if enterprise_code == 0 else ' '}] Enterprise evaluation dataset (25 scenarios)",
            "",
            "## Notes",
            "",
            "- Deterministic services + Postgres/SQLite are authoritative; chat is not an approval path.",
            "- Audit trail is append-only (Checkpoint 11).",
            "- Shelf-capacity restriction is enforced in `replenishment_service.calculate_replenishment`.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {REPORT_PATH}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
