"""Client for the GRONOS ConnectionRequest API behind SAP API Management.

* OAuth2 client credentials: ``POST {base}/v1/api/OAuthService/GenerateToken``
  with Basic Auth (client id / secret) and ``grant_type=client_credentials``.
* List: ``GET {base}/http/CP1001/IF0058/ConnectionRequest?companyId=<prefix>*``.
  A plain ``*`` or short prefixes run into a gateway timeout, so the list is
  fetched per company-id prefix; a prefix that times out is split into its
  ten children (``1028`` -> ``10280`` … ``10289``) until ``max_prefix_length``.
* Detail: ``GET …/ConnectionRequest?id=<objectId>&companyId=<companyId>*``.

The list currently returns every request twice; :meth:`GronosClient.list_all`
removes duplicates by ``objectId``.

Tested from the cluster pod on 27.10.2026: the host is reachable without
proxy, so environment proxies are ignored unless ``use_env_proxy`` is set.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

import requests

# Child of "airflow.task": the lines land in the Airflow task log in every
# executor/logging setup; outside Airflow it is a normal logger.
log = logging.getLogger("airflow.task.gronos.client")

TOKEN_PATH = "/v1/api/OAuthService/GenerateToken"
REQUESTS_PATH = "/http/CP1001/IF0058/ConnectionRequest"
WILDCARD = "*"
GATEWAY_ERRORS = frozenset({502, 503, 504})


class GronosApiError(RuntimeError):
    """Any API answer we cannot use; fails the Airflow task."""


class _GatewayTimeout(Exception):
    """Prefix too broad for the gateway (502/503/504 or client timeout)."""


def parse_prefixes(spec: str) -> list[str]:
    """``"1000-1299, 2000"`` -> ``["1000", …, "1299", "2000"]`` (ranges keep the width)."""
    prefixes: list[str] = []
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        if "-" in part:
            start, end = (x.strip() for x in part.split("-", 1))
            if not (start.isdigit() and end.isdigit()) or int(end) < int(start):
                raise ValueError(f"Ungültiger Präfix-Bereich: {part!r}")
            width = len(start)
            prefixes += [str(n).zfill(width) for n in range(int(start), int(end) + 1)]
        elif part.isdigit():
            prefixes.append(part)
        else:
            raise ValueError(f"Ungültiges Präfix: {part!r}")
    return prefixes


def records(payload: Any) -> list[dict]:
    """Request records from a response body (plain list or wrapped list)."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("value", "results", "d", "items", "data"):
            if key in payload:
                return records(payload[key])
        if "objectId" in payload:
            return [payload]
        lists = [v for v in payload.values() if isinstance(v, list)]
        return records(lists[0]) if lists else []
    return []


@dataclass
class ListResult:
    records: list[dict]
    calls: int = 0
    duplicates: int = 0
    split_prefixes: list[str] = field(default_factory=list)


class GronosClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        *,
        timeout: float = 150.0,
        max_prefix_length: int = 7,
        use_env_proxy: bool = False,
        session: requests.Session | None = None,
    ):
        if not base_url:
            raise GronosApiError("GRONOS_API_BASE_URL ist nicht gesetzt")
        if not client_id or not client_secret:
            raise GronosApiError("GRONOS_API_CLIENT_ID / GRONOS_API_CLIENT_SECRET sind nicht gesetzt")
        self.base_url = base_url.rstrip("/")
        self._auth = (client_id, client_secret)
        self.timeout = timeout
        self.max_prefix_length = max_prefix_length
        self.session = session or requests.Session()
        self.session.trust_env = use_env_proxy
        self._token: str | None = None

    # ------------------------------------------------------------------ auth
    def _fetch_token(self) -> str:
        resp = self.session.post(
            self.base_url + TOKEN_PATH,
            auth=self._auth,
            data={"grant_type": "client_credentials"},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise GronosApiError(f"Token-Abruf fehlgeschlagen: HTTP {resp.status_code}")
        token = (resp.json() or {}).get("access_token")
        if not token:
            raise GronosApiError("Token-Antwort ohne access_token")
        return token

    def _get(self, params: dict[str, str]) -> requests.Response:
        """GET on the request endpoint; renews the token once on 401."""
        for attempt in (1, 2):
            if self._token is None:
                self._token = self._fetch_token()
            try:
                resp = self.session.get(
                    self.base_url + REQUESTS_PATH,
                    params=params,
                    headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
                    timeout=self.timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                raise _GatewayTimeout(str(exc)) from exc
            if resp.status_code == 401 and attempt == 1:
                self._token = None
                continue
            return resp
        raise GronosApiError("HTTP 401 auch nach neuem Token")  # pragma: no cover

    # ------------------------------------------------------------------ list
    def list_prefix(self, prefix: str) -> list[dict]:
        resp = self._get({"companyId": prefix + WILDCARD})
        if resp.status_code in GATEWAY_ERRORS:
            raise _GatewayTimeout(f"HTTP {resp.status_code}")
        if resp.status_code == 404:
            return []
        if resp.status_code != 200:
            raise GronosApiError(f"Liste companyId={prefix}{WILDCARD}: HTTP {resp.status_code}")
        if not resp.content.strip():
            return []
        return records(resp.json())

    def list_all(self, prefixes: Iterable[str]) -> ListResult:
        """All requests for the given company-id prefixes, unique by objectId."""
        result = ListResult(records=[])
        by_id: dict[str, dict] = {}
        pending = list(prefixes)
        while pending:
            prefix = pending.pop(0)
            result.calls += 1
            started = time.monotonic()
            log.info("Liste companyId=%s%s … (Aufruf %d, noch %d offen)", prefix, WILDCARD, result.calls, len(pending))
            try:
                found = self.list_prefix(prefix)
            except _GatewayTimeout as exc:
                if len(prefix) >= self.max_prefix_length:
                    raise GronosApiError(
                        f"companyId={prefix}{WILDCARD} liefert weiterhin {exc} – nicht weiter teilbar"
                    ) from exc
                log.info("companyId=%s%s: %s nach %.1f s – teile auf", prefix, WILDCARD, exc, time.monotonic() - started)
                result.split_prefixes.append(prefix)
                pending[:0] = [prefix + d for d in "0123456789"]
                continue
            log.info("Liste companyId=%s%s: %d Datensätze in %.1f s", prefix, WILDCARD, len(found), time.monotonic() - started)
            for rec in found:
                oid = rec.get("objectId")
                if not oid:
                    log.warning("Datensatz ohne objectId in companyId=%s%s ignoriert", prefix, WILDCARD)
                    continue
                if oid in by_id:
                    result.duplicates += 1
                    if (rec.get("updatedAt") or "") <= (by_id[oid].get("updatedAt") or ""):
                        continue
                by_id[oid] = rec
        result.records = list(by_id.values())
        return result

    # ---------------------------------------------------------------- detail
    def detail(self, object_id: str, company_id: str | None) -> dict:
        """Detail record of one request (taken from the response unchanged)."""
        company = (company_id or "") + WILDCARD
        try:
            resp = self._get({"id": object_id, "companyId": company})
        except _GatewayTimeout as exc:
            raise GronosApiError(f"Detail {object_id}: {exc}") from exc
        if resp.status_code != 200:
            raise GronosApiError(f"Detail {object_id}: HTTP {resp.status_code}")
        found = records(resp.json())
        match = [r for r in found if r.get("objectId") == object_id]
        if not match:
            raise GronosApiError(f"Detail {object_id}: Anfrage nicht in der Antwort enthalten")
        return match[0]
