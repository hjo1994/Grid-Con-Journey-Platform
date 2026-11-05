"""Reifegrad rules (app/scoring.py) and the score endpoints."""
import datetime
import json
from pathlib import Path

import pytest

from app import scoring
from tests.test_evaluation import BASE, FI, NP, RE, client, db_path, post  # noqa: F401  (fixtures)

CASES = json.loads((Path(__file__).parent / "scoring_cases.json").read_text())


def framework_of(criteria: list[dict]) -> scoring.Framework:
    subs, groups, checks = [], {}, {}
    for c in criteria:
        for s in c["sub_criteria"]:
            own = [scoring.Check(k["id"], s["id"], k["check_type"], k["points"], k["graded"], k["alternative_group"])
                   for k in s["checks"]]
            checks.update({k.id: k for k in own})
            subs.append(scoring.SubCriterion(s["id"], c["id"], s["scoring_group"], own))
            groups.setdefault(s["scoring_group"], scoring.Group(s["scoring_group"], s["scoring_group"], c["id"], s["max_score"])).checks.extend(own)
    return scoring.Framework({c["id"]: c["weight"] for c in criteria}, subs, list(groups.values()), checks)


FW = framework_of(CASES["framework"])


@pytest.mark.parametrize("case", CASES["cases"], ids=[c["name"] for c in CASES["cases"]])
def test_shared_cases(case):
    values = {k: (v[0], v[1]) for k, v in case["values"].items()}
    results = {g.key: scoring.group_score(g, values) for g in FW.groups}
    assert {k: [r.score, r.status] for k, r in results.items()} == case["groups"]
    assert scoring.overall_score(FW, results) == (case["percent"], case["complete"])


def test_diverging_groups_and_deviating_reviewers():
    def results(**scores):
        return {g.key: scoring.GroupResult(scores.get(g.key.replace("+", "_")), "complete") for g in FW.groups}

    a, b, c = results(B3=2, C1=1), results(B3=2, C1=2), results(B3=1)
    assert scoring.diverging_groups(FW, [a, b, c]) == ["B3", "C1"]
    # B3: 2, 2, 1 → c deviates; C1: 1, 2 (tie) → a and b deviate
    assert scoring.deviates(["B3", "C1"], [a, b, c]) == [True, True, True]
    assert scoring.deviates(["B3"], [a, b, c]) == [False, False, True]
    assert scoring.diverging_groups(FW, [a, results(B3=2, C1=1)]) == []


def test_combined_is_the_mean_of_given_scores():
    assert scoring.combined_percent([55.0, 60.0, None]) == 57.5
    assert scoring.combined_percent([None, None]) is None
    assert scoring.round1(16.65) == 16.7


def test_request_scores_grouped_by_sub_criterion(client):
    # Gold: RE has B3-04 fulfilled (2 points) but B3-01 open → incomplete
    post(client, NP, {"evaluation_check_id": "B3-01", "verdict": "fulfilled"},
         {"evaluation_check_id": "B3-04", "verdict": "fulfilled"},
         {"evaluation_check_id": "D1-01", "verdict": "fulfilled", "score": 1, "comment": "Speicher geplant"})
    body = client.get(f"{BASE}/4902/evaluation-scores").json()
    reviewers = {r["user"]["id"]: r for r in body["reviewers"]}
    assert list(reviewers) == [NP, RE, FI]

    np_ = reviewers[NP]
    b3 = next(s for s in np_["sub_criteria"] if s["sub_criterion_id"] == "B3")
    assert b3["scoring_group"] == "B3" and b3["points"] == 2
    assert [(c["evaluation_check_id"], c["check_type"], c["pending"]) for c in b3["checks"]] == [
        ("B3-01", "minimum", True), ("B3-04", "points", True)]
    d1 = next(s for s in np_["sub_criteria"] if s["sub_criterion_id"] == "D1")
    assert d1["checks"][0]["graded"] and d1["checks"][0]["score"] == 1 and d1["checks"][0]["comment"] == "Speicher geplant"
    assert {g["scoring_group"]: (g["score"], g["status"]) for g in np_["groups"]} == {"B3": (2, "complete"), "D1": (1, "complete")}
    # 0.3 × 2/2 + 0.1 × 1/2 of weight 0.4 in total → 35 %
    assert (np_["percent"], np_["complete"]) == (35.0, True)

    re_ = reviewers[RE]
    assert {g["scoring_group"]: g["status"] for g in re_["groups"]} == {"B3": "incomplete", "D1": "empty"}
    assert (re_["percent"], re_["complete"]) == (30.0, False)
    assert reviewers[FI]["percent"] is None and reviewers[FI]["sub_criteria"][0]["checks"] == []

    combined = body["combined"]
    assert combined == {"percent": 32.5, "method": "mean", "done": 1, "total": 3, "complete": False,
                        "diverging_groups": []}


def test_deviating_reviewer_is_flagged(client):
    post(client, NP, {"evaluation_check_id": "B3-01", "verdict": "fulfilled"},
         {"evaluation_check_id": "B3-04", "verdict": "not_fulfilled"})
    body = client.get(f"{BASE}/4902/evaluation-scores").json()
    assert body["combined"]["diverging_groups"] == ["B3"]            # NP 0, RE 2
    assert [r["deviates"] for r in body["reviewers"]] == [True, True, False]


def test_summaries_for_the_overview(client):
    post(client, NP, {"evaluation_check_id": "B3-01", "verdict": "fulfilled", "comment": "ok"},
         {"evaluation_check_id": "B3-04", "verdict": "fulfilled"})
    body = client.get("/api/v1/evaluation-scores", params=[("ids", 4902), ("ids", 9999), ("ids", 4902)]).json()
    assert body["total"] == 1
    item = body["items"][0]
    assert (item["id_gronos_new"], item["percent"], item["done"], item["total"]) == (4902, 30.0, 0, 3)
    assert item["comment_count"] == 1 and item["diverging_groups"] == []
    assert [(r["short"], r["percent"], r["complete"]) for r in item["reviewers"]] == [
        ("NP", 30.0, False), ("RE", 30.0, False), ("FI", None, False)]
    assert item["reviewers"][0]["last_change"].endswith("Z")


def test_score_endpoints_validate_input(client):
    assert client.get(f"{BASE}/1/evaluation-scores").status_code == 404
    assert client.get("/api/v1/evaluation-scores").status_code == 422
    too_many = [("ids", i) for i in range(501)]
    assert client.get("/api/v1/evaluation-scores", params=too_many).status_code == 422
