# Lokaler Stub für `eg-auth`

Übernommen aus dem AI Cockpit (`backend/local_stubs/eg_auth`). Nur für
den Entwicklungsrechner ohne Zugriff auf den Firmen-Spiegel. Im Cluster zählt
ausschließlich, was über `pyproject.toml` installiert ist — dieser Ordner wird
dort nie geladen.

**Im Deployment darf `PYTHONPATH` diesen Ordner niemals enthalten.** PYTHONPATH
hat Vorrang vor installierten Paketen: der Stub würde das echte `eg-auth`
verdrängen und zusammen mit einem versehentlichen `EG_AUTH_DEV_MODE=True` wäre
die API ohne Anmeldung erreichbar. Das Deployment startet ohne PYTHONPATH.

Der Stub unterstützt ausschließlich `EG_AUTH_DEV_MODE=True` — echte OIDC-Prüfung
kann er nicht und soll er nicht vortäuschen. `authorizer()` liefert, wie das
Original, eine `Depends`-Instanz (keine nackte Funktion, sonst 422).

`app/main.py` hängt `local_stubs` nur bei `EG_AUTH_DEV_MODE=True` selbst an den
`sys.path`; im Cluster ist der Wert `False`.

Lokal starten:

```sh
cd backend
EG_AUTH_DEV_MODE=True EG_AUTH_DEV_GROUPS='["app_50hzt_aap_communities_all__x"]' \
GRID_CON_DB_PATH=/pfad/zu/grid_con.db \
  .venv/bin/uvicorn app.main:app --port 8000
```
