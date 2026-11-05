"""Bewertungs-Framework des Reifegradverfahrens (Config-Tabellen).

Quelle: Excel "Monitor Netzanschlussanträge Bewertung Reifegrad" (Blatt
"ehem. Zyklus 1 & 2 - 2026", Spalten AP–CT), insbesondere die Formeln der
"Ist-Punktzahl 50Hz"-Spalten. Daraus abgeleitet:

* Kriterien A–C je 30 %, D 10 % (Formel "Gewichtete Gesamtpunktzahl").
* Je Kriterium werden die Punkte der Sub-Kriterien summiert und auf die
  Höchstpunktzahl des Kriteriums normiert (A: 2+1, B: 1+2, C: 2+1, D: 2).
* B1+B2 und C1+C2 werden gemeinsam gepunktet (eine Scoring-Gruppe).
* Checks mit Wert 0 in der Excel sind Mindestanforderungen; "oder"-Spalten
  sind Alternativen (Mindestanforderung: einer genügt; Punkte: höchster Wert).
* Mantelbogen F.1.1 ist eine formale Mindestanforderung ohne Gewicht.

Bewusste Vereinfachungen gegenüber der Excel (fachlich zu bestätigen):
* A1: die zweite Spalte "A1-01" (Wert 2) ist nicht als eigener Check übernommen.
* B3-04 (2 Punkte) setzt in der Excel B3-03 voraus; hier zählt der höchste
  erfüllte Punkte-Check.
* Die Beschreibungstexte der Checks stehen nicht in der Excel (Leitfaden
  zum Reifegradverfahren); ``Description`` ist bis dahin leer.

Die Scoring-Regeln selbst wertet die Bewertungsoberfläche aus
(monitoring-app/src/domain/scoring.ts); hier stehen nur die Stammdaten.
:func:`sync_framework` schreibt sie idempotent in die Datenbank.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Check:
    code: str
    check_type: str  # "minimum" | "points"
    points: int = 0
    alternative_group: str | None = None
    graded: bool = False
    document_category: str | None = None


@dataclass(frozen=True)
class SubCriterion:
    code: str
    name: str
    scoring_group: str
    scoring_group_name: str
    max_score: int
    question: str | None
    checks: list[Check] = field(default_factory=list)


@dataclass(frozen=True)
class Criterion:
    code: str
    name: str
    weight: float
    sub_criteria: list[SubCriterion] = field(default_factory=list)


def _m(code, alt=None, doc=None):
    return Check(code, "minimum", 0, alt, False, doc)


def _p(code, points, alt=None, graded=False, doc=None):
    return Check(code, "points", points, alt, graded, doc)


FRAMEWORK: list[Criterion] = [
    Criterion("F", "Formale Vollständigkeit", 0.0, [
        SubCriterion("F1", "Mantelbogen", "F1", "Mantelbogen", 0,
                     "Liegt der Mantelbogen (Formular F.1.1) vollständig vor?",
                     [_m("F.1.1", doc="Mantelbogen F.1.1")]),
    ]),
    Criterion("A", "Projekt / Fläche", 0.3, [
        SubCriterion("A1", "Flächensicherung Projekt und Kunden-UW", "A1", "Flächensicherung", 2,
                     "Sind die Projektfläche und die Fläche des Kunden-UW gesichert?",
                     [_m("A1-01", doc="Flächensicherungsnachweis"), _m("A1-02", doc="Lageplan + Flurstücke"),
                      _p("A1-03", 1, "A1-P1"), _p("A1-04", 1, "A1-P1"), _p("A1-05", 1, "A1-P1"),
                      _p("A1-06", 2, "A1-P2"), _p("A1-07", 2, "A1-P2"), _p("A1-08", 2, "A1-P2")]),
        SubCriterion("A2", "Genehmigungsstand Projekt", "A2", "Genehmigungsstand", 1,
                     "Wie weit ist das Genehmigungsverfahren des Projekts?",
                     [_p("A2-01", 1, doc="Zeitplan Genehmigungsverfahren")]),
    ]),
    Criterion("B", "Technik", 0.3, [
        SubCriterion("B1", "Techn. Konzept Projekt", "B1+B2", "Technisches Konzept", 1,
                     "Ist das technische Konzept von Projekt und Kunden-UW schlüssig?",
                     [_m("B1-01", doc="Beschreibung techn. + betriebl. Aspekte"), _m("B1-02"), _m("B1-03")]),
        SubCriterion("B2", "Techn. Konzept Kunden-UW", "B1+B2", "Technisches Konzept", 1,
                     "Ist das technische Konzept von Projekt und Kunden-UW schlüssig?",
                     [_m("B2-01", doc="Single-Line-Diagramm"), _m("B2-02"), _m("B2-03"), _m("B2-04"),
                      _m("B2-05"), _p("B2-06", 1)]),
        SubCriterion("B3", "Trassierung zur Anbindung", "B3", "Trassierung", 2,
                     "Ist eine Kabeltrasse zum Netzverknüpfungspunkt geplant und sind die Wegerechte geklärt?",
                     [_m("B3-01", doc="Trassierungsstrategie"), _m("B3-02"), _p("B3-03", 1), _p("B3-04", 2)]),
    ]),
    Criterion("C", "Unternehmen / Finanzen", 0.3, [
        SubCriterion("C1", "Substanz des Unternehmens", "C1+C2", "Substanz und Bestellungen", 2,
                     "Hat das Unternehmen die Substanz für das Vorhaben, und sind zeitkritische Assets bestellt?",
                     [_m("C1-01", "C1-M"), _m("C1-02", "C1-M"), _m("C1-03", "C1-M"), _m("C1-04", "C1-M"),
                      _m("C1-05", "C1-M"), _m("C1-06")]),
        SubCriterion("C2", "Bestellungen", "C1+C2", "Substanz und Bestellungen", 2,
                     "Hat das Unternehmen die Substanz für das Vorhaben, und sind zeitkritische Assets bestellt?",
                     [_m("C2-01", doc="Beschaffungsstrategie"), _m("C2-02"), _p("C2-03", 1),
                      _p("C2-04", 2, "C2-P2"), _p("C2-05", 2, "C2-P2"), _p("C2-06", 2, "C2-P2")]),
        SubCriterion("C3", "Bonität und Finanzierung", "C3", "Bonität", 1,
                     "Ist die Finanzierung durch Bonitätsauskunft oder Rating belegt?",
                     [_p("C3-01", 1, "C3-P1", doc="Bonitätsauskunft"), _p("C3-02", 1, "C3-P1"),
                      _p("C3-03", 1, "C3-P1")]),
    ]),
    Criterion("D", "Hybridisierung", 0.1, [
        SubCriterion("D1", "Projekthybridisierung", "D1", "Hybridisierung", 2,
                     "Ist das Projekt hybridisiert (z. B. mit Speicher)?",
                     [_p("D1-01", 2, graded=True)]),
    ]),
]


def framework_rows() -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Zeilen für EvaluationCriteria, EvaluationSubCriteria, EvaluationChecks."""
    criteria, subs, checks = [], [], []
    for ci, c in enumerate(FRAMEWORK, start=1):
        criteria.append((c.code, c.name, c.weight, ci))
        for si, s in enumerate(c.sub_criteria, start=1):
            subs.append((s.code, c.code, s.name, s.scoring_group, s.scoring_group_name, s.max_score,
                         s.question, ci * 100 + si))
            for ki, k in enumerate(s.checks, start=1):
                checks.append((k.code, s.code, None, k.check_type, k.points, int(k.graded),
                               k.alternative_group, k.document_category, (ci * 100 + si) * 100 + ki))
    return criteria, subs, checks


def sync_framework(conn: sqlite3.Connection) -> dict[str, int]:
    """Legt das Framework an bzw. aktualisiert es (Upsert über die Codes).

    Checks, die aus dem Framework entfallen, bleiben stehen, weil Gold-Einträge
    auf sie zeigen können.
    """
    criteria, subs, checks = framework_rows()
    conn.executemany(
        "INSERT INTO EvaluationCriteria (ID, Name, Weight, SortOrder) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(ID) DO UPDATE SET Name=excluded.Name, Weight=excluded.Weight, SortOrder=excluded.SortOrder",
        criteria,
    )
    conn.executemany(
        "INSERT INTO EvaluationSubCriteria (ID, EvaluationCriterionID, Name, ScoringGroup, ScoringGroupName, "
        "MaxScore, Question, SortOrder) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(ID) DO UPDATE SET EvaluationCriterionID=excluded.EvaluationCriterionID, Name=excluded.Name, "
        "ScoringGroup=excluded.ScoringGroup, ScoringGroupName=excluded.ScoringGroupName, "
        "MaxScore=excluded.MaxScore, Question=excluded.Question, SortOrder=excluded.SortOrder",
        subs,
    )
    conn.executemany(
        "INSERT INTO EvaluationChecks (ID, EvaluationSubCriterionID, Description, CheckType, Points, Graded, "
        "AlternativeGroup, DocumentCategory, SortOrder) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(ID) DO UPDATE SET EvaluationSubCriterionID=excluded.EvaluationSubCriterionID, "
        "Description=COALESCE(EvaluationChecks.Description, excluded.Description), CheckType=excluded.CheckType, "
        "Points=excluded.Points, Graded=excluded.Graded, AlternativeGroup=excluded.AlternativeGroup, "
        "DocumentCategory=excluded.DocumentCategory, SortOrder=excluded.SortOrder",
        checks,
    )
    return {"criteria": len(criteria), "sub_criteria": len(subs), "checks": len(checks)}
