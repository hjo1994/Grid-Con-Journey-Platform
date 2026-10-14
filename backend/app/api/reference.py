from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import API_VERSION, status_catalogue
from app.db import get_session
from app.models import GridConnectionRequest as Request
from app.queries import data_as_of
from app.schemas import Meta, RequestStatusOut

router = APIRouter(prefix="/api/v1", tags=["reference"])


@router.get("/request-statuses", response_model=list[RequestStatusOut])
def request_statuses(session: Annotated[Session, Depends(get_session)]) -> list[RequestStatusOut]:
    """Configured statuses in process order (phase, in_process), followed by
    statuses that occur in the data but are not configured (order null)."""
    configured = [RequestStatusOut(**entry, configured=True) for entry in status_catalogue()]
    known = {s.name for s in configured}
    in_data = session.scalars(
        select(Request.RequestStatus)
        .where(Request.RequestStatus.is_not(None))
        .distinct()
        .order_by(Request.RequestStatus)
    ).all()
    unknown = [
        RequestStatusOut(name=name, order=None, phase=None, in_process=False, configured=False)
        for name in in_data
        if name not in known
    ]
    return configured + unknown


@router.get("/meta", response_model=Meta)
def meta(session: Annotated[Session, Depends(get_session)]) -> Meta:
    return Meta(api_version=API_VERSION, data_as_of=data_as_of(session))
