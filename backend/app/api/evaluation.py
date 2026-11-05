"""Collaborative evaluation (K1 "Spalte je Prüfer", K4 "Verlauf").

Access: every endpoint needs a signed-in user (eg-auth, ``authorizer()``).
The evaluator is chosen in the app's header independent of the sign-in and
passed in the ``X-User-ID`` header (Users.ID) when saving; reading needs no
evaluator.
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import authorizer
from app.db import get_session, get_write_session
from app.evaluation import (
    InputError,
    action_of,
    current,
    entries,
    entries_for,
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
from app.scoring import (
    Framework,
    best_points,
    combined_percent,
    deviates,
    diverging_groups,
    group_score,
    load_framework,
    overall_score,
    short_of,
)
from app.schemas import (
    CheckOut,
    CheckResultOut,
    CombinedScoreOut,
    CriterionOut,
    EvaluationEntryOut,
    EvaluationHistory,
    EvaluationInputBody,
    EvaluationInputResult,
    EvaluationScoreSummaries,
    EvaluationScoreSummary,
    EvaluationState,
    GroupScoreOut,
    HistoryEntryOut,
    RequestEvaluationScores,
    ReviewerScoreOut,
    ReviewerSummaryOut,
    SubCriterionOut,
    SubCriterionResultOut,
    UserEvaluationItem,
    UserEvaluations,
    UserOut,
)

router = APIRouter(prefix="/api/v1", tags=["evaluation"], dependencies=[authorizer()])

Db = Annotated[Session, Depends(get_session)]


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


@router.get("/users/{user_id}/evaluations", response_model=UserEvaluations)
def user_evaluations(user_id: str, session: Db, response: Response) -> UserEvaluations:
    """"Meine Bewertungen": every request the user has evaluated with their
    current check results (Gold + pending), most recently changed first. The
    maturity level is computed by the client from ``checks`` and the framework,
    as in K1."""
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Unbekannte Nutzer:in")
    items = []
    for ticket in evaluated_tickets(session, user_id):
        own = [e for e in entries(session, ticket) if e.user_id == user_id]
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


def request_scores(fw: Framework, users: list[User], ticket: int, all_entries) -> RequestEvaluationScores:
    """Scores of one request from its entries (Gold + pending), see app/scoring.py."""
    latest = [e for e in current(all_entries) if e.evaluation_check_id in fw.checks]
    group_results = []
    reviewers = []
    for u in users:
        own = [e for e in latest if e.user_id == u.ID]
        values = {e.evaluation_check_id: (e.verdict, e.score) for e in own}
        results = {g.key: group_score(g, values) for g in fw.groups}
        percent, complete = overall_score(fw, results)
        by_check = {e.evaluation_check_id: e for e in own}
        subs = []
        for s in fw.sub_criteria:
            checks = [CheckResultOut(**entry_out(by_check[c.id]).model_dump(), sub_criterion_id=s.id,
                                     check_type=c.check_type, points=c.points, graded=c.graded,
                                     alternative_group=c.alternative_group)
                      for c in s.checks if c.id in by_check]
            subs.append(SubCriterionResultOut(sub_criterion_id=s.id, scoring_group=s.scoring_group,
                                              criterion_id=s.criterion_id, points=best_points(s.checks, values),
                                              checks=checks))
        times = [e.timestamp for e in all_entries if e.user_id == u.ID]
        group_results.append(results)
        reviewers.append(ReviewerScoreOut(
            user=user_out(u), percent=percent, complete=complete, deviates=False,
            last_change=max(times, default=None), sub_criteria=subs,
            groups=[GroupScoreOut(scoring_group=g.key, criterion_id=g.criterion_id, max_score=g.max_score,
                                  score=results[g.key].score, status=results[g.key].status) for g in fw.groups]))
    diverging = diverging_groups(fw, group_results)
    for r, flag in zip(reviewers, deviates(diverging, group_results)):
        r.deviates = flag
    done = sum(r.complete for r in reviewers)
    return RequestEvaluationScores(
        id_gronos_new=ticket,
        last_change=max((e.timestamp for e in all_entries), default=None),
        combined=CombinedScoreOut(percent=combined_percent([r.percent for r in reviewers]), done=done,
                                  total=len(reviewers), complete=bool(reviewers) and done == len(reviewers),
                                  diverging_groups=diverging),
        reviewers=reviewers,
    )


@router.get("/grid-connection-requests/{id_gronos_new}/evaluation-scores", response_model=RequestEvaluationScores)
def evaluation_scores(id_gronos_new: int, session: Db, response: Response) -> RequestEvaluationScores:
    """Reifegrad of one request, computed in the backend: per evaluator the
    latest result of every check (Gold + inputs not yet processed by
    BronzeToGold), grouped by sub-criterion, with points per sub-criterion,
    score per scoring group and overall percent; plus the combined score of
    all evaluators. The editing view loads it once and recomputes the own
    column locally while the user changes checks."""
    current_request(session, id_gronos_new)
    response.headers["Cache-Control"] = "no-store"
    return request_scores(load_framework(session), evaluators(session), id_gronos_new, entries(session, id_gronos_new))


@router.get("/evaluation-scores", response_model=EvaluationScoreSummaries)
def evaluation_score_summaries(
    session: Db,
    response: Response,
    ids: Annotated[list[int], Query(description="id_gronos_new, mehrfach angebbar (höchstens 500)")],
) -> EvaluationScoreSummaries:
    """Compact Reifegrad of several requests for the overview: combined score,
    per evaluator percent, complete and deviates, diverging groups and the
    number of comments. Unknown ids are left out."""
    if len(ids) > 500:
        raise HTTPException(status_code=422, detail="Höchstens 500 ids")
    wanted = list(dict.fromkeys(ids))
    known = set(session.scalars(select(Request.id_gronos_new).where(Request.id_gronos_new.in_(wanted))))
    fw = load_framework(session)
    users = evaluators(session)
    by_ticket = entries_for(session, wanted)
    items = []
    for ticket in wanted:
        if ticket not in known:
            continue
        all_entries = by_ticket.get(ticket, [])
        s = request_scores(fw, users, ticket, all_entries)
        items.append(EvaluationScoreSummary(
            id_gronos_new=ticket, percent=s.combined.percent, done=s.combined.done, total=s.combined.total,
            complete=s.combined.complete, diverging_groups=s.combined.diverging_groups,
            comment_count=sum(1 for e in all_entries if e.comment), last_change=s.last_change,
            reviewers=[ReviewerSummaryOut(user_id=r.user.id, name=r.user.name, role=r.user.role,
                                          role_label=r.user.role_label, short=short_of(r.user.role),
                                          percent=r.percent, complete=r.complete, deviates=r.deviates,
                                          last_change=r.last_change) for r in s.reviewers]))
    response.headers["Cache-Control"] = "no-store"
    return EvaluationScoreSummaries(items=items, total=len(items))


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
    x_user_id: Annotated[str | None, Header(description="Users.ID of the acting evaluator")] = None,
) -> EvaluationInputResult:
    """Store one or several check evaluations of the acting user (Bronze
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
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-ID fehlt")
    user = session.get(User, x_user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Unbekannte Nutzer:in")
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
