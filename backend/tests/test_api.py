"""API smoke test for the annotation CRUD routes (main.py).

No real video: we point the app's store at a temp DB and seed a Video row directly, then
drive the HTTP surface the frontend canvas will use.
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from rallytator import main
from rallytator.store import Store


@pytest.fixture()
def client(tmp_path):
    main._store = Store(str(tmp_path / "api.db"))
    main._reader = None
    main._video_id = None
    with TestClient(main.app) as c:
        yield c
    main._store.close()


@pytest.fixture()
def video_id(client):
    return main._store.create_video("/v/clip.mp4", 1920, 1080, 30.0, 600)


def test_track_and_detection_lifecycle(client, video_id):
    r = client.post(f"/videos/{video_id}/tracks", json={"type": "ball"})
    assert r.status_code == 201
    tid = r.json()["id"]

    geom = {"pt": [100.0, 200.0], "vis": "visible"}
    r = client.put(f"/tracks/{tid}/detections/331",
                    json={"geom": geom, "source": "cotracker", "flight_index": 0})
    assert r.status_code == 200
    assert r.json()["geom"] == geom and r.json()["edited"] is False

    # upsert same (track, frame) as a human edit — still one detection
    r = client.put(f"/tracks/{tid}/detections/331",
                   json={"geom": {"pt": [101.0, 200.0], "vis": "visible"},
                         "source": "human", "edited": True, "model_geom": geom})
    assert r.status_code == 200
    got = client.get(f"/tracks/{tid}/detections/331").json()
    assert got["edited"] is True and got["model_geom"] == geom
    assert len(client.get(f"/tracks/{tid}/detections").json()) == 1


def test_frame_read_path(client, video_id):
    p = client.post(f"/videos/{video_id}/tracks", json={"type": "player"}).json()["id"]
    b = client.post(f"/videos/{video_id}/tracks", json={"type": "ball"}).json()["id"]
    client.put(f"/tracks/{p}/detections/42", json={"geom": {"kpts": []}, "source": "yolo"})
    client.put(f"/tracks/{b}/detections/42",
               json={"geom": {"pt": [1.0, 1.0], "vis": "visible"}, "source": "cotracker"})
    r = client.get(f"/videos/{video_id}/frames/42/detections")
    assert r.status_code == 200
    assert {d["track_type"] for d in r.json()} == {"player", "ball"}


def test_mask_base64_roundtrip(client, video_id):
    tid = client.post(f"/videos/{video_id}/tracks", json={"type": "player"}).json()["id"]
    did = client.put(f"/tracks/{tid}/detections/7",
                     json={"geom": {"kpts": []}, "source": "sam3"}).json()["id"]
    payload = base64.b64encode(b"\x01\x02\x03").decode()
    assert client.put(f"/detections/{did}/mask",
                      json={"rle": payload, "height": 1080, "width": 1920}).status_code == 204
    got = client.get(f"/detections/{did}/mask").json()
    assert got["rle"] == payload and got["width"] == 1920


def test_delete_track_cascades(client, video_id):
    tid = client.post(f"/videos/{video_id}/tracks", json={"type": "ball"}).json()["id"]
    client.put(f"/tracks/{tid}/detections/1",
               json={"geom": {"pt": [0.0, 0.0], "vis": "visible"}, "source": "cotracker"})
    assert client.delete(f"/tracks/{tid}").status_code == 204
    assert client.get(f"/videos/{video_id}/frames/1/detections").json() == []


def test_bad_track_type_rejected(client, video_id):
    assert client.post(f"/videos/{video_id}/tracks", json={"type": "banana"}).status_code == 422


def test_missing_detection_is_404(client, video_id):
    tid = client.post(f"/videos/{video_id}/tracks", json={"type": "ball"}).json()["id"]
    assert client.get(f"/tracks/{tid}/detections/999").status_code == 404
