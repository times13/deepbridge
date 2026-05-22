"""
Test fumée — vérifie que tous les endpoints mockés répondent correctement.
Lancement : `pytest tests/test_smoke.py -v` depuis le dossier backend.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert "version" in body


def test_list_patients():
    r = client.get("/api/patients")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 3
    assert body[0]["id"].startswith("PATIENT_")


def test_get_patient_detail():
    r = client.get("/api/patients/PATIENT_001")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "PATIENT_001"
    assert "features" in body
    assert "slices" in body
    assert len(body["slices"]) == body["slice_count"]


def test_get_patient_404():
    r = client.get("/api/patients/UNKNOWN")
    assert r.status_code == 404


def test_analyze():
    r = client.post("/api/patients/PATIENT_001/analyze")
    assert r.status_code == 200
    body = r.json()
    assert body["patient_id"] == "PATIENT_001"
    assert 0 <= body["stenosis_left"]["nascet_percent"] <= 100
    assert 0 <= body["stenosis_right"]["nascet_percent"] <= 100
    assert 0 <= body["complication_risk"]["probability"] <= 1
    assert body["recommendation"]["verdict"] in {"surgery", "monitoring", "contraindicated"}


def test_analyze_404():
    r = client.post("/api/patients/UNKNOWN/analyze")
    assert r.status_code == 404


def test_slice_not_implemented():
    r = client.get("/api/patients/PATIENT_001/slices/0")
    assert r.status_code == 501
