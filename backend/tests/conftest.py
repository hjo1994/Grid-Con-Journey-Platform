import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.main import get_app
from app.models import Base, GridConnectionCustomer, GridConnectionRequest

T1 = datetime.datetime(2026, 10, 1, 8, 0, 0)
T2 = datetime.datetime(2026, 10, 2, 8, 0, 0)

CUSTOMER_A = "00000000-0000-0000-0000-00000000000a"
CUSTOMER_B = "00000000-0000-0000-0000-00000000000b"


def _request(id_, ticket, project, status, tech, max_p, ts, customer=CUSTOMER_A, substation=None):
    return GridConnectionRequest(
        ID=id_, id_gronos_new=ticket, id_gronos_old=project, RequestStatus=status,
        GenerationTechnology=tech, maxP=max_p, timestamp=ts, CustomerID=customer,
        Substation50Hertz=substation,
    )


@pytest.fixture()
def db_path(tmp_path):
    """Synthetic data, no real customers:

    ticket 100 has two entries (old: Offen, new: Eingestellt), so the current
    state differs from the history; 101 has two technologies; 103 has an
    unconfigured status and no max_p.
    """
    path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add_all(
            [
                GridConnectionCustomer(ID=CUSTOMER_A, CustomerName="Solar 100% GmbH",
                                       CustomerContactPerson="Anna", CustomerContactPersonEmail="a@example.invalid"),
                GridConnectionCustomer(ID=CUSTOMER_B, CustomerName="Wind_Park AG",
                                       CustomerContactPerson="Ben", CustomerContactPersonEmail=None),
            ]
        )
        s.flush()
        s.add_all(
            [
                _request("r100-old", 100, "Projekt-0100", "Offen", "Photovoltaik", 100.0, T1, substation="UW Nord"),
                _request("r100-new", 100, "Projekt-0100", "Eingestellt", "Photovoltaik", 120.0, T2, substation="UW Nord"),
                _request("r101", 101, "Projekt-0101", "Netzanschlussantrag eingegangen", "Batterie | Photovoltaik", 50.0, T1),
                _request("r102", 102, "Projekt-0102", "Standortanfrage eingegangen", "Wind Onshore", 30.0, T1,
                         customer=CUSTOMER_B, substation="UW Süd"),
                _request("r103", 103, "Projekt-0103", "Neuer Status", "Windkraft", None, T1, customer=CUSTOMER_B),
            ]
        )
        s.commit()
    engine.dispose()
    return path


@pytest.fixture()
def client(db_path):
    return TestClient(get_app(db_path))
