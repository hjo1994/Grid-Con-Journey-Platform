from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.requests import Limit, Offset, Order, Sort, list_requests
from app.db import get_session
from app.models import GridConnectionCustomer as Customer
from app.queries import BaseRequestFilters, escape_like
from app.schemas import CustomerOut, CustomerPage, RequestPage

router = APIRouter(prefix="/api/v1/grid-connection-customers", tags=["grid-connection-customers"])

_SORT_COLUMNS = {
    "customer_name": Customer.CustomerName,
    "customer_contact_person": Customer.CustomerContactPerson,
}


@router.get("", response_model=CustomerPage)
def get_customers(
    session: Annotated[Session, Depends(get_session)],
    q: Annotated[str | None, Query(description="Substring in name, contact person or e-mail")] = None,
    sort: Literal["customer_name", "customer_contact_person"] = "customer_name",
    order: Order = "asc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> CustomerPage:
    conditions = []
    if q and q.strip():
        pattern = f"%{escape_like(q.strip())}%"
        conditions.append(
            or_(
                Customer.CustomerName.ilike(pattern, escape="\\"),
                Customer.CustomerContactPerson.ilike(pattern, escape="\\"),
                Customer.CustomerContactPersonEmail.ilike(pattern, escape="\\"),
            )
        )
    total = session.scalar(select(func.count(Customer.ID)).where(*conditions)) or 0
    column = _SORT_COLUMNS[sort]
    ordering = column.desc() if order == "desc" else column.asc()
    items = session.scalars(
        select(Customer)
        .where(*conditions)
        .order_by(column.is_(None), ordering, Customer.ID)
        .limit(limit)
        .offset(offset)
    ).all()
    return CustomerPage(
        items=[CustomerOut.model_validate(c) for c in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def _existing_customer(session: Session, customer_id: str) -> Customer:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Kunde nicht gefunden")
    return customer


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: str, session: Annotated[Session, Depends(get_session)]) -> CustomerOut:
    return CustomerOut.model_validate(_existing_customer(session, customer_id))


@router.get("/{customer_id}/grid-connection-requests", response_model=RequestPage)
def get_customer_requests(
    customer_id: str,
    session: Annotated[Session, Depends(get_session)],
    filters: Annotated[BaseRequestFilters, Depends()],
    sort: Sort = "id_gronos_new",
    order: Order = "asc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> RequestPage:
    """Same as GET /grid-connection-requests, restricted to this customer."""
    _existing_customer(session, customer_id)
    filters.customer_id = [customer_id]
    return list_requests(session, filters, sort, order, limit, offset)
