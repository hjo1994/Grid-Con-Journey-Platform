"""Installiert fehlende Python-Pakete zur Laufzeit nach /tmp/airflow_packages.

Das Airflow-Image der Plattform bringt polars und fastexcel nicht mit, und
/tmp ist nach jedem Deployment leer. Beim Parsen des DAGs wird geprüft, ob
die Pakete importierbar sind; fehlende werden per pip installiert. Anders als
früher wartet der Loader auf pip (höchstens WAIT_SECONDS), damit schon der
erste Parse nach einem Deployment die Operatoren importieren kann.

Dauert pip länger, läuft es im Hintergrund weiter und entfernt die Lock-Datei
selbst, sobald es fertig ist; der nächste Parse wartet dann erneut bzw. findet
die Pakete. Eine Lock-Datei, die älter als STALE_LOCK_SECONDS ist (z. B. weil
pip abgebrochen wurde), wird ignoriert und neu angelegt.
"""
import importlib
import os
import shlex
import subprocess
import sys
import time

TMP_PACKAGES_DIR = "/tmp/airflow_packages"
LOCK_FILE = os.path.join(TMP_PACKAGES_DIR, "pip.lock")
PIP_LOG = os.path.join(TMP_PACKAGES_DIR, "pip.log")

# (Import-Name, pip-Name) – pyarrow wird vom Code nicht gebraucht.
REQUIRED_PACKAGES = [
    ("polars", "polars"),
    ("fastexcel", "fastexcel"),
]

# Muss unter [core] dag_file_processor_timeout bleiben (Standard 50 s).
WAIT_SECONDS = int(os.environ.get("GRID_CON_PIP_WAIT_SECONDS", "40"))
STALE_LOCK_SECONDS = 15 * 60


def _missing() -> list[str]:
    importlib.invalidate_caches()  # neu installierte Pakete sichtbar machen
    missing = []
    for import_name, pip_name in REQUIRED_PACKAGES:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)
    return missing


def _lock_is_fresh() -> bool:
    try:
        return time.time() - os.path.getmtime(LOCK_FILE) < STALE_LOCK_SECONDS
    except FileNotFoundError:
        return False


def _wait_for_lock(deadline: float) -> None:
    while _lock_is_fresh() and time.time() < deadline:
        time.sleep(1)


def ensure_dependencies() -> None:
    os.makedirs(TMP_PACKAGES_DIR, exist_ok=True)
    if TMP_PACKAGES_DIR not in sys.path:
        sys.path.insert(0, TMP_PACKAGES_DIR)

    missing = _missing()
    if not missing:
        return

    deadline = time.time() + WAIT_SECONDS

    if _lock_is_fresh():
        print(f"Auto-Installer: Installation läuft bereits, warte auf: {', '.join(missing)}")
    else:
        print(f"Auto-Installer: Installiere {', '.join(missing)} nach {TMP_PACKAGES_DIR} ...")
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        env = os.environ.copy()
        env["PIP_USER"] = "false"
        pip_cmd = " ".join(
            shlex.quote(part)
            for part in [sys.executable, "-m", "pip", "install", f"--target={TMP_PACKAGES_DIR}",
                         "--no-cache-dir", *missing]
        )
        # Lock-Datei entfernt pip selbst, wenn es fertig ist – auch wenn wir
        # nicht bis zum Ende warten. Ausgabe landet in pip.log zur Fehlersuche.
        subprocess.Popen(
            f"{pip_cmd} > {shlex.quote(PIP_LOG)} 2>&1; rm -f {shlex.quote(LOCK_FILE)}",
            shell=True,
            env=env,
            start_new_session=True,  # pip überlebt das Ende des Parse-Prozesses
        )

    _wait_for_lock(deadline)

    missing = _missing()
    if missing:
        print(
            f"Auto-Installer: {', '.join(missing)} noch nicht verfügbar "
            f"(pip läuft weiter, siehe {PIP_LOG}); nächster Parse versucht es erneut."
        )
    else:
        print("Auto-Installer: Pakete verfügbar.")


ensure_dependencies()
