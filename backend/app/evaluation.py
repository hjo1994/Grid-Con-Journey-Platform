"""Collaborative evaluation: read model (Gold + pending Bronze) and the write path.

Gold (RequestEvaluationChecks) is the system of record, filled by the
BronzeToGold DAG from the Bronze table UserEvaluationInputs. Between an
input and the DAG run the input exists only in Bronze. So that every
evaluator sees changes immediately ("live"), the read model merges Gold with
the inputs after the Gold watermark (highest InputBronzeTimestamp of the Gold
BusinessTransactions) and marks those as ``pending``. Once the DAG has run,
the same entry comes from Gold with the same values.

BronzeToGold stores only changes (delta): an input whose verdict and score
equal the newest entry of the same user and check and that carries no new
comment gets no Gold entry. The read model applies the same rule
(``unchanged``) to pending inputs, so they look the same before and after the
DAG run.

A request (``id_gronos_new``) has several Silver states; evaluations belong to
the request, not to one state, so every query goes over all states of the
ticket.
"""
from __future__ import annotations

import json
import logging
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import AIRFLOW_GOLD_DAG_ID, airflow_settings
from app.models import (
    EVALUATOR_ROLES,
    BusinessTransaction,
    EvaluationCheck,
    EvaluationSubCriterion,
    GridConnectionRequest,
    RequestEvaluationCheck,
    User,
    UserEvaluationInput,
)

log = logging.getLogger(__name__)


@dataclass
class Entry:
    """One evaluation of one check by one user (Gold or pending Bronze)."""

    id: str
    user_id: str
    evaluation_check_id: str
    verdict: str
    score: float | None
    comment: str | None
    timestamp: datetime
    version: int
    pending: bool
    previous_verdict: str | None = None
    previous_score: float | None = None


def state_ids(session: Session, id_gronos_new: int) -> list[str]:
    return list(session.scalars(select(GridConnectionRequest.ID).where(GridConnectionRequest.id_gronos_new == id_gronos_new)))


def gold_watermark(session: Session) -> datetime | None:
    return session.scalar(
        select(func.max(BusinessTransaction.InputBronzeTimestamp)).where(
            BusinessTransaction.UserEvaluationInputID.is_not(None)
        )
    )


def entries(session: Session, id_gronos_new: int) -> list[Entry]:
    """All evaluation entries of a request in chronological order, with
    version and previous value per (user, check)."""
    ids = state_ids(session, id_gronos_new)
    if not ids:
        return []
    gold = session.scalars(
        select(RequestEvaluationCheck)
        .where(RequestEvaluationCheck.GridConnectionRequestID.in_(ids))
        .order_by(RequestEvaluationCheck.Timestamp, RequestEvaluationCheck.Version)
    ).all()
    result = [
        Entry(g.ID, g.UserID, g.EvaluationCheckID, g.EvaluationVerdict, g.EvaluationScore,
              g.EvaluationComment, g.Timestamp, g.Version, False)
        for g in gold
    ]
    mark = gold_watermark(session)
    pending_q = select(UserEvaluationInput).where(UserEvaluationInput.GridConnectionRequestID.in_(ids))
    if mark is not None:
        pending_q = pending_q.where(UserEvaluationInput.Timestamp > mark)
    valid_checks = set(session.scalars(select(EvaluationCheck.ID)))
    newest: dict[tuple[str, str], Entry] = {}
    for e in result:
        key = (e.user_id, e.evaluation_check_id)
        if key not in newest or e.version > newest[key].version:
            newest[key] = e
    for i in session.scalars(pending_q.order_by(UserEvaluationInput.Timestamp)).all():
        if i.EvaluationCheckID not in valid_checks:
            continue
        key = (i.UserID, i.EvaluationCheckID)
        prev = newest.get(key)
        if prev is not None and unchanged(prev, i.EvaluationVerdict, i.EvaluationScore, i.Comment):
            continue
        e = Entry(i.ID, i.UserID, i.EvaluationCheckID, i.EvaluationVerdict, i.EvaluationScore,
                  i.Comment, i.Timestamp, (prev.version if prev else 0) + 1, True)
        newest[key] = e
        result.append(e)

    result.sort(key=lambda e: (e.timestamp, e.version))
    last: dict[tuple[str, str], Entry] = {}
    for e in result:
        prev = last.get((e.user_id, e.evaluation_check_id))
        if prev is not None:
            e.previous_verdict, e.previous_score = prev.verdict, prev.score
        last[(e.user_id, e.evaluation_check_id)] = e
    return result


def unchanged(prev: Entry, verdict: str, score: float | None, comment: str | None) -> bool:
    """Delta rule of BronzeToGold (Input Orchestration ``writer.input_unchanged``):
    same verdict and score as the newest entry and no new comment."""
    return (
        verdict == prev.verdict
        and (None if score is None else float(score)) == (None if prev.score is None else float(prev.score))
        and (not comment or comment == prev.comment)
    )


def current(all_entries: list[Entry]) -> list[Entry]:
    """Newest entry per (user, check)."""
    latest: dict[tuple[str, str], Entry] = {}
    for e in all_entries:
        latest[(e.user_id, e.evaluation_check_id)] = e
    return list(latest.values())


def action_of(e: Entry) -> str:
    """rated (first value) | changed (value differs) | commented (same value, comment only)."""
    if e.previous_verdict is None:
        return "rated"
    if (e.previous_verdict, e.previous_score) != (e.verdict, e.score):
        return "changed"
    return "commented"


def evaluated_tickets(session: Session, user_id: str) -> list[int]:
    """``id_gronos_new`` of all requests the user has evaluated (Gold or pending)."""
    gold = (select(GridConnectionRequest.id_gronos_new)
            .join(RequestEvaluationCheck, RequestEvaluationCheck.GridConnectionRequestID == GridConnectionRequest.ID)
            .where(RequestEvaluationCheck.UserID == user_id))
    bronze = (select(GridConnectionRequest.id_gronos_new)
              .join(UserEvaluationInput, UserEvaluationInput.GridConnectionRequestID == GridConnectionRequest.ID)
              .where(UserEvaluationInput.UserID == user_id))
    return sorted({t for t in session.scalars(gold.union(bronze)) if t is not None})


def evaluators(session: Session) -> list[User]:
    order = {role: i for i, role in enumerate(EVALUATOR_ROLES)}
    users = session.scalars(select(User).where(User.Role.in_(EVALUATOR_ROLES))).all()
    return sorted(users, key=lambda u: (order[u.Role], u.Name or u.Email))


# --------------------------------------------------------------------------- #
# Write path
# --------------------------------------------------------------------------- #
class InputError(ValueError):
    pass


def _next_timestamp(session: Session) -> datetime:
    """Now, but strictly after every existing input, so no input can land
    behind the BronzeToGold watermark. Counterpart: writer.next_input_timestamp
    in Input Orchestration."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    last = session.scalar(select(func.max(UserEvaluationInput.Timestamp)))
    return max(now, last + timedelta(microseconds=1)) if last else now


def normalise(check: EvaluationCheck, verdict: str, score: float | None) -> float | None:
    """Score stored for a verdict, following the framework rules."""
    if verdict != "fulfilled":
        return 0.0 if verdict == "not_fulfilled" else None
    if check.CheckType == "minimum":
        return 0.0
    if check.Graded:
        if score is None or not (1 <= score <= check.Points) or score != int(score):
            raise InputError(f"{check.ID}: Punkte 1 … {check.Points} angeben")
        return float(score)
    return float(check.Points)


def write_inputs(session: Session, user: User, request_id: str, items: list[dict]) -> list[UserEvaluationInput]:
    """Append the inputs in one transaction (BEGIN IMMEDIATE: serialised with
    Input Orchestration, the timestamp is taken inside the lock)."""
    checks = {c.ID: c for c in session.scalars(select(EvaluationCheck).where(
        EvaluationCheck.ID.in_([i["evaluation_check_id"] for i in items])))}
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    ts = _next_timestamp(session)
    rows = []
    for item in items:
        check = checks.get(item["evaluation_check_id"])
        if check is None:
            raise InputError(f"Unbekannter Check {item['evaluation_check_id']}")
        score = normalise(check, item["verdict"], item.get("score"))
        comment = (item.get("comment") or "").strip() or None
        rows.append(UserEvaluationInput(
            ID=str(uuid.uuid4()), GridConnectionRequestID=request_id, EvaluationCheckID=check.ID,
            UserID=user.ID, EvaluationVerdict=item["verdict"], EvaluationScore=score, Comment=comment,
            Timestamp=ts,
        ))
    session.add_all(rows)
    session.commit()
    return rows


def trigger_gold_dag() -> bool:
    """Trigger BronzeToGold via the Airflow 3 REST API (best effort).

    Without AIRFLOW_API_URL nothing happens. Auth: AIRFLOW_API_TOKEN, or
    username/password exchanged at ``/auth/token`` (simple auth manager).
    """
    cfg = airflow_settings()
    if not cfg["url"]:
        return False
    opener = urllib.request.build_opener()

    def post(path: str, body: dict, token: str | None = None) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(cfg["url"] + path, data=json.dumps(body).encode(), headers=headers, method="POST")
        with opener.open(req, timeout=10) as resp:
            return json.loads(resp.read() or b"{}")

    try:
        token = cfg["token"] or (
            post("/auth/token", {"username": cfg["username"], "password": cfg["password"]})["access_token"]
            if cfg["username"] else None
        )
        post(f"/api/v2/dags/{AIRFLOW_GOLD_DAG_ID}/dagRuns", {"logical_date": None}, token)
        return True
    except Exception as exc:  # the input is stored either way
        log.warning("BronzeToGold konnte nicht ausgelöst werden: %s", exc)
        return False


def sub_criterion_of_checks(session: Session) -> dict[str, EvaluationSubCriterion]:
    rows = session.execute(select(EvaluationCheck.ID, EvaluationSubCriterion).join(
        EvaluationSubCriterion, EvaluationSubCriterion.ID == EvaluationCheck.EvaluationSubCriterionID))
    return {check_id: sub for check_id, sub in rows}
