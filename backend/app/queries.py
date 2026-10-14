"""Shared query building for GridConnectionRequests.

Silver is versioned (append-only): a ticket (``id_gronos_new``) can have
several entries, the newest ``timestamp`` is the current state. By default
every endpoint works on that current state; ``versions=all`` uses every
entry. Filters always apply *after* picking the current state, so filtering
for a status never returns an outdated entry of a ticket.
"""

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Query
from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.config import status_catalogue
from app.models import GridConnectionCustomer as Customer
from app.models import GridConnectionRequest as Request

MULTI_SEPARATOR = " | "

Versions = Literal["latest", "all"]


def escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def latest_condition():
    """Request.ID is the newest entry of its ticket (ties: highest ID).

    Window function instead of NULLS LAST tricks: available from SQLite 3.25
    (cluster image: 3.26) and in MySQL 8. Entries without id_gronos_new are
    not grouped with each other.
    """
    ranked = select(
        Request.ID,
        func.row_number()
        .over(
            partition_by=Request.id_gronos_new,
            order_by=(Request.timestamp.desc(), Request.ID.desc()),
        )
        .label("rn"),
    ).subquery()
    newest = select(ranked.c.ID).where(ranked.c.rn == 1)
    return or_(Request.id_gronos_new.is_(None), Request.ID.in_(newest))


def technology_matches(values: list[str]):
    """GenerationTechnology contains one of ``values`` as a whole element of
    the " | "-separated list (exact match, so "Wind" does not hit "Wind Onshore")."""
    padded = MULTI_SEPARATOR + Request.GenerationTechnology + MULTI_SEPARATOR
    return or_(
        *(
            padded.like(f"%{escape_like(MULTI_SEPARATOR + v + MULTI_SEPARATOR)}%", escape="\\")
            for v in values
        )
    )


@dataclass
class BaseRequestFilters:
    """Request filters without customer_id (used below a customer path)."""

    q: Annotated[
        str | None,
        Query(description="Substring in id_gronos_new, id_gronos_old or customer name"),
    ] = None
    request_status: Annotated[list[str] | None, Query(description="Repeatable")] = None
    exclude_status: Annotated[list[str] | None, Query(description="Repeatable")] = None
    generation_technology: Annotated[
        list[str] | None,
        Query(description="Repeatable; matches single values inside 'A | B'"),
    ] = None
    substation_50hertz: Annotated[list[str] | None, Query(description="Repeatable")] = None
    versions: Annotated[
        Versions, Query(description="latest = newest entry per id_gronos_new, all = every entry")
    ] = "latest"

    customer_id = None  # set by RequestFilters or by the customer route

    def conditions(self) -> list:
        conditions = []
        if self.versions == "latest":
            conditions.append(latest_condition())
        if self.request_status:
            conditions.append(Request.RequestStatus.in_(self.request_status))
        if self.exclude_status:
            conditions.append(
                or_(Request.RequestStatus.is_(None), Request.RequestStatus.not_in(self.exclude_status))
            )
        if self.generation_technology:
            conditions.append(technology_matches(self.generation_technology))
        if self.customer_id:
            conditions.append(Request.CustomerID.in_(self.customer_id))
        if self.substation_50hertz:
            conditions.append(Request.Substation50Hertz.in_(self.substation_50hertz))
        if self.q and self.q.strip():
            pattern = f"%{escape_like(self.q.strip())}%"
            conditions.append(
                or_(
                    cast(Request.id_gronos_new, String).like(pattern, escape="\\"),
                    Request.id_gronos_old.ilike(pattern, escape="\\"),
                    Customer.CustomerName.ilike(pattern, escape="\\"),
                )
            )
        return conditions

    def apply(self, stmt: Select) -> Select:
        return stmt.outerjoin(Customer, Request.CustomerID == Customer.ID).where(*self.conditions())


@dataclass
class RequestFilters(BaseRequestFilters):
    """Query parameters shared by the list and the aggregate endpoint."""

    customer_id: Annotated[list[str] | None, Query(description="Repeatable")] = None


def status_order():
    """Configured process order as a sortable expression; unknown statuses last."""
    whens = {entry["name"]: entry["order"] for entry in status_catalogue()}
    return case(whens, value=Request.RequestStatus, else_=len(whens) + 1)


def data_as_of(session: Session):
    """Newest timestamp in Silver = the data state of the whole database."""
    return session.scalar(select(func.max(Request.timestamp)))
