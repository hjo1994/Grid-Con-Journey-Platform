"""Seeding: Config-Tabellen des Bewertungs-Frameworks (EvaluationCriteria,
EvaluationSubCriteria, EvaluationChecks) aus ``evaluation_framework.py``
(evaluation_framework.seed_framework). Nutzer:innen legt dieser Operator nicht an.
"""
from __future__ import annotations

from airflow.models.baseoperator import BaseOperator

from grid_con_ingestion.evaluation_framework import seed_framework


class SeedEvaluationFrameworkOperator(BaseOperator):
    template_fields = ("db_path",)

    def __init__(self, *, db_path: str, **kwargs):
        super().__init__(**kwargs)
        self.db_path = db_path

    def execute(self, context) -> dict:
        stats = seed_framework(self.db_path)
        self.log.info("Evaluation framework seeded into %s: %s", self.db_path, stats)
        return stats
