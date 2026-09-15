from fastapi.testclient import TestClient

from backend.app.db import connection as db
from backend.app.main import create_app


def test_health_and_schema(library):
    with TestClient(create_app()) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_vec_roundtrip(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init_db(conn)

    dim = db.SPACES["image_a"]
    table = db.vec_table("image_a")
    conn.execute(f"INSERT INTO {table}(rowid, embedding) VALUES (?, ?)",
                 (1, db.serialize([0.0] * dim)))
    conn.execute(f"INSERT INTO {table}(rowid, embedding) VALUES (?, ?)",
                 (2, db.serialize([1.0] * dim)))
    conn.commit()

    rows = db.knn(conn, "image_a", [0.0] * dim, limit=5)
    assert [r["rowid"] for r in rows] == [1, 2]

    rows = db.knn(conn, "image_a", [0.0] * dim, limit=5, restrict_to=[2])
    assert [r["rowid"] for r in rows] == [2]

    assert db.knn(conn, "image_a", [0.0] * dim, limit=5, restrict_to=[]) == []


def test_unknown_space_is_rejected(library):
    import pytest

    # Назва простору підставляється в SQL, тож довільний рядок приймати не можна.
    with pytest.raises(KeyError):
        db.vec_table("image'; DROP TABLE items; --")
