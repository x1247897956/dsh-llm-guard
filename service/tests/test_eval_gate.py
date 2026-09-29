"""Gate must reject missing measurements and malformed availability evidence."""
import json

import pytest

from eval.gate import check


@pytest.fixture
def gate_data(tmp_path):
    report = {
        "meta": {"dataset": {"sha256": "a" * 64}},
        "results": {"rules+semantic": {
            "overall": {"recall": 0.8},
            "semantic_stats": {"calls": 10, "failed": 1, "parse_failed": 0, "failure_rate": 0.1},
        }},
    }
    baseline = {"metrics": {"rules+semantic": {"recall": 0.7}},
                "max_semantic_failure_rate": 0.2, "dataset_sha256": "a" * 64}

    def run():
        (tmp_path / "report.json").write_text(json.dumps(report))
        path = tmp_path / "baseline.json"
        path.write_text(json.dumps(baseline))
        return check(tmp_path, path)

    return report, baseline, run


def test_valid_measurement_passes(gate_data):
    assert gate_data[2]() == 0


@pytest.mark.parametrize("stats", [None, {}, {"calls": 0, "failed": 0, "failure_rate": 0},
    {"calls": -1, "failed": 0, "failure_rate": 0},
    {"calls": 10, "failed": 11, "failure_rate": 0},
    {"calls": 10, "failed": 5, "failure_rate": 0},
    {"calls": 10, "failed": 1},
    {"calls": 10, "failed": 1, "failure_rate": float("nan")},
    {"calls": True, "failed": 0, "failure_rate": 0},
])
def test_invalid_semantic_evidence_fails(gate_data, stats):
    report, _, run = gate_data
    report["results"]["rules+semantic"]["semantic_stats"] = stats
    assert run() == 1


def test_parse_failure_is_rejected(gate_data):
    report, _, run = gate_data
    report["results"]["rules+semantic"]["semantic_stats"]["parse_failed"] = 1
    assert run() == 1


def test_dataset_mismatch_fails(gate_data):
    report, _, run = gate_data
    report["meta"]["dataset"]["sha256"] = "b" * 64
    assert run() == 1


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), 1.1, True, "0.8"])
def test_invalid_metric_fails(gate_data, value):
    report, _, run = gate_data
    report["results"]["rules+semantic"]["overall"]["recall"] = value
    assert run() == 1


def test_regression_fails(gate_data):
    report, _, run = gate_data
    report["results"]["rules+semantic"]["overall"]["recall"] = 0.5
    assert run() == 1


def test_empty_baseline_cannot_pass(gate_data):
    _, baseline, run = gate_data
    baseline["metrics"] = {}
    assert run() == 1
