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
