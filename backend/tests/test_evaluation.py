"""Collaborative evaluation endpoints (K1/K4) against a synthetic DB."""
import datetime
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import evaluation
from app.main import get_app
from app.models import (
    Base,
    BusinessTransaction,
    EvaluationCheck,
    EvaluationCriterion,
    EvaluationSubCriterion,
    GridConnectionRequest,
    RequestEvaluationCheck,
    User,
    UserEvaluationInput,
)

BASE = "/api/v1/grid-connection-requests"
T0 = datetime.datetime(2026, 11, 3, 9, 12, 0)
NP, RE, FI, VIEWER = "u-np", "u-re", "u-fi", "u-view"


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "eval.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add_all([
            GridConnectionRequest(ID="r1-old", id_gronos_new=4902, id_gronos_old="Projekt-G02", timestamp=T0),
            GridConnectionRequest(ID="r1-new", id_gronos_new=4902, id_gronos_old="Projekt-G02",
                                  timestamp=T0 + datetime.timedelta(days=1)),
            User(ID=NP, Email="np@example.invalid", Name="J. Hoffmann", Role="netzplanung"),
            User(ID=RE, Email="re@example.invalid", Name="A. Becker", Role="flaechen_recht"),
            User(ID=FI, Email="fi@example.invalid", Name="M. Krüger", Role="finanzen"),
            User(ID=VIEWER, Email="v@example.invalid", Name="L. Weber", Role="viewer"),
            EvaluationCriterion(ID="B", Name="Technik", Weight=0.3, SortOrder=1),
            EvaluationCriterion(ID="D", Name="Hybridisierung", Weight=0.1, SortOrder=2),
        ])
        s.flush()
        s.add_all([
            EvaluationSubCriterion(ID="B3", EvaluationCriterionID="B", Name="Trassierung", ScoringGroup="B3",
                                   ScoringGroupName="Trassierung", MaxScore=2, Question="Trasse?", SortOrder=1),
            EvaluationSubCriterion(ID="D1", EvaluationCriterionID="D", Name="Hybridisierung", ScoringGroup="D1",
                                   ScoringGroupName="Hybridisierung", MaxScore=2, Question=None, SortOrder=2),
        ])
        s.flush()
        s.add_all([
            EvaluationCheck(ID="B3-01", EvaluationSubCriterionID="B3", CheckType="minimum", Points=0, Graded=False, SortOrder=1),
            EvaluationCheck(ID="B3-04", EvaluationSubCriterionID="B3", CheckType="points", Points=2, Graded=False, SortOrder=2),
            EvaluationCheck(ID="D1-01", EvaluationSubCriterionID="D1", CheckType="points", Points=2, Graded=True, SortOrder=3),
        ])
        s.flush()
        # Gold: Flächen & Recht rated B3-04 as fulfilled (processed by BronzeToGold)
        s.add(UserEvaluationInput(ID="in-1", GridConnectionRequestID="r1-old", EvaluationCheckID="B3-04", UserID=RE,
                                  EvaluationVerdict="fulfilled", EvaluationScore=2, Comment=None, Timestamp=T0))
        s.add(BusinessTransaction(ID="bt-1", UserEvaluationInputID="in-1", Timestamp=T0, InputBronzeTimestamp=T0))
        s.flush()
        s.add(RequestEvaluationCheck(ID="g-1", GridConnectionRequestID="r1-old", UserID=RE, EvaluationCheckID="B3-04",
                                     BusinessTransactionID="bt-1", EvaluationVerdict="fulfilled", EvaluationScore=2,
                                     Version=1, Timestamp=T0))
        s.commit()
    engine.dispose()
    return path


@pytest.fixture()
def client(db_path, monkeypatch):
    calls = []
    monkeypatch.setattr("app.api.evaluation.trigger_gold_dag", lambda: calls.append(1) or True)
    c = TestClient(get_app(db_path))
    c.trigger_calls = calls
    return c


def post(client, user, *checks):
    return client.post(f"{BASE}/4902/evaluation-inputs", json={"checks": list(checks)},
                       headers={"X-User-ID": user} if user else {})


def test_framework_and_users(client):
    fw = client.get("/api/v1/evaluation-framework").json()
    assert [c["id"] for c in fw] == ["B", "D"]
    b3 = fw[0]["sub_criteria"][0]
    assert (b3["scoring_group"], b3["max_score"], [k["id"] for k in b3["checks"]]) == ("B3", 2, ["B3-01", "B3-04"])
    users = {u["id"]: u for u in client.get("/api/v1/users").json()}
    assert users[RE]["role_label"] == "Flächen & Recht" and users[RE]["can_evaluate"]
    assert not users[VIEWER]["can_evaluate"]


def test_state_lists_gold_across_silver_states(client):
    body = client.get(f"{BASE}/4902/evaluation").json()
    assert body["grid_connection_request_id"] == "r1-new"                  # newest Silver state
    assert [e["id"] for e in body["evaluators"]] == [NP, RE, FI]             # role order, no viewer
    assert body["checks"] == [{
        "id": "g-1", "user_id": RE, "evaluation_check_id": "B3-04", "verdict": "fulfilled", "score": 2.0,
        "comment": None, "version": 1, "timestamp": "2026-11-03T09:12:00Z", "pending": False,
    }]
    assert client.get(f"{BASE}/999/evaluation").status_code == 404


def test_input_is_visible_immediately_as_pending(client, db_path):
    resp = post(client, RE, {"evaluation_check_id": "B3-04", "verdict": "not_fulfilled",
                             "comment": "Wegerechte liegen nur als Entwurf vor."})
    assert resp.status_code == 201, resp.text
    item = resp.json()["items"][0]
    assert (item["version"], item["score"], item["pending"]) == (2, 0.0, True)
    assert client.trigger_calls == [1]

    state = client.get(f"{BASE}/4902/evaluation").json()
    assert [(c["verdict"], c["version"], c["pending"]) for c in state["checks"]] == [("not_fulfilled", 2, True)]

    con = sqlite3.connect(db_path)
    row = con.execute("SELECT GridConnectionRequestID, EvaluationScore, Comment, Timestamp FROM UserEvaluationInputs "
                      "WHERE ID = ?", (item["id"],)).fetchone()
    assert row[:3] == ("r1-new", 0.0, "Wegerechte liegen nur als Entwurf vor.")
    assert row[3] > "2026-11-03 09:12:00"


def test_history_with_previous_values_and_filters(client):
    post(client, NP, {"evaluation_check_id": "B3-04", "verdict": "fulfilled"})
    post(client, RE, {"evaluation_check_id": "B3-04", "verdict": "not_fulfilled", "comment": "Wegerechte fehlen"})
    post(client, RE, {"evaluation_check_id": "B3-04", "verdict": "not_fulfilled", "comment": "Weiterhin offen"})
    post(client, FI, {"evaluation_check_id": "D1-01", "verdict": "fulfilled", "score": 1})

    hist = client.get(f"{BASE}/4902/evaluation-history").json()
    got = [(i["user_id"], i["evaluation_check_id"], i["action"], i["previous_score"], i["score"]) for i in hist["items"]]
    assert got == [
        (FI, "D1-01", "rated", None, 1.0),
        (RE, "B3-04", "commented", 0.0, 0.0),
        (RE, "B3-04", "changed", 2.0, 0.0),
        (NP, "B3-04", "rated", None, 2.0),
        (RE, "B3-04", "rated", None, 2.0),
    ]
    ratings = client.get(f"{BASE}/4902/evaluation-history?kind=ratings").json()
    assert [i["action"] for i in ratings["items"]] == ["rated", "changed", "rated", "rated"]
    comments = client.get(f"{BASE}/4902/evaluation-history?kind=comments").json()
    assert [i["comment"] for i in comments["items"]] == ["Weiterhin offen", "Wegerechte fehlen"]
    b3 = client.get(f"{BASE}/4902/evaluation-history?scoring_group=B3&user_id={RE}").json()
    assert b3["total"] == 3


def test_several_checks_in_one_input_share_the_timestamp(client):
    resp = post(client, NP, {"evaluation_check_id": "B3-01", "verdict": "fulfilled"},
                {"evaluation_check_id": "B3-04", "verdict": "fulfilled"})
    items = resp.json()["items"]
    assert len(items) == 2 and items[0]["timestamp"] == items[1]["timestamp"]
    assert [i["score"] for i in items] == [0.0, 2.0]                         # minimum → 0, points → 2


def test_input_validation_and_permissions(client):
    ok = {"evaluation_check_id": "B3-04", "verdict": "fulfilled"}
    assert post(client, None, ok).status_code == 401
    assert post(client, "nobody", ok).status_code == 401
    assert post(client, VIEWER, ok).status_code == 403
    assert post(client, NP, {"evaluation_check_id": "XX", "verdict": "fulfilled"}).status_code == 422
    assert post(client, NP, {"evaluation_check_id": "B3-04", "verdict": "maybe"}).status_code == 422
    assert post(client, NP, {"evaluation_check_id": "D1-01", "verdict": "fulfilled"}).status_code == 422
    assert post(client, NP, {"evaluation_check_id": "D1-01", "verdict": "fulfilled", "score": 3}).status_code == 422
    assert client.post(f"{BASE}/4902/evaluation-inputs", json={"checks": []},
                       headers={"X-User-ID": NP}).status_code == 422
    resp = post(client, NP, {"evaluation_check_id": "D1-01", "verdict": "open"})
    assert resp.status_code == 201 and resp.json()["items"][0]["score"] is None


def test_timestamps_strictly_increase(client, db_path):
    for _ in range(5):
        post(client, NP, {"evaluation_check_id": "B3-04", "verdict": "fulfilled"})
    ts = [r[0] for r in sqlite3.connect(db_path).execute("SELECT Timestamp FROM UserEvaluationInputs ORDER BY rowid")]
    assert ts == sorted(ts) and len(set(ts)) == len(ts)


def test_gold_trigger_without_config_is_a_noop(monkeypatch):
    monkeypatch.delenv("AIRFLOW_API_URL", raising=False)
    assert evaluation.trigger_gold_dag() is False


def test_reads_still_use_a_read_only_connection(client, db_path):
    client.get(f"{BASE}/4902/evaluation")
    engine = client.app.state.engine
    with engine.connect() as conn:
        with pytest.raises(Exception, match="readonly"):
            conn.exec_driver_sql("DELETE FROM Users")
