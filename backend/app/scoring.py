"""Maturity score (Reifegrad) of the collaborative evaluation.

Computed from the latest check result per user and check (Gold + pending
Bronze, ``app.evaluation``) and the framework tables. Same rules as the
monitoring app's live recompute while editing (``monitoring-app/src/domain/
scoring.ts``); both run the shared cases in ``tests/scoring_cases.json``.

* Sub-criteria with the same ``ScoringGroup`` are scored together (B1+B2).
* Minimum checks (``CheckType`` "minimum") must be fulfilled and give no
  points. Checks sharing an ``AlternativeGroup`` are alternatives: one
  fulfilled is enough. A failed minimum requirement sets the group to 0.
* Points checks give their stored score when fulfilled; the group gets the
  highest value reached, capped at ``MaxScore``.
* A group is incomplete while a minimum requirement is still open; it is
  empty while none of its checks is evaluated.
* Overall = Σ criterion weight × (points of the criterion / max points of the
  criterion), in percent with one decimal.
* Combined (all reviewers) = mean of the reviewers who have a score.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EvaluationCheck, EvaluationCriterion, EvaluationSubCriterion

EVALUATED = ("fulfilled", "not_fulfilled")


@dataclass
class Check:
    id: str
    sub_criterion_id: str
    check_type: str
    points: int
    graded: bool
    alternative_group: str | None


@dataclass
class SubCriterion:
    id: str
    criterion_id: str
    scoring_group: str
    checks: list[Check] = field(default_factory=list)


@dataclass
class Group:
    key: str
    name: str
    criterion_id: str
    max_score: int
    checks: list[Check] = field(default_factory=list)


@dataclass
class Framework:
    weights: dict[str, float]          # criterion id → weight, in display order
    sub_criteria: list[SubCriterion]
    groups: list[Group]
    checks: dict[str, Check]


@dataclass
class GroupResult:
    score: float | None
    status: str  # complete | incomplete | min_failed | empty


# verdict and stored score per check id of one user
Values = dict[str, tuple[str, float | None]]


def load_framework(session: Session) -> Framework:
    criteria = session.scalars(select(EvaluationCriterion).order_by(EvaluationCriterion.SortOrder)).all()
    subs = session.scalars(select(EvaluationSubCriterion).order_by(EvaluationSubCriterion.SortOrder)).all()
    checks = session.scalars(select(EvaluationCheck).order_by(EvaluationCheck.SortOrder)).all()
    by_sub: dict[str, list[Check]] = {}
    all_checks: dict[str, Check] = {}
    for c in checks:
        check = Check(c.ID, c.EvaluationSubCriterionID, c.CheckType, c.Points, bool(c.Graded), c.AlternativeGroup)
        by_sub.setdefault(c.EvaluationSubCriterionID, []).append(check)
        all_checks[c.ID] = check
    order = {c.ID: i for i, c in enumerate(criteria)}
    sub_criteria: list[SubCriterion] = []
    groups: dict[str, Group] = {}
    # criteria order first, then the sub-criteria's own order (as the framework endpoint)
    for s in sorted(subs, key=lambda s: (order.get(s.EvaluationCriterionID, len(order)), s.SortOrder)):
        own = by_sub.get(s.ID, [])
        sub_criteria.append(SubCriterion(s.ID, s.EvaluationCriterionID, s.ScoringGroup, own))
        g = groups.setdefault(s.ScoringGroup, Group(s.ScoringGroup, s.ScoringGroupName, s.EvaluationCriterionID, s.MaxScore))
        g.checks.extend(own)
    return Framework({c.ID: c.Weight for c in criteria}, sub_criteria, list(groups.values()), all_checks)


def round1(x: float) -> float:
    """Half up to one decimal, like ``Math.round(x * 10) / 10`` in the UI."""
    return math.floor(x * 10 + 0.5) / 10


def best_points(checks: list[Check], values: Values) -> float | None:
    """Highest score of the fulfilled points checks; None if none is evaluated."""
    if not any(values.get(c.id, ("open", None))[0] in EVALUATED for c in checks):
        return None
    points = 0.0
    for c in checks:
        if c.check_type != "points":
            continue
        verdict, score = values.get(c.id, ("open", None))
        if verdict == "fulfilled":
            points = max(points, (score or 0.0) if c.graded else float(c.points))
    return points


def group_score(group: Group, values: Values) -> GroupResult:
    def verdict(c: Check) -> str:
        return values.get(c.id, ("open", None))[0]

    if not any(verdict(c) in EVALUATED for c in group.checks):
        return GroupResult(None, "empty")
    units: dict[str, list[Check]] = {}
    for c in group.checks:
        if c.check_type == "minimum":
            units.setdefault(c.alternative_group or c.id, []).append(c)
    incomplete = False
    for checks in units.values():
        if any(verdict(c) == "fulfilled" for c in checks):
            continue
        if all(verdict(c) == "not_fulfilled" for c in checks):
            return GroupResult(0.0, "min_failed")
        incomplete = True
    points = best_points(group.checks, values) or 0.0
    return GroupResult(min(points, float(group.max_score)), "incomplete" if incomplete else "complete")


def overall_score(fw: Framework, results: dict[str, GroupResult]) -> tuple[float | None, bool]:
    """(percent, complete) of one user from their group results."""
    percent = 0.0
    scored = False
    complete = True
    for criterion, weight in fw.weights.items():
        own = [g for g in fw.groups if g.criterion_id == criterion]
        scores = [results[g.key] for g in own]
        if any(s.status != "complete" for s in scores):
            complete = False
        max_points = sum(g.max_score for g in own)
        if weight == 0 or max_points == 0:
            continue
        got = sum(s.score or 0.0 for s in scores)
        if any(s.score is not None for s in scores):
            scored = True
        percent += weight * (got / max_points)
    return (round1(percent * 100) if scored else None), complete


def diverging_groups(fw: Framework, per_user: list[dict[str, GroupResult]]) -> list[str]:
    """Groups with points in which the reviewers who scored them disagree."""
    result = []
    for g in fw.groups:
        if g.max_score == 0:
            continue
        given = {r[g.key].score for r in per_user if r[g.key].score is not None}
        if len(given) > 1:
            result.append(g.key)
    return result


def deviates(group_keys: list[str], per_user: list[dict[str, GroupResult]]) -> list[bool]:
    """Per reviewer: in a diverging group their score differs from the most
    common score, or there is no single most common score."""
    flags = [False] * len(per_user)
    for key in group_keys:
        scores = [r[key].score for r in per_user]
        counts = Counter(s for s in scores if s is not None).most_common()
        mode = counts[0][0] if len(counts) == 1 or counts[0][1] > counts[1][1] else None
        for i, s in enumerate(scores):
            if s is not None and s != mode:
                flags[i] = True
    return flags


def combined_percent(percents: list[float | None]) -> float | None:
    given = [p for p in percents if p is not None]
    return round1(sum(given) / len(given)) if given else None


ROLE_SHORT = {"netzplanung": "NP", "flaechen_recht": "RE", "finanzen": "FI"}


def short_of(role: str) -> str:
    return ROLE_SHORT.get(role, role[:2].upper())
