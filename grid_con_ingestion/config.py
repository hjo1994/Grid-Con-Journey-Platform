"""Environment-based configuration for the Input Orchestration DAG."""
import os
from pathlib import Path

# Quelle: "file" (Quellordner) – später "api" (siehe sources.ApiSource)
SOURCE_TYPE = os.environ.get("GRID_CON_SOURCE_TYPE", "file")

SOURCE_DIR = Path(os.environ.get("SOURCE_DIR", "/data/source"))
SOURCE_FILENAME_GLOB = os.environ.get("SOURCE_FILENAME_GLOB", "C4C_GRONOS_*.xlsx")

# Zentrale SQLite-Datenbank (Volume /data/db, read-only im Backend gemountet).
DB_PATH = Path(os.environ.get("GRID_CON_DB_PATH", "/data/db/grid_con.db"))

# Platzhalter für die spätere API-Anbindung
API_BASE_URL = os.environ.get("GRID_CON_API_BASE_URL", "")
API_CONN_ID = os.environ.get("GRID_CON_API_CONN_ID", "grid_con_c4c_api")


def source_kwargs() -> dict:
    """Parameter für die gewählte Quelle (werden an sources.build_source übergeben)."""
    if SOURCE_TYPE == "file":
        return {"source_dir": str(SOURCE_DIR), "filename_glob": SOURCE_FILENAME_GLOB}
    if SOURCE_TYPE == "api":
        return {"base_url": API_BASE_URL, "conn_id": API_CONN_ID, "staging_dir": str(SOURCE_DIR)}
    raise ValueError(f"Unbekannter GRID_CON_SOURCE_TYPE: {SOURCE_TYPE}")


# --------------------------------------------------------------------------- #
# GRONOS-API (SAP API Management), DAGs gronos_raw_to_bronze / gronos_bronze_to_silver
# --------------------------------------------------------------------------- #
# Basis-URL des Tenants, z. B. https://eliagroup-111-dev.test.apimanagement.eu10.hana.ondemand.com
GRONOS_API_BASE_URL = os.environ.get("GRONOS_API_BASE_URL", "")
# Client-Credentials aus einem OpenShift-Secret (nie im Repo / in Helm-Values im Klartext)
GRONOS_API_CLIENT_ID = os.environ.get("GRONOS_API_CLIENT_ID", "")
GRONOS_API_CLIENT_SECRET = os.environ.get("GRONOS_API_CLIENT_SECRET", "")
# companyId-Präfixe für den Listenabruf ("*" allein läuft in einen Gateway-Timeout);
# Bereiche und Einzelwerte, kommagetrennt. Zu breite Präfixe werden automatisch geteilt.
GRONOS_COMPANY_ID_PREFIXES = os.environ.get("GRONOS_COMPANY_ID_PREFIXES", "1000-1299")
# Detail call per request: "always" (dev: the list lacks contacts and stages),
# "auto" (only when the list record has no "contacts"; ACC lists are complete),
# "never" (store the list record as is).
GRONOS_DETAIL_MODE = os.environ.get("GRONOS_DETAIL_MODE", "auto").strip().lower()
GRONOS_MAX_PREFIX_LENGTH = int(os.environ.get("GRONOS_MAX_PREFIX_LENGTH", "7"))
GRONOS_API_TIMEOUT = float(os.environ.get("GRONOS_API_TIMEOUT", "150"))
# Vom Pod aus ist die API ohne Proxy erreichbar (getestet 27.10.2026)
GRONOS_API_USE_ENV_PROXY = os.environ.get("GRONOS_API_USE_ENV_PROXY", "false").lower() == "true"
GRONOS_RAW_TO_BRONZE_SCHEDULE = os.environ.get("GRONOS_RAW_TO_BRONZE_SCHEDULE", "*/30 * * * *")


def gronos_client():
    from grid_con_ingestion.gronos.client import GronosClient

    return GronosClient(
        GRONOS_API_BASE_URL,
        GRONOS_API_CLIENT_ID,
        GRONOS_API_CLIENT_SECRET,
        timeout=GRONOS_API_TIMEOUT,
        max_prefix_length=GRONOS_MAX_PREFIX_LENGTH,
        use_env_proxy=GRONOS_API_USE_ENV_PROXY,
    )
