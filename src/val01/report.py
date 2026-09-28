"""Test report with test-plan traceability (pytest plugin).

Enabled by `pytest --report` (loaded via `-p val01.report` in pyproject).
Writes into reports/:
  results.json   raw machine-readable results
  report.html    human-readable report: summary, traceability matrix, failures
  summary.md     short markdown, used for the GitHub Actions job summary

The traceability matrix joins docs/test_plan.md (requirements) with the
@pytest.mark.tp IDs on the tests (evidence). It flags gaps in both
directions: a plan item with no test, and a test tagged with an ID that
isn't in the plan.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import platform
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pytest

PLAN_ROW = re.compile(r"^\|\s*([A-Z]+-\d{3})\s*\|(.+)\|\s*$")


# ---------------------------------------------------------------- pure logic
@dataclass
class PlanItem:
    id: str
    requirement: str
    targets: tuple[str, ...]


@dataclass
class TestResult:
    nodeid: str
    tp: str | None
    outcome: str  # passed / failed / skipped / error
    duration: float
    message: str = ""
    properties: dict = field(default_factory=dict)


def parse_test_plan(text: str) -> dict[str, PlanItem]:
    """Extract ID rows from the markdown tables in docs/test_plan.md.

    Main table: | ID | Requirement | Method | Targets |
    FI table:   | ID | Requirement | Method |   (targets default to sim)
    """
    items: dict[str, PlanItem] = {}
    for line in text.splitlines():
        m = PLAN_ROW.match(line.strip())
        if not m:
            continue
        cols = [c.strip() for c in m.group(2).split("|")]
        targets = ("sim",)
        if len(cols) >= 3:
            raw = cols[2].replace("only", "").strip()
            targets = tuple(t.strip() for t in raw.split(",") if t.strip()) or ("sim",)
        items[m.group(1)] = PlanItem(m.group(1), cols[0], targets)
    return items


def trace(plan: dict[str, PlanItem], results: list[TestResult], target: str) -> list[dict]:
    """One row per plan ID (plus orphan IDs), with an aggregated verdict.

    PASS         every executed test for the ID passed (at least one)
    FAIL         any test failed or errored
    SKIPPED      tests exist, but all were skipped
    NOT COVERED  the ID applies to this target but no test carries it
    N/A          the ID does not apply to this target
    ORPHAN       tests carry an ID that is not in the plan
    """
    by_id: dict[str, list[TestResult]] = {}
    for r in results:
        if r.tp:
            by_id.setdefault(r.tp, []).append(r)

    rows = []
    for pid, item in plan.items():
        tests = by_id.get(pid, [])
        applies = target in item.targets or (target == "fw" and "hw" in item.targets)
        rows.append(_row(pid, item.requirement, tests, applies))
    for pid in sorted(set(by_id) - set(plan)):
        row = _row(pid, "(not in test plan)", by_id[pid], True)
        row["verdict"] = "ORPHAN"
        rows.append(row)
    return rows


def _row(pid: str, requirement: str, tests: list[TestResult], applies: bool) -> dict:
    outcomes = [t.outcome for t in tests]
    if not tests:
        verdict = "NOT COVERED" if applies else "N/A"
    elif any(o in ("failed", "error") for o in outcomes):
        verdict = "FAIL"
    elif all(o == "skipped" for o in outcomes):
        verdict = "SKIPPED"
    else:
        verdict = "PASS"
    return {
        "id": pid,
        "requirement": requirement,
        "verdict": verdict,
        "tests": len(tests),
        "passed": outcomes.count("passed"),
        "failed": outcomes.count("failed") + outcomes.count("error"),
        "skipped": outcomes.count("skipped"),
    }


# ------------------------------------------------------------ pytest plugin
def pytest_addoption(parser):
    parser.addoption("--report", action="store_true", help="write reports/ (HTML, JSON, MD)")
    parser.addoption("--report-dir", default="reports", help="report output directory")
    parser.addoption("--strict-trace", action="store_true",
                     help="fail the run on traceability gaps (NOT COVERED, ORPHAN, untraced DUT tests)")


class _Collector:
    def __init__(self, config):
        self.config = config
        self.tp_by_nodeid: dict[str, str | None] = {}
        self.dut_nodeids: set[str] = set()
        self.results: dict[str, TestResult] = {}
        self.started = dt.datetime.now(dt.timezone.utc)

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, items):
        for item in items:
            m = item.get_closest_marker("tp")
            self.tp_by_nodeid[item.nodeid] = m.args[0] if m and m.args else None
            if item.get_closest_marker("dut"):
                self.dut_nodeids.add(item.nodeid)

    def pytest_runtest_logreport(self, report):
        # Keep the first non-passing phase, or the call phase if everything passed
        if report.when == "call" or report.outcome != "passed":
            if report.nodeid in self.results and self.results[report.nodeid].outcome != "passed":
                return
            outcome = report.outcome
            if report.when != "call" and outcome == "failed":
                outcome = "error"
            msg = ""
            if report.failed:
                crash = getattr(report.longrepr, "reprcrash", None)
                msg = crash.message if crash else str(report.longrepr).strip().splitlines()[-1]
                msg = msg.strip().splitlines()[0][:300] if msg.strip() else ""
            elif report.skipped and isinstance(report.longrepr, tuple):
                msg = str(report.longrepr[2])
            self.results[report.nodeid] = TestResult(
                nodeid=report.nodeid,
                tp=self.tp_by_nodeid.get(report.nodeid),
                outcome=outcome,
                duration=round(report.duration, 4),
                message=msg,
                properties=dict(report.user_properties),
            )

    def pytest_sessionfinish(self, session):
        root = Path(self.config.rootpath)
        out = root / self.config.getoption("--report-dir")
        out.mkdir(parents=True, exist_ok=True)

        plan_path = root / "docs" / "test_plan.md"
        plan = parse_test_plan(plan_path.read_text()) if plan_path.exists() else {}
        target = self.config.getoption("--target", default="sim")
        results = list(self.results.values())
        rows = trace(plan, results, target)
        meta = _meta(root, target, self.started)
        counts = {o: sum(r.outcome == o for r in results) for o in ("passed", "failed", "error", "skipped")}
        verdicts = {v: sum(r["verdict"] == v for r in rows) for v in
                    ("PASS", "FAIL", "SKIPPED", "NOT COVERED", "N/A", "ORPHAN")}
        untraced = [r.nodeid for r in results if r.tp is None and r.nodeid in self.dut_nodeids]

        data = {
            "meta": meta, "counts": counts, "verdicts": verdicts, "traceability": rows,
            "untraced_dut_tests": untraced, "results": [asdict(r) for r in results],
        }
        (out / "results.json").write_text(json.dumps(data, indent=2))
        (out / "report.html").write_text(_html(data))
        (out / "summary.md").write_text(_markdown(data))
        self.summary_line = f"VAL01 report: {out / 'report.html'}  verdicts={verdicts}"
        gaps = verdicts["NOT COVERED"] + verdicts["ORPHAN"] + len(untraced)
        if self.config.getoption("--strict-trace") and gaps and session.exitstatus == 0:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
            self.summary_line += f"\nVAL01 strict-trace: {gaps} traceability gap(s) -> run FAILED"

    def pytest_terminal_summary(self, terminalreporter):
        if getattr(self, "summary_line", None):
            terminalreporter.write_line(self.summary_line)


def pytest_configure(config):
    if config.getoption("--report"):
        config.pluginmanager.register(_Collector(config), "val01-report-collector")


# ----------------------------------------------------------------- rendering
def _meta(root: Path, target: str, started) -> dict:
    sha = os.environ.get("GITHUB_SHA", "")[:7]
    if not sha:
        try:
            sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                                 capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            sha = ""
    return {
        "target": target,
        "commit": sha or "unknown",
        "python": platform.python_version(),
        "started_utc": started.strftime("%Y-%m-%d %H:%M:%S"),
    }


VERDICT_ORDER = ["FAIL", "ORPHAN", "NOT COVERED", "SKIPPED", "PASS", "N/A"]


def _overall(data) -> str:
    v, c = data["verdicts"], data["counts"]
    bad = v["FAIL"] or v["ORPHAN"] or v["NOT COVERED"] or c["failed"] or c["error"]
    return "FAIL" if bad else "PASS"


def _markdown(data) -> str:
    m, c, v = data["meta"], data["counts"], data["verdicts"]
    lines = [
        f"## VAL01 — {_overall(data)}",
        f"target `{m['target']}` · commit `{m['commit']}` · Python {m['python']}",
        "",
        f"**Tests:** {c['passed']} passed, {c['failed']} failed, {c['error']} errors, {c['skipped']} skipped",
        "",
        "| Verdict | Plan items |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v[k]} |" for k in VERDICT_ORDER if v[k]]
    problems = [r for r in data["traceability"] if r["verdict"] in ("FAIL", "ORPHAN", "NOT COVERED")]
    if problems:
        lines += ["", "**Needs attention:**", ""]
        lines += [f"- `{r['id']}` {r['verdict']}: {r['requirement']}" for r in problems]
    return "\n".join(lines) + "\n"


def _html(data) -> str:
    e = html.escape
    m, c = data["meta"], data["counts"]
    overall = _overall(data)
    rows = sorted(data["traceability"], key=lambda r: (VERDICT_ORDER.index(r["verdict"]), r["id"]))
    trace_rows = "".join(
        f"<tr><td class=id>{e(r['id'])}</td><td>{e(r['requirement'])}</td>"
        f"<td><span class='v {r['verdict'].replace(' ', '-').replace('/', '')}'>{r['verdict']}</span></td>"
        f"<td class=num>{r['passed']}/{r['tests']}</td></tr>"
        for r in rows
    )
    failures = [r for r in data["results"] if r["outcome"] in ("failed", "error")]
    fail_html = "".join(
        f"<tr><td class=id>{e(r['tp'] or '—')}</td><td><code>{e(r['nodeid'])}</code></td>"
        f"<td><code>{e(r['message'])}</code></td></tr>" for r in failures
    ) or "<tr><td colspan=3 class=muted>None</td></tr>"
    props = [r for r in data["results"] if r["properties"]]
    prop_html = "".join(
        f"<tr><td class=id>{e(r['tp'] or '—')}</td><td>"
        + "".join(f"<div><b>{e(k)}</b>: <code>{e(str(val))}</code></div>" for k, val in r["properties"].items())
        + "</td></tr>" for r in props
    ) or "<tr><td colspan=2 class=muted>None</td></tr>"
    untraced = "".join(f"<li><code>{e(n)}</code></li>" for n in data["untraced_dut_tests"])

    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>VAL01 Test Report</title><style>
:root{{--bg:#fff;--fg:#1a1d21;--muted:#6b7280;--line:#e5e7eb;--card:#f8f9fb;
--pass:#15803d;--fail:#b91c1c;--warn:#b45309;--skip:#6b7280}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111316;--fg:#e8eaed;--muted:#9aa0a6;
--line:#2a2e33;--card:#1a1d21;--pass:#4ade80;--fail:#f87171;--warn:#fbbf24;--skip:#9aa0a6}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px}}
main{{max-width:1000px;margin:auto}} h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 8px}}
.meta{{color:var(--muted)}} .cards{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-width:90px}}
.card b{{display:block;font-size:20px}} table{{width:100%;border-collapse:collapse}}
td,th{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--muted);font-weight:500}} .id{{font-family:ui-monospace,monospace;white-space:nowrap}}
.num{{text-align:right;font-variant-numeric:tabular-nums}} code{{font-size:12px;word-break:break-all}}
.v{{font-weight:600;font-size:12px}} .PASS{{color:var(--pass)}} .FAIL,.ORPHAN{{color:var(--fail)}}
.NOT-COVERED{{color:var(--warn)}} .SKIPPED,.NA,.muted{{color:var(--skip)}}
.overall{{font-size:13px;padding:2px 10px;border-radius:99px;border:1px solid currentColor;margin-left:8px}}
.wrap{{overflow-x:auto}}
</style></head><body><main>
<h1>VAL01 Test Report <span class="overall {overall}">{overall}</span></h1>
<div class=meta>target <b>{e(m['target'])}</b> · commit <code>{e(m['commit'])}</code> · Python {e(m['python'])} · {e(m['started_utc'])} UTC</div>
<div class=cards>
<div class=card><b class=PASS>{c['passed']}</b>passed</div>
<div class=card><b class=FAIL>{c['failed'] + c['error']}</b>failed/error</div>
<div class=card><b class=muted>{c['skipped']}</b>skipped</div>
<div class=card><b>{len(data['traceability'])}</b>plan items</div>
</div>
<h2>Traceability: test plan → evidence</h2>
<div class=wrap><table><tr><th>ID</th><th>Requirement</th><th>Verdict</th><th class=num>Passed/Tests</th></tr>{trace_rows}</table></div>
<h2>Failures</h2>
<div class=wrap><table><tr><th>ID</th><th>Test</th><th>Message</th></tr>{fail_html}</table></div>
<h2>Recorded metrics</h2>
<div class=wrap><table><tr><th>ID</th><th>Properties</th></tr>{prop_html}</table></div>
{"<h2>DUT tests without a test-plan ID</h2><ul>" + untraced + "</ul>" if untraced else ""}
</main></body></html>
"""
