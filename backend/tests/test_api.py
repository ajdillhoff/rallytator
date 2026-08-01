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
from rallytator.worker import process_job
from tests.test_models import FakeRegistry, _read_frame, _read_span


def _fake_runner(job, emit):
    """Run jobs inline with a fake Registry so the API needs no subprocess/GPU."""
    return process_job(job, FakeRegistry(), emit, _read_frame, _read_span)


@pytest.fixture()
def client(tmp_path):
    main._store = Store(str(tmp_path / "api.db"))
    main._reader = None
    main._video_id = None
    main._jobs_mgr = None
    main._local_runner = _fake_runner
    with TestClient(main.app) as c:
        yield c
    main._store.close()
    if main._jobs_mgr is not None:
        main._jobs_mgr.stop()
    main._jobs_mgr = None
    main._local_runner = None


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


def test_bbox_geom_roundtrip(client, video_id):
    tid = client.post(f"/videos/{video_id}/tracks", json={"type": "player"}).json()["id"]
    geom = {"bbox": [10.0, 20.0, 100.0, 200.0], "kpts": [[15.0, 25.0, "visible"]]}
    client.put(f"/tracks/{tid}/detections/5", json={"geom": geom, "source": "rfdetr"})
    got = client.get(f"/tracks/{tid}/detections/5").json()
    assert got["geom"] == geom and got["source"] == "rfdetr"


def test_mask_png_and_has_mask(client, video_id):
    import io

    import numpy as np
    from PIL import Image

    from rallytator import masks

    tid = client.post(f"/videos/{video_id}/tracks", json={"type": "player"}).json()["id"]
    did = client.put(f"/tracks/{tid}/detections/9",
                     json={"geom": {"kpts": []}, "source": "sam3"}).json()["id"]
    m = np.zeros((12, 16), dtype=bool)
    m[3:7, 4:9] = True
    payload = base64.b64encode(masks.rle_encode(m)).decode()
    client.put(f"/detections/{did}/mask", json={"rle": payload, "height": 12, "width": 16})

    png = client.get(f"/detections/{did}/mask.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    arr = np.asarray(Image.open(io.BytesIO(png.content)))
    assert arr.shape == (12, 16, 4) and bool(arr[4, 5, 3])  # alpha set inside the mask

    # frame read path advertises mask presence
    dets = client.get(f"/videos/{video_id}/frames/9/detections").json()
    assert dets[0]["has_mask"] is True


def test_rfdetr_detect_endpoint(client, video_id):
    tid = client.post(f"/videos/{video_id}/tracks", json={"type": "player"}).json()["id"]
    r = client.post(f"/tracks/{tid}/detect?frame=4")
    assert r.status_code == 200
    d = r.json()
    assert d["source"] == "rfdetr" and d["geom"]["bbox"] == [10.0, 20.0, 30.0, 40.0]


def test_sam_segment_requires_prompt(client, video_id):
    tid = client.post(f"/videos/{video_id}/tracks", json={"type": "player"}).json()["id"]
    assert client.post(f"/tracks/{tid}/segment?frame=0&model=sam3").status_code == 400


def test_sam_segment_writes_mask(client, video_id):
    tid = client.post(f"/videos/{video_id}/tracks", json={"type": "player"}).json()["id"]
    client.put(f"/tracks/{tid}/detections/0",
               json={"geom": {"bbox": [1, 1, 5, 5], "kpts": []}, "source": "human"})
    r = client.post(f"/tracks/{tid}/segment?frame=0&model=sam3")
    assert r.status_code == 200
    dets = client.get(f"/videos/{video_id}/frames/0/detections").json()
    assert dets[0]["has_mask"] is True


def test_rfdetr_keypoints_endpoint(client, video_id):
    tid = client.post(f"/videos/{video_id}/tracks", json={"type": "player"}).json()["id"]
    r = client.post(f"/tracks/{tid}/keypoints?frame=2")
    assert r.status_code == 200 and len(r.json()["geom"]["kpts"]) == 17


def test_track_job_persists_masks(client, video_id):
    tid = client.post(f"/videos/{video_id}/tracks", json={"type": "player"}).json()["id"]
    client.put(f"/tracks/{tid}/detections/10",
               json={"geom": {"bbox": [2, 2, 4, 4], "kpts": []}, "source": "human"})
    jid = client.post(f"/tracks/{tid}/track",
                      json={"start_frame": 10, "end_frame": 13}).json()["job_id"]

    # poll: each request pumps the event loop, letting the job + persist task advance
    for _ in range(100):
        st = client.get(f"/jobs/{jid}").json()
        if st["state"] == "done":
            break
    assert st["state"] == "done"

    for _ in range(100):
        dets = client.get(f"/videos/{video_id}/frames/12/detections").json()
        if dets and dets[0]["has_mask"]:
            break
    assert dets and dets[0]["has_mask"] is True and dets[0]["source"] == "sam3"
