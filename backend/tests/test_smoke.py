"""
Tests fumée — vérifient que l'API upload-based répond correctement.
Lancement : `pytest tests/test_smoke.py -v` depuis le dossier backend.
"""
import io
import struct

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _make_minimal_dicom_bytes() -> bytes:
    """
    Construit un blob de bytes minimal qui passe la validation `is_dicom_bytes`
    (préambule 128 octets + marqueur 'DICM') mais qui n'a pas de tags valides.
    pydicom.dcmread renverra des métadonnées vides — c'est OK, l'endpoint
    accepte ces fichiers et utilise des valeurs par défaut.
    """
    return b"\x00" * 128 + b"DICM" + b"\x00" * 100


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["version"]


def test_analyze_rejects_empty_upload():
    # FastAPI requiert au moins un fichier dans le multipart "files"
    r = client.post("/api/analyze", files=[])
    assert r.status_code in (400, 422)


def test_analyze_rejects_non_dicom_files():
    fake_pdf = b"%PDF-1.4 not a dicom file"
    r = client.post(
        "/api/analyze",
        files=[("files", ("notes.pdf", fake_pdf, "application/pdf"))],
    )
    assert r.status_code == 400
    assert "DICOM" in r.json()["detail"]


def test_analyze_accepts_dicom_signature():
    blob = _make_minimal_dicom_bytes()
    r = client.post(
        "/api/analyze",
        files=[("files", ("slice_0001.dcm", blob, "application/dicom"))],
    )
    assert r.status_code == 200
    body = r.json()
    # On a un résultat structuré complet
    assert "stenosis_left" in body
    assert "stenosis_right" in body
    assert "complication_risk" in body
    assert "recommendation" in body
    assert body["recommendation"]["verdict"] in {
        "surgery",
        "monitoring",
        "contraindicated",
    }


def test_analyze_multiple_files():
    blob = _make_minimal_dicom_bytes()
    files = [
        ("files", (f"slice_{i:04d}.dcm", blob, "application/dicom"))
        for i in range(5)
    ]
    r = client.post("/api/analyze", files=files)
    assert r.status_code == 200
    body = r.json()
    # Les critical_slice_index doivent être dans [0, 5)
    assert 0 <= body["stenosis_left"]["critical_slice_index"] < 5


def test_reports_not_implemented():
    r = client.get("/api/reports/some-uuid")
    assert r.status_code == 501
