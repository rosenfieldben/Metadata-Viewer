"""End-to-end: upload golden fixtures through the FastAPI test client and
validate the full response shape.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    # Context manager form runs the lifespan, exercising the exiftool check.
    with TestClient(app) as c:
        yield c


def upload(client, path, name=None):
    with open(path, "rb") as fh:
        return client.post("/api/inspect",
                           files={"file": (name or path.name, fh)})


def test_png_full_response_shape(client, fixtures_dir):
    resp = upload(client, fixtures_dir / "golden.png")
    assert resp.status_code == 200
    data = resp.json()

    assert set(data) == {"file_info", "groups", "flags", "gps", "raw", "errors"}

    info = data["file_info"]
    assert info["name"] == "golden.png"
    assert info["size"] > 0
    assert len(info["md5"]) == 32 and len(info["sha256"]) == 64
    assert info["detected_mime"] == "image/png"
    assert info["claimed_type"] == "png"
    assert info["type_mismatch"] is False

    group_names = [g["name"] for g in data["groups"]]
    assert "GPS" in group_names
    for group in data["groups"]:
        for entry in group["entries"]:
            assert set(entry) == {"key", "value"}

    labels = [f["label"] for f in data["flags"]]
    assert any("GPS" in l for l in labels)
    assert any("Personal names" in l for l in labels)
    assert any("Software or device" in l for l in labels)

    lat, lon = data["gps"]
    assert abs(lat - 37.7749) < 1e-4 and abs(lon + 122.4194) < 1e-4

    assert data["raw"]["File:FileType"] == "PNG"
    assert data["errors"] == []


def test_docx_supplement_and_company_flag(client, fixtures_dir):
    resp = upload(client, fixtures_dir / "golden.docx")
    data = resp.json()
    labels = [f["label"] for f in data["flags"]]
    assert any("Company or organization" in l for l in labels)
    assert any("Personal names" in l for l in labels)
    assert any("Revision history" in l for l in labels)


def test_pdf_pypdf_supplement_merged(client, fixtures_dir):
    resp = upload(client, fixtures_dir / "golden.pdf")
    data = resp.json()
    pypdf_group = next((g for g in data["groups"] if g["name"] == "pypdf"), None)
    assert pypdf_group is not None
    keys = {e["key"] for e in pypdf_group["entries"]}
    assert "PageCount" in keys or "Encrypted" in keys


def test_renamed_png_triggers_mismatch(client, fixtures_dir):
    resp = upload(client, fixtures_dir / "renamed-png.docx")
    data = resp.json()
    assert data["file_info"]["type_mismatch"] is True
    assert any("does not match" in f["label"] and f["severity"] == "warning"
               for f in data["flags"])


def test_unparseable_file_still_returns_basics(client, tmp_path):
    weird = tmp_path / "garbage.zzz"
    weird.write_bytes(b"\x00\x01\x02\x03 not any known format \xff\xfe")
    resp = upload(client, weird)
    assert resp.status_code == 200
    data = resp.json()
    assert data["file_info"]["sha256"]
    assert data["file_info"]["size"] == weird.stat().st_size


def test_oversize_upload_rejected_with_413(client, fixtures_dir, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module, "MAX_UPLOAD_BYTES", 100)
    resp = upload(client, fixtures_dir / "golden.docx")
    assert resp.status_code == 413
    assert "METADATA_INSPECTOR_MAX_BYTES" in resp.json()["detail"]
