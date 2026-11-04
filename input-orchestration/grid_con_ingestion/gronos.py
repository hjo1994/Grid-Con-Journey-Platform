"""GRONOS-API: Abruf der Netzanschlussanträge und Ableitung der Silver-Werte.

Abruf (RawToBronze), wie im Pod am 27.10. und 02.11.2026 getestet
(``api-zugriff/test_double_call_pod*.txt``):

1. OAuth-Token per Client Credentials (Basic Auth,
   ``POST …/v1/api/OAuthService/GenerateToken``).
2. **Liste** ``GET …/http/CP1001/IF0058/ConnectionRequest?companyId=<präfix>*``.
   Ein einfaches ``*`` läuft in einen Timeout, deshalb über companyId-Präfixe;
   bei 502/503/504 bzw. Abbruch wird das Präfix um eine Ziffer verfeinert
   (bis 7 Stellen). Jeder Antrag kommt doppelt → Duplikate über ``objectId``.
3. **Delta**: nur Anträge, deren ``updatedAt`` neuer ist als der neueste Stand
   in Bronze (oder die noch nicht in Bronze sind).
4. **Detail** je verbleibendem Antrag
   ``GET …/ConnectionRequest?id=<objectId>&companyId=<companyId>*``.

Bei 401 wird der Token einmal erneuert; andere Fehler brechen den Lauf ab,
bevor etwas geschrieben wird (kein Teil-Abruf in Bronze).

:func:`derive_request` / :func:`derive_customer` bilden einen Bronze-Datensatz
(Detail-JSON) auf die Silver-Spalten ab, nach dem Mapping in
``api-zugriff/proposal-bronze-gronosexport.md`` (Abschnitt 2). Codes
(``status``, ``nextActor``, …) bleiben Codes, bis die Code-Listen vorliegen.
"""
from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable

log = logging.getLogger(__name__)

TOKEN_PATH = "/v1/api/OAuthService/GenerateToken"
REQUEST_PATH = "/http/CP1001/IF0058/ConnectionRequest"
GATEWAY_ERRORS = {0, 502, 503, 504}
MAX_PREFIX_LENGTH = 7
MULTI_SEPARATOR = " | "
APPLICANT_ROLE = "1"  # contacts[].role des Antragstellers (Annahme, Code-Liste offen)


class GronosApiError(RuntimeError):
    pass


def records(payload: Any) -> list[dict]:
    """Datensätze aus einer API-Antwort (Liste, OData-Hülle oder Einzelobjekt)."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("value", "results", "d", "items", "data"):
            if key in payload:
                return records(payload[key])
        if "objectId" in payload:
            return [payload]
    return []


# Signatur des HTTP-Aufrufs: (method, url, headers, body) -> (status, body). In
# Tests durch eine Attrappe ersetzt.
Transport = Callable[[str, str, dict, bytes | None], tuple[int, bytes]]


def urllib_transport(timeout: float = 150.0) -> Transport:
    # Im Cluster ohne Proxy (getestet 27.10.), deshalb ProxyHandler({}).
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, bytes]:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with opener.open(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log.warning("GRONOS-Aufruf fehlgeschlagen: %s", exc)
            return 0, b""

    return call


@dataclass
class GronosClient:
    base_url: str
    client_id: str
    client_secret: str
    transport: Transport = field(default_factory=urllib_transport)
    _token: str | None = None
    calls: int = 0

    def _fetch_token(self) -> str:
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        status, body = self.transport(
            "POST",
            self.base_url.rstrip("/") + TOKEN_PATH,
            {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
            b"grant_type=client_credentials",
        )
        if status != 200:
            raise GronosApiError(f"Token-Abruf fehlgeschlagen (HTTP {status})")
        return json.loads(body)["access_token"]

    def get(self, params: dict[str, str]) -> tuple[int, bytes]:
        url = self.base_url.rstrip("/") + REQUEST_PATH + "?" + urllib.parse.urlencode(params)
        for attempt in range(2):
            if self._token is None:
                self._token = self._fetch_token()
            self.calls += 1
            status, body = self.transport(
                "GET", url, {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}, None
            )
            if status == 401 and attempt == 0:
                self._token = None
                continue
            return status, body
        return status, body

    def list_requests(self, prefixes: Iterable[str]) -> dict[str, dict]:
        """Alle Anträge der Liste, eindeutig je objectId."""
        by_id: dict[str, dict] = {}
        todo = list(prefixes)
        while todo:
            prefix = todo.pop(0)
            status, body = self.get({"companyId": prefix + "*"})
            if status in GATEWAY_ERRORS:
                if len(prefix) >= MAX_PREFIX_LENGTH:
                    raise GronosApiError(f"companyId={prefix}* liefert HTTP {status} und ist nicht weiter teilbar")
                todo[:0] = [prefix + d for d in "0123456789"]
                continue
            if status != 200:
                raise GronosApiError(f"Liste companyId={prefix}*: HTTP {status}")
            for rec in records(json.loads(body or b"[]")) if body.strip() else []:
                if rec.get("objectId"):
                    by_id.setdefault(rec["objectId"], rec)
        return by_id

    def detail(self, object_id: str, company_id: str | None) -> dict:
        """Detail eines Antrags; zuerst mit der eigenen companyId, sonst ``1*``."""
        filters = [f"{company_id}*"] if company_id else []
        filters.append("1*")
        for company_filter in filters:
            status, body = self.get({"id": object_id, "companyId": company_filter})
            if status != 200:
                raise GronosApiError(f"Detail {object_id}: HTTP {status}")
            found = [r for r in records(json.loads(body)) if r.get("objectId") == object_id] if body.strip() else []
            if found:
                return found[0]
        raise GronosApiError(f"Detail {object_id}: kein Datensatz in der Antwort")


def is_newer(listed: dict, known_updated_at: str | None) -> bool:
    """Antrag aus der Liste abrufen? Neu oder ``updatedAt`` neuer als in Bronze."""
    if known_updated_at is None:
        return True
    return (listed.get("updatedAt") or "") > known_updated_at


# --------------------------------------------------------------------------- #
# Ableitung Bronze (Content-JSON) → Silver
# --------------------------------------------------------------------------- #
def _clean(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _float(value: Any) -> float | None:
    value = _clean(value)
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _datetime(value: Any) -> str | None:
    """ISO-Zeitstempel der API → 'YYYY-MM-DD HH:MM:SS.ffffff' (wie die übrigen Spalten)."""
    value = _clean(value)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    value = _clean(value)
    if value is None:
        return None
    return str(value).lower() in ("true", "1", "x", "yes", "ja")


def _distinct(values: Iterable[Any]) -> str | None:
    seen: list[str] = []
    for v in values:
        v = _clean(v)
        if v is not None and str(v) not in seen:
            seen.append(str(v))
    return MULTI_SEPARATOR.join(seen) or None


def _location_text(loc: dict) -> str | None:
    if _clean(loc.get("displayName")):
        return _clean(loc["displayName"])
    a = loc.get("address") or {}
    street = " ".join(p for p in (_clean(a.get("street")), _clean(a.get("streetNumber"))) if p)
    town = " ".join(p for p in (_clean(a.get("postalCode")), _clean(a.get("municipality"))) if p)
    return ", ".join(p for p in (street, town) if p) or None


def applicant(content: dict) -> dict | None:
    contacts = [c for c in content.get("contacts") or [] if isinstance(c, dict)]
    for c in contacts:
        if str(c.get("role")) == APPLICANT_ROLE:
            return c
    return contacts[0] if contacts else None


REQUEST_VALUE_COLUMNS = [
    "GronosObjectID", "RequestStatus", "NextActor", "ProjectPhase", "DsoContacted", "DsoResponse",
    "SubstationLocation", "GenerationTechnology", "Substation50Hertz", "maxP", "CommissioningDate",
    "Latitude", "Longitude", "SwitchCount", "DocumentURL", "id_gronos_old", "id_gronos_new",
    "RequestComment", "SourceUpdatedAt",
]


def derive_request(content: dict) -> dict:
    """Silver-Werte von GridConnectionRequests (ohne ID, CustomerID, BT, timestamp)."""
    stages = [s for s in content.get("expansionStageConnections") or [] if isinstance(s, dict)]
    locations = [loc for loc in content.get("locations") or [] if isinstance(loc, dict)]
    documents = [d for d in content.get("documents") or [] if isinstance(d, dict)]

    capacities = [c for c in (_float(s.get("capacity")) for s in stages) if c is not None]
    starts = sorted(d for d in (_datetime(s.get("startDate")) for s in stages) if d)
    # Technologie: expansionStageGroup, sonst connectionType (Code-Liste offen, siehe Mapping-Doku)
    technology = _distinct(s.get("expansionStageGroup") for s in stages) or _distinct(
        s.get("connectionType") for s in stages
    )
    coordinate = (locations[0].get("coordinate") or {}) if locations else {}
    friendly = _clean(content.get("friendlyId"))
    try:
        friendly_id = int(str(friendly)) if friendly is not None else None
    except ValueError:
        friendly_id = None

    return {
        "GronosObjectID": _clean(content.get("objectId")),
        "RequestStatus": _clean(str(content["status"])) if content.get("status") is not None else None,
        "NextActor": _clean(str(content["nextActor"])) if content.get("nextActor") is not None else None,
        "ProjectPhase": _clean(content.get("projectPhase")),
        "DsoContacted": _bool(content.get("dsoContacted")),
        "DsoResponse": _clean(str(content["dsoResponse"])) if content.get("dsoResponse") is not None else None,
        "SubstationLocation": _distinct(_location_text(loc) for loc in locations),
        "GenerationTechnology": technology,
        "Substation50Hertz": None,  # keine Quelle in der API
        "maxP": sum(capacities) if capacities else None,
        "CommissioningDate": starts[0] if starts else None,
        "Latitude": _float(coordinate.get("latitude")),
        "Longitude": _float(coordinate.get("longitude")),
        "SwitchCount": None,  # keine Quelle in der API
        "DocumentURL": _distinct(d.get("documentFileName") for d in documents),  # nur Dateinamen
        "id_gronos_old": _clean(content.get("projectName")),
        "id_gronos_new": friendly_id,
        "RequestComment": _clean(content.get("projectDescription")),
        "SourceUpdatedAt": _datetime(content.get("updatedAt")),
    }


def derive_customer(content: dict) -> dict:
    """Silver-Werte von GridConnectionCustomers (ohne ID)."""
    contact = applicant(content) or {}
    company = contact.get("companyInfo") or {}
    person = " ".join(p for p in (_clean(contact.get("firstName")), _clean(contact.get("lastName"))) if p)
    email = _clean(contact.get("email"))
    company_id = _clean(content.get("companyId")) or _clean(company.get("partyId"))
    return {
        "CompanyID": str(company_id) if company_id is not None else None,
        "CustomerName": _clean(company.get("legalName")),
        "CustomerContactPerson": person or None,
        "CustomerContactPersonEmail": email.lower() if email else None,
        "VatNumber": _clean(company.get("vatNumber")),
    }


def fetch_delta(
    client: GronosClient, prefixes: Iterable[str], known: dict[str, str]
) -> tuple[list[dict], dict[str, int]]:
    """Liste → Delta gegen ``known`` (objectId → updatedAt in Bronze) → Details."""
    started = time.monotonic()
    listed = client.list_requests(prefixes)
    todo = [rec for oid, rec in listed.items() if is_newer(rec, known.get(oid))]
    details = [client.detail(rec["objectId"], _clean(str(rec.get("companyId") or "")) or None) for rec in todo]
    stats = {
        "listed": len(listed),
        "changed": len(todo),
        "api_calls": client.calls,
        "seconds": round(time.monotonic() - started, 1),
    }
    return details, stats
