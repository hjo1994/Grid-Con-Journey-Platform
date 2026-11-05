# Grid Con Customer Journey — Backend und Monitoring-App

Netzanschlussanfragen aus C4C/GRONOS werden eingelesen, in einem zentralen
Datenmodell abgelegt und über eine standardisierte API für verschiedene
Applikationen bereitgestellt. Aufbau analog zum Referenzprojekt *AI Cockpit*.

Dieser Branch (`dedicated_env/backend_app`) enthält die beiden Deployments,
die die Daten ausliefern, angepasst an die Plattform (Anmeldung über
`eg-auth`/`eg-auth-react`, Pakete vom Firmen-Spiegel). Die Workflow
Orchestration liegt in `dedicated_env/input_orchestration`, der
Entwicklungsstand aller Module in `main`.

1. **`backend/`** — FastAPI-Schnittstelle (`/api/v1`) auf Silver, Gold und
   Config, geschützt mit `eg-auth`; schreibt nur die Bewertungseingaben nach
   Bronze und löst danach BronzeToGold aus. Details: `backend/README.md`.
2. **`monitoring-app/`** — React-Applikation, meldet per OIDC an
   (`eg-auth-react`) und ruft das Backend mit Bearer-Token auf: Übersicht,
   „Meine Bewertungen“, K1 (Bewertung, eine Spalte je Prüfer:in) und K4
   (Verlauf). Details: `monitoring-app/README.md`.

## Datenbank (Interim)

SQLite-Datei **`/data/db/grid_con.db`**. Zwei Schreiber: Input Orchestration
(Bronze, Silver, Gold, Config) und das Backend (nur `UserEvaluationInputs`),
beide in place mit Transaktionen. Das Volume muss im Backend **schreibbar**
gemountet sein.
