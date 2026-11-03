"""Demo-Datenbank für den lokalen Stack: läuft durch die echte GRONOS-Pipeline
(raw_to_bronze + bronze_to_silver) mit einer simulierten API. Nur synthetische
Daten, keine echten Anfragen, kein Netzwerkzugriff.

    python scripts/seed_demo_gronos.py data/db/grid_con_demo.db
"""
import json, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from grid_con_ingestion.gronos.client import GronosClient
from grid_con_ingestion.gronos.store import raw_to_bronze, bronze_to_silver

random.seed(7)
TECH = ["BESS", "PV", "WIND", "H2", "DC"]
TOWNS = [("Testort", 54.06, 12.33), ("Musterstadt", 53.55, 13.26), ("Beispielfeld", 52.39, 13.06),
         ("Probedorf", 51.34, 12.37), ("Neustadt", 52.97, 11.75)]
data = []
for i in range(14):
    town, lat, lon = TOWNS[i % 5]
    stages = [{"objectId": f"S{i}{k}", "startDate": f"202{7+k}-0{1+i%8}-01T00:00:00.000",
               "expansionStageGroup": TECH[(i + k) % 5] if i % 3 else TECH[i % 5],
               "connectionType": 1 + k, "capacity": random.choice([20, 50, 100, 150, 250, 300])}
              for k in range(1 + (i % 3 == 0))]
    company = f"10{25 + i % 4}{100 + i % 6:03d}"
    data.append({
        "objectId": f"DEMO{i:028d}",
        "friendlyId": str(4900 + i), "companyId": company, "status": str(1 + i % 5), "nextActor": str(i % 3),
        "dsoResponse": str(i % 2), "dsoContacted": i % 2 == 0, "projectName": f"Projekt-G{i:02d}",
        "projectDescription": "Synthetischer Testdatensatz" if i % 4 == 0 else "", "projectPhase": f"Z0{1 + i % 3}",
        "createdAt": "2026-07-24T06:31:52.704", "updatedAt": f"2026-10-{10 + i:02d}T08:00:00.000",
        "expansionStageConnections": stages,
        "locations": [{"objectId": f"L{i}", "coordinate": {"latitude": lat + i / 100, "longitude": lon + i / 100},
                       "displayName": "", "address": {"street": "Teststraße", "streetNumber": str(i + 1),
                                                      "postalCode": f"1{i:04d}", "municipality": town}}],
        "contacts": [{"objectId": f"C{i}", "role": 1, "firstName": "Person", "lastName": f"{company[-3:]}",
                      "email": f"person{company[-3:]}@example.invalid",
                      "companyInfo": {"partyId": company, "legalName": f"Unternehmen-{company[-3:]} GmbH",
                                      "vatNumber": f"DE000{company}"}}],
        "documents": [{"objectId": f"D{i}{k}", "documentFileName": n, "type": "1"}
                      for k, n in enumerate(["lageplan.pdf", "vollmacht.pdf", "datenblatt.pdf"][: i % 4])],
    })

class Resp:
    def __init__(s, code, body=None):
        s.status_code = code; s.text = json.dumps(body) if body is not None else ""; s.content = s.text.encode()
    def json(s): return json.loads(s.text)

class Fake(requests.Session):
    def post(s, *a, **k): return Resp(200, {"access_token": "t"})
    def get(s, url, params=None, **k):
        p = params["companyId"][:-1]
        if "id" in params: return Resp(200, [r for r in data if r["objectId"] == params["id"]])
        if len(p) < 4: return Resp(504)
        f = [r for r in data if r["companyId"].startswith(p)]
        return Resp(200, f + f)

db = Path(sys.argv[1])
if db.exists():
    sys.exit(f"{db} existiert bereits – bitte eine neue Datei angeben (keine Mischung mit echten Daten).")
c = GronosClient("https://fake.invalid", "id", "secret", session=Fake())
print(raw_to_bronze(c, db, ["1025", "1026", "1027", "1028"]).as_dict())
print(bronze_to_silver(db).as_dict())
# second pull: two requests change
data[1]["status"] = "5"; data[1]["updatedAt"] = "2026-11-01T09:00:00.000"
data[3]["dsoContacted"] = True; data[3]["updatedAt"] = "2026-11-01T10:00:00.000"
print(raw_to_bronze(c, db, ["1025", "1026", "1027", "1028"]).as_dict())
print(bronze_to_silver(db).as_dict())
