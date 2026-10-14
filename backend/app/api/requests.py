from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import GridConnectionCustomer as Customer
from app.models import GridConnectionRequest as Request
from app.queries import (
    MULTI_SEPARATOR,
    RequestFilters,
    data_as_of,
    latest_condition,
    status_order,
)
from app.schemas import (
    AggregateItem,
    AggregateResult,
    CustomerOut,
    RequestOut,
    RequestPage,
    RequestWithCustomerOut,
)

router = APIRouter(prefix="/api/v1/grid-connection-requests", tags=["grid-connection-requests"])

SortField = Literal[
    "id_gronos_new",
    "id_gronos_old",
    "request_status",
    "generation_technology",
    "max_p",
    "substation_50hertz",
    "customer_name",
    "timestamp",
]
_SORT_COLUMNS = {
    "id_gronos_new": Request.id_gronos_new,
    "id_gronos_old": Request.id_gronos_old,
    "generation_technology": Request.GenerationTechnology,
    "max_p": Request.maxP,
    "substation_50hertz": Request.Substation50Hertz,
    "customer_name": Customer.CustomerName,
    "timestamp": Request.timestamp,
}
GroupBy = Literal["request_status", "generation_technology", "substation_50hertz", "customer_id"]
_GROUP_COLUMNS = {
    "request_status": Request.RequestStatus,
    "generation_technology": Request.GenerationTechnology,
    "substation_50hertz": Request.Substation50Hertz,
    "customer_id": Request.CustomerID,
}


def list_requests(
    session: Session,
    filters: RequestFilters,
    sort: SortField,
    order: Literal["asc", "desc"],
    limit: int,
    offset: int,
) -> RequestPage:
    total = session.scalar(filters.apply(select(func.count(Request.ID)))) or 0

    # request_status sorts by the configured process order, not alphabetically.
    column = status_order() if sort == "request_status" else _SORT_COLUMNS[sort]
    ordering = column.desc() if order == "desc" else column.asc()
    items = session.scalars(
        filters.apply(select(Request))
        # `IS NULL` first = missing values last in either direction (portable,
        # SQLite 3.26 in the cluster image has no NULLS LAST).
        .order_by(column.is_(None), ordering, Request.id_gronos_new, Request.timestamp, Request.ID)
        .limit(limit)
        .offset(offset)
    ).all()
    return RequestPage(
        items=[RequestOut.model_validate(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
        data_as_of=data_as_of(session),
    )


Sort = Annotated[SortField, Query()]
Order = Annotated[Literal["asc", "desc"], Query()]
Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0)]


@router.get("", response_model=RequestPage)
def get_requests(
    session: Annotated[Session, Depends(get_session)],
    filters: Annotated[RequestFilters, Depends()],
    sort: Sort = "id_gronos_new",
    order: Order = "asc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> RequestPage:
    """Grid connection requests; by default the newest entry per id_gronos_new."""
    return list_requests(session, filters, sort, order, limit, offset)


@router.get("/aggregate", response_model=AggregateResult)
def aggregate(
    session: Annotated[Session, Depends(get_session)],
    filters: Annotated[RequestFilters, Depends()],
    group_by: Annotated[GroupBy, Query()],
    split_multi: Annotated[
        bool,
        Query(
            description="Only for group_by=generation_technology: 'A | B' counts once for A "
            "and once for B, max_p is split evenly between them"
        ),
    ] = False,
) -> AggregateResult:
    """count and sum_max_p (MW, missing max_p counts as 0) per group, same filters as the list."""
    if split_multi and group_by != "generation_technology":
        raise HTTPException(
            status_code=422, detail="split_multi gibt es nur für group_by=generation_technology"
        )
    column = _GROUP_COLUMNS[group_by]
    total = session.scalar(filters.apply(select(func.count(Request.ID)))) or 0

    if split_multi:
        counts: dict[str | None, int] = defaultdict(int)
        sums: dict[str | None, float] = defaultdict(float)
        for value, max_p in session.execute(filters.apply(select(column, Request.maxP))):
            parts = [p.strip() for p in value.split(MULTI_SEPARATOR.strip())] if value else [None]
            parts = [p for p in parts if p != ""] or [None]
            for part in parts:
                counts[part] += 1
                sums[part] += (max_p or 0.0) / len(parts)
        rows = [(key, counts[key], sums[key]) for key in counts]
    else:
        rows = session.execute(
            filters.apply(
                select(column, func.count(Request.ID), func.coalesce(func.sum(Request.maxP), 0.0))
            ).group_by(column)
        ).all()

    items = sorted(
        (AggregateItem(key=k, count=c, sum_max_p=round(float(s), 6)) for k, c, s in rows),
        key=lambda i: (-i.count, i.key is None, i.key or ""),
    )
    return AggregateResult(
        group_by=group_by,
        split_multi=split_multi,
        total=total,
        items=items,
        data_as_of=data_as_of(session),
    )


@router.get(
    "/{id_gronos_new}",
    response_model=RequestWithCustomerOut,
    response_model_exclude_unset=True,
)
def get_request(
    id_gronos_new: int,
    session: Annotated[Session, Depends(get_session)],
    expand: Annotated[list[Literal["customer"]] | None, Query()] = None,
):
    """Current state (newest entry) of one ticket; expand=customer embeds the customer."""
    request = session.scalars(
        select(Request).where(Request.id_gronos_new == id_gronos_new, latest_condition())
    ).first()
    if request is None:
        raise HTTPException(status_code=404, detail="Netzanschlussanfrage nicht gefunden")
    body = RequestOut.model_validate(request).model_dump(mode="json")
    if expand and "customer" in expand:
        customer = request.customer
        body["customer"] = CustomerOut.model_validate(customer).model_dump(mode="json") if customer else None
    return JSONResponse(body)
