"""GronosExports.Content (JSON of one request) -> Silver values.

Mapping as in `solution documentation/LogicalDataModel.drawio` (PROPOSAL v3,
02.11.2026). Rules:

* empty strings / whitespace -> NULL, codes stay codes until the code lists
  are available,
* several list entries (locations, stage groups, documents) are joined with
  " | " in API order, as the Excel export did,
* ``maxP`` = sum of ``expansionStageConnections[].capacity`` (MW),
  ``CommissioningDate`` = earliest ``startDate``,
* coordinates from the first location,
* the customer is the company of the request (``companyId``); contact person
  is the contact of that company, preferring role "1" (applicant,
  assumption until the code list is confirmed).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SEPARATOR = " | "
APPLICANT_ROLE = "1"

REQUEST_VALUE_COLUMNS = [
    "GronosObjectID",
    "id_gronos_new",
    "id_gronos_old",
    "RequestStatus",
    "NextActor",
    "ProjectPhase",
    "DsoContacted",
    "DsoResponse",
    "RequestComment",
    "GenerationTechnology",
    "maxP",
    "CommissioningDate",
    "SubstationLocation",
    "Latitude",
    "Longitude",
    "Substation50Hertz",
    "SwitchCount",
    "DocumentURL",
    "SourceUpdatedAt",
]
CUSTOMER_VALUE_COLUMNS = ["CompanyID", "CustomerName", "CustomerContactPerson", "CustomerContactPersonEmail", "VatNumber"]


class InvalidContent(ValueError):
    """Content cannot be turned into a Silver record (no JSON object / no objectId)."""


@dataclass
class SilverRecord:
    request: dict[str, Any]
    customer: dict[str, Any] | None


# --------------------------------------------------------------------------- #
# value helpers
# --------------------------------------------------------------------------- #
def text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    s = str(value).strip()
    return s or None


def code(value: Any) -> str | None:
    """Codes as text; booleans/ints are kept readable ("1", "true")."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return text(value)


def boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    s = text(value)
    if s is None:
        return None
    if s.lower() in {"true", "1", "x", "yes"}:
        return True
    if s.lower() in {"false", "0", "no"}:
        return False
    return None


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = text(value)
    if s is None:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def integer(value: Any) -> int | None:
    s = text(value)
    return int(s) if s is not None and s.isdigit() else None


def timestamp(value: Any) -> str | None:
    """ISO date/time from the API -> 'YYYY-MM-DD HH:MM:SS.ffffff' (UTC, naive)."""
    s = text(value)
    if s is None:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(sep=" ", timespec="microseconds")


def joined(values: list[str | None], unique: bool = False) -> str | None:
    out: list[str] = []
    for v in values:
        if v is None or (unique and v in out):
            continue
        out.append(v)
    return SEPARATOR.join(out) or None


def _list(rec: dict, key: str) -> list[dict]:
    value = rec.get(key)
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


# --------------------------------------------------------------------------- #
# parts
# --------------------------------------------------------------------------- #
def location_label(loc: dict) -> str | None:
    name = text(loc.get("displayName"))
    if name:
        return name
    addr = loc.get("address") if isinstance(loc.get("address"), dict) else {}
    street = " ".join(p for p in (text(addr.get("street")), text(addr.get("streetNumber"))) if p)
    city = " ".join(p for p in (text(addr.get("postalCode")), text(addr.get("municipality"))) if p)
    return ", ".join(p for p in (street, city) if p) or None


def applicant_contact(rec: dict, company_id: str | None) -> dict | None:
    contacts = _list(rec, "contacts")

    def company_of(c: dict) -> str | None:
        info = c.get("companyInfo") if isinstance(c.get("companyInfo"), dict) else {}
        return text(info.get("partyId"))

    same_company = [c for c in contacts if company_id is None or company_of(c) == company_id]
    for pool in (same_company, contacts):
        for c in pool:
            if code(c.get("role")) == APPLICANT_ROLE:
                return c
        if pool:
            return pool[0]
    return None


def customer_values(rec: dict) -> dict[str, Any] | None:
    company_id = text(rec.get("companyId"))
    contact = applicant_contact(rec, company_id)
    info = (contact or {}).get("companyInfo")
    info = info if isinstance(info, dict) else {}
    company_id = company_id or text(info.get("partyId"))
    if company_id is None:
        return None
    first, last = text((contact or {}).get("firstName")), text((contact or {}).get("lastName"))
    email = text((contact or {}).get("email"))
    return {
        "CompanyID": company_id,
        "CustomerName": text(info.get("legalName")),
        "CustomerContactPerson": " ".join(p for p in (first, last) if p) or None,
        "CustomerContactPersonEmail": email.lower() if email else None,
        "VatNumber": text(info.get("vatNumber")),
    }


def request_values(rec: dict) -> dict[str, Any]:
    stages = _list(rec, "expansionStageConnections")
    locations = _list(rec, "locations")
    documents = _list(rec, "documents")

    capacities = [c for c in (number(s.get("capacity")) for s in stages) if c is not None]
    start_dates = [d for d in (timestamp(s.get("startDate")) for s in stages) if d is not None]
    groups = [code(s.get("expansionStageGroup")) for s in stages]
    if not any(groups):
        groups = [code(s.get("connectionType")) for s in stages]

    coord = (locations[0].get("coordinate") if locations else None) or {}
    coord = coord if isinstance(coord, dict) else {}

    return {
        "GronosObjectID": text(rec.get("objectId")),
        "id_gronos_new": integer(rec.get("friendlyId")),
        "id_gronos_old": text(rec.get("projectName")),
        "RequestStatus": code(rec.get("status")),
        "NextActor": code(rec.get("nextActor")),
        "ProjectPhase": code(rec.get("projectPhase")),
        "DsoContacted": boolean(rec.get("dsoContacted")),
        "DsoResponse": code(rec.get("dsoResponse")),
        "RequestComment": text(rec.get("projectDescription")),
        "GenerationTechnology": joined(groups, unique=True),
        "maxP": sum(capacities) if capacities else None,
        "CommissioningDate": min(start_dates) if start_dates else None,
        "SubstationLocation": joined([location_label(loc) for loc in locations]),
        "Latitude": number(coord.get("latitude")),
        "Longitude": number(coord.get("longitude")),
        "Substation50Hertz": None,  # no API source
        "SwitchCount": None,  # no API source
        "DocumentURL": joined([text(d.get("documentFileName")) for d in documents]),
        "SourceUpdatedAt": timestamp(rec.get("updatedAt")),
    }


def to_silver(content: str) -> SilverRecord:
    try:
        rec = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise InvalidContent(f"invalid JSON: {exc}") from exc
    if not isinstance(rec, dict):
        raise InvalidContent("JSON is not an object")
    request = request_values(rec)
    if request["GronosObjectID"] is None:
        raise InvalidContent("objectId missing")
    return SilverRecord(request=request, customer=customer_values(rec))
