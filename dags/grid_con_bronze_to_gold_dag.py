"""BronzeToGold: Eingaben der Pruefer:innen (UserEvaluationInputs) ->
RequestEvaluationChecks.

    grid_con_bronze_to_gold   (ausgeloest vom Backend, optional Schedule)
        bronze_to_gold

* Das Backend loest den DAG nach jeder gespeicherten Bewertung ueber die
  Airflow-REST-API aus (POST /api/v1/dags/grid_con_bronze_to_gold/dagRuns).
  Optional zusaetzlich per GRID_CON_GOLD_SCHEDULE (z. B. "*/15 * * * *").
* bronze_to_gold: verarbeitet alle Eingaben mit Timestamp nach dem letzten
  Lauf (MAX(BusinessTransactions.InputBronzeTimestamp) der Gold-Vorgaenge).
  Jede Eingabe bekommt eine BusinessTransaction; ein RequestEvaluationChecks-
  Eintrag (naechste Version) entsteht nur, wenn sie sich vom letzten Gold-Stand
  derselben Nutzer:in und desselben Checks unterscheidet.

max_active_runs=1 reiht schnell aufeinander folgende Ausloesungen ein; jede
Eingabe wird genau einmal verarbeitet.
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
from grid_con_ingestion.operators.bronze_to_gold import BronzeToGoldOperator  # noqa: E402

with DAG(
    dag_id=config.GOLD_DAG_ID,
    schedule=config.GOLD_SCHEDULE,
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["grid-con", "input-orchestration", "gold"],
):
    BronzeToGoldOperator(task_id="bronze_to_gold", db_path=str(config.DB_PATH))
