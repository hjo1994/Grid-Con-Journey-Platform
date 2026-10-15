"""Grid Con Input Orchestration.

Im Airflow-Deployment installiert dags/dependency_loader.py fehlende Pakete
(polars, fastexcel, pyarrow) nach /tmp/airflow_packages; der Pfad wird hier
ergänzt, damit er auch in den Task-Prozessen vor dem ersten polars-Import
im sys.path steht.
"""
import site

site.addsitedir("/tmp/airflow_packages")
