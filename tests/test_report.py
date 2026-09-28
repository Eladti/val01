"""Unit tests for the traceability logic in the report plugin."""

from pathlib import Path

import pytest

from val01.report import TestResult as R
from val01.report import parse_test_plan, trace

pytestmark = pytest.mark.unit

PLAN = """
| ID       | Requirement | Method | Targets  |
|----------|-------------|--------|----------|
| REG-001  | ID reads    | read   | sim, hw  |
| ADC-003  | latch       | model  | sim only |
| FI-001   | faults      | inject |
"""


def by_id(rows):
    return {r["id"]: r for r in rows}


def test_parse_plan_targets():
    plan = parse_test_plan(PLAN)
    assert set(plan) == {"REG-001", "ADC-003", "FI-001"}
    assert plan["REG-001"].targets == ("sim", "hw")
    assert plan["ADC-003"].targets == ("sim",)
    assert plan["FI-001"].targets == ("sim",)  # no Targets column → sim


def test_real_test_plan_parses():
    plan = parse_test_plan((Path(__file__).parents[1] / "docs" / "test_plan.md").read_text())
    assert "REG-001" in plan and "FI-005" in plan
    assert "DEF-001" not in plan  # defect record, not a requirement


@pytest.mark.parametrize(
    "outcomes,verdict",
    [
        (["passed", "passed"], "PASS"),
        (["passed", "failed"], "FAIL"),
        (["passed", "error"], "FAIL"),
        (["skipped", "skipped"], "SKIPPED"),
        (["passed", "skipped"], "PASS"),
    ],
)
def test_verdict_aggregation(outcomes, verdict):
    results = [R(f"t{i}", "REG-001", o, 0.0) for i, o in enumerate(outcomes)]
    assert by_id(trace(parse_test_plan(PLAN), results, "sim"))["REG-001"]["verdict"] == verdict


def test_gaps_flagged_both_directions():
    results = [R("t1", "REG-001", "passed", 0.0), R("t2", "XYZ-999", "passed", 0.0)]
    rows = by_id(trace(parse_test_plan(PLAN), results, "sim"))
    assert rows["ADC-003"]["verdict"] == "NOT COVERED"  # plan item without evidence
    assert rows["XYZ-999"]["verdict"] == "ORPHAN"  # evidence without a plan item


def test_sim_only_item_is_na_on_hw():
    rows = by_id(trace(parse_test_plan(PLAN), [], "hw"))
    assert rows["ADC-003"]["verdict"] == "N/A"
    assert rows["REG-001"]["verdict"] == "NOT COVERED"
