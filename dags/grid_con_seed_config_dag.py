"""Seeding der Config-Tabellen: Bewertungs-Framework (EvaluationCriteria,
EvaluationSubCriteria, EvaluationChecks) aus grid_con_ingestion/evaluation_framework.py.

    grid_con_seed_config   (manuell, ohne Zeitplan)
        seed_evaluation_framework

* Einmal nach dem Deployment bzw. nach jeder Aenderung am Framework im Code
  ausloesen. Idempotent: vorhandene Eintraege werden aktualisiert, neue
  ergaenzt, nichts geloescht (Gold-Eintraege koennen auf alte Checks zeigen).
* Legt fehlende Tabellen an. Nutzer:innen (Users) werden hier nicht angelegt.
* BronzeToGold liest die Config-Tabellen nur und bricht ab, solange sie leer sind.
"""
from __future__ import annotations

import datetime
import os
import site
import sys

# Wie in den GRONOS-DAGs: Projektwurzel importierbar machen und fehlende
# Pakete nachinstallieren, bevor die Operatoren sie importieren.
_DAG_DIR = os.path.dirname(os.path.abspath(__file__))
site.addsitedir(_DAG_DIR)
sys.path.insert(0, '/data/dags/grid_con_ingestion/operators')

import dependency_loader  # noqa: E402,F401

from airflow import DAG  # noqa: E402

from grid_con_ingestion import config  # noqa: E402
from grid_con_ingestion.operators.seed_config import SeedEvaluationFrameworkOperator  # noqa: E402

with DAG(
    dag_id="grid_con_seed_config",
    schedule=None,
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["grid-con", "input-orchestration", "config"],
):
    SeedEvaluationFrameworkOperator(task_id="seed_evaluation_framework", db_path=str(config.DB_PATH))
