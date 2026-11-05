"""Collaborative evaluation (K1 "Spalte je Prüfer", K4 "Verlauf").

Identity: the signed-in user (eg-auth). Their e-mail is looked up in
``Users.Email`` (case-insensitive); the role there decides whether they may
evaluate. Every endpoint needs a signed-in user (``authorizer()``); a user
without a Users entry may read but not evaluate.
"""
from __future__ import annotations

from typing import Annotated, Literal

from eg_auth.fastapi import UserInfo
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import authorizer
from app.db import get_session, get_write_session
from app.evaluation import (
    InputError,
    action_of,
    current,
    entries,
    evaluated_tickets,
    evaluators,
    sub_criterion_of_checks,
    trigger_gold_dag,
    write_inputs,
)
from app.models import (
    EVALUATOR_ROLES,
    ROLES,
    EvaluationCheck,
    EvaluationCriterion,
    EvaluationSubCriterion,
    User,
)
from app.models import GridConnectionRequest as Request
from app.queries import latest_condition
from app.schemas import (
    CheckOut,
    CriterionOut,
    EvaluationEntryOut,
    EvaluationHistory,
    EvaluationInputBody,
    EvaluationInputResult,
    EvaluationState,
    HistoryEntryOut,
    MeOut,
    SubCriterionOut,
    UserEvaluationItem,
    UserEvaluations,
    UserOut,
)

router = APIRouter(prefix="/api/v1", tags=["evaluation"], dependencies=[authorizer()])

Db = Annotated[Session, Depends(get_session)]
SignedIn = Annotated[UserInfo, authorizer()]


def registered_user(session: Session, info: UserInfo) -> User | None:
    """Users entry of the signed-in user (by e-mail), or None."""
    email = (info.email or "").strip().lower()
    if not email:
        return None
    return session.scalars(select(User).where(func.lower(User.Email) == email)).first()


def user_out(u: User) -> UserOut:
    return UserOut(id=u.ID, email=u.Email, name=u.Name, role=u.Role, role_label=ROLES.get(u.Role, u.Role),
                   can_evaluate=u.Role in EVALUATOR_ROLES)


def entry_out(e) -> EvaluationEntryOut:
    return EvaluationEntryOut(id=e.id, user_id=e.user_id, evaluation_check_id=e.evaluation_check_id,
                              verdict=e.verdict, score=e.score, comment=e.comment, version=e.version,
                              timestamp=e.timestamp, pending=e.pending)


def current_request(session: Session, id_gronos_new: int) -> Request:
    request = session.scalars(
        select(Request).where(Request.id_gronos_new == id_gronos_new, latest_condition())
    ).first()
    if request is None:
        raise HTTPException(status_code=404, detail="Netzanschlussanfrage nicht gefunden")
    return request


@router.get("/users", response_model=list[UserOut])
def list_users(session: Db) -> list[UserOut]:
    """All users with their role; ``can_evaluate`` for the evaluator roles."""
    users = session.scalars(select(User).order_by(User.Role, User.Name, User.Email)).all()
    return [user_out(u) for u in users]


@router.get("/users/me", response_model=MeOut)
def me(session: Db, info: SignedIn) -> MeOut:
    """The signed-in user and their Users entry (role, ``can_evaluate``)."""
    user = registered_user(session, info)
    return MeOut(email=info.email, name=info.name, user=user_out(user) if user else None)


@router.get("/users/me/evaluations", response_model=UserEvaluations)
def my_evaluations(session: Db, info: SignedIn, response: Response) -> UserEvaluations:
    """"Meine Bewertungen": every request the signed-in user has evaluated with
    their current check results (Gold + pending), most recently changed first.
    The maturity level is computed by the client from ``checks`` and the
    framework, as in K1."""
    user = registered_user(session, info)
    if user is None:
        raise HTTPException(status_code=404, detail="Nicht als Nutzer:in angelegt")
    items = []
    for ticket in evaluated_tickets(session, user.ID):
        own = [e for e in entries(session, ticket) if e.user_id == user.ID]
        if not own:
            continue
        request = current_request(session, ticket)
        items.append(UserEvaluationItem(
            id_gronos_new=ticket, id_gronos_old=request.id_gronos_old,
            generation_technology=request.GenerationTechnology, max_p=request.maxP,
            request_status=request.RequestStatus, checks=[entry_out(e) for e in current(own)],
            last_change=max(e.timestamp for e in own), pending=any(e.pending for e in own)))
    items.sort(key=lambda i: i.last_change, reverse=True)
    response.headers["Cache-Control"] = "no-store"
    return UserEvaluations(user=user_out(user), items=items, total=len(items))


@router.get("/evaluation-framework", response_model=list[CriterionOut])
def framework(session: Db) -> list[CriterionOut]:
    """Criteria → sub-criteria → checks in display order (Config tables)."""
    checks: dict[str, list[CheckOut]] = {}
    for c in session.scalars(select(EvaluationCheck).order_by(EvaluationCheck.SortOrder)):
        checks.setdefault(c.EvaluationSubCriterionID, []).append(CheckOut(
            id=c.ID, description=c.Description, check_type=c.CheckType, points=c.Points, graded=bool(c.Graded),
            alternative_group=c.AlternativeGroup, document_category=c.DocumentCategory))
    subs: dict[str, list[SubCriterionOut]] = {}
    for s in session.scalars(select(EvaluationSubCriterion).order_by(EvaluationSubCriterion.SortOrder)):
        subs.setdefault(s.EvaluationCriterionID, []).append(SubCriterionOut(
            id=s.ID, name=s.Name, scoring_group=s.ScoringGroup, scoring_group_name=s.ScoringGroupName,
            max_score=s.MaxScore, question=s.Question, checks=checks.get(s.ID, [])))
    return [
        CriterionOut(id=c.ID, name=c.Name, weight=c.Weight, sub_criteria=subs.get(c.ID, []))
        for c in session.scalars(select(EvaluationCriterion).order_by(EvaluationCriterion.SortOrder))
    ]


@router.get("/grid-connection-requests/{id_gronos_new}/evaluation", response_model=EvaluationState)
def evaluation_state(id_gronos_new: int, session: Db, response: Response) -> EvaluationState:
    """Current evaluation of a request: newest entry per evaluator and check,
    including inputs not yet processed by BronzeToGold (``pending``). Cheap
    enough to poll every few seconds."""
    request = current_request(session, id_gronos_new)
    all_entries = entries(session, id_gronos_new)
    response.headers["Cache-Control"] = "no-store"
    return EvaluationState(
        id_gronos_new=id_gronos_new,
        grid_connection_request_id=request.ID,
        evaluators=[user_out(u) for u in evaluators(session)],
        checks=[entry_out(e) for e in current(all_entries)],
        last_change=max((e.timestamp for e in all_entries), default=None),
    )


@router.get("/grid-connection-requests/{id_gronos_new}/evaluation-history", response_model=EvaluationHistory)
def evaluation_history(
    id_gronos_new: int,
    session: Db,
    response: Response,
    kind: Annotated[Literal["all", "ratings", "comments"], Query(
        description="ratings = only entries that set or change a value, comments = only entries with a comment")] = "all",
    scoring_group: Annotated[str | None, Query(description="e.g. B3 or B1+B2")] = None,
    user_id: Annotated[str | None, Query()] = None,
) -> EvaluationHistory:
    """Change log of all users, newest first, with the previous value of the
    same user and check (K4)."""
    current_request(session, id_gronos_new)
    subs = sub_criterion_of_checks(session)
    items = []
    for e in reversed(entries(session, id_gronos_new)):
        sub = subs[e.evaluation_check_id]
        action = action_of(e)
        if kind == "ratings" and action == "commented":
            continue
        if kind == "comments" and not e.comment:
            continue
        if scoring_group and sub.ScoringGroup != scoring_group:
            continue
        if user_id and e.user_id != user_id:
            continue
        items.append(HistoryEntryOut(
            **entry_out(e).model_dump(), action=action, previous_verdict=e.previous_verdict,
            previous_score=e.previous_score, sub_criterion_id=sub.ID, scoring_group=sub.ScoringGroup))
    response.headers["Cache-Control"] = "no-store"
    return EvaluationHistory(id_gronos_new=id_gronos_new, items=items, total=len(items))


@router.post(
    "/grid-connection-requests/{id_gronos_new}/evaluation-inputs",
    response_model=EvaluationInputResult,
    status_code=201,
)
def post_evaluation_inputs(
    id_gronos_new: int,
    body: EvaluationInputBody,
    background: BackgroundTasks,
    session: Annotated[Session, Depends(get_write_session)],
    info: SignedIn,
) -> EvaluationInputResult:
    """Store one or several check evaluations of the signed-in user (Bronze
    UserEvaluationInputs, append-only) and trigger BronzeToGold. The monitoring
    app sends everything staged until "Bewertung speichern" in one call.

    Every input is stored in Bronze; ``items`` lists only those that change
    the current state (the same delta rule BronzeToGold applies),
    ``unchanged`` counts the rest.

    verdict ``fulfilled`` / ``not_fulfilled`` / ``open`` (withdraw); a comment
    with an unchanged verdict is a comment-only entry. The score is derived
    from the framework (minimum checks 0, points checks their points); only
    for ``graded`` checks the evaluator sends 1 … points.
    """
    user = registered_user(session, info)
    if user is None:
        raise HTTPException(status_code=403, detail="Nicht als Prüfer:in angelegt")
    if user.Role not in EVALUATOR_ROLES:
        raise HTTPException(status_code=403, detail="Diese Rolle darf nicht bewerten")
    request = current_request(session, id_gronos_new)
    try:
        rows = write_inputs(session, user, request.ID, [i.model_dump() for i in body.checks])
    except InputError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # versions as the read model will show them
    by_id = {e.id: e for e in entries(session, id_gronos_new)}
    background.add_task(trigger_gold_dag)
    return EvaluationInputResult(
        items=[entry_out(by_id[r.ID]) for r in rows if r.ID in by_id],
        unchanged=sum(r.ID not in by_id for r in rows),
        gold_triggered=False,  # the trigger runs after the response; see logs
    )
