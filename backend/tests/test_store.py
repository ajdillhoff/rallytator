"""Store CRUD + invariants (docs/data-model.md). In-memory-ish: temp file per test."""

from __future__ import annotations

import sqlite3

import pytest

from rallytator.store import Store


@pytest.fixture()
def store(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    yield s
    s.close()


@pytest.fixture()
def video(store):
    return store.create_video("/v/clip.mp4", 1920, 1080, 30.0, 600)


def test_video_roundtrip_and_lookup_by_path(store):
    vid = store.create_video("/v/a.mp4", 1920, 1080, 30.0, 600)
    v = store.get_video(vid)
    assert v["width"] == 1920 and v["n_frames"] == 600
    assert store.get_video_by_path("/v/a.mp4")["id"] == vid
    assert store.get_video_by_path("/v/missing.mp4") is None
    assert [x["id"] for x in store.list_videos()] == [vid]


def test_track_create_list_and_type_check(store, video):
    t = store.create_track(video, "player", annotator="alex")
    assert [x["id"] for x in store.list_tracks(video)] == [t]
    assert store.list_tracks(video)[0]["annotator"] == "alex"
    with pytest.raises(sqlite3.IntegrityError):
        store.create_track(video, "banana")  # CHECK constraint


def test_detection_upsert_is_idempotent_on_track_frame(store, video):
    t = store.create_track(video, "ball")
    geom1 = {"pt": [10.0, 20.0], "vis": "visible"}
    d1 = store.upsert_detection(t, 100, geom1, "cotracker", flight_index=0)
    geom2 = {"pt": [11.0, 21.0], "vis": "visible"}
    d2 = store.upsert_detection(t, 100, geom2, "human", edited=True,
                                model_geom=geom1, flight_index=0)
    assert d1 == d2  # same row, not a second insert
    got = store.get_detection(t, 100)
    assert got["geom"] == geom2 and got["edited"] is True
    assert got["source"] == "human" and got["model_geom"] == geom1
    assert len(store.track_detections(t)) == 1


def test_geom_json_roundtrips_as_object(store, video):
    t = store.create_track(video, "player")
    geom = {"kpts": [[1.0, 2.0, "visible"], [3.0, 4.0, "occluded"]]}
    store.upsert_detection(t, 5, geom, "yolo", model_confidence=0.9)
    got = store.get_detection(t, 5)
    assert got["geom"] == geom
    assert got["model_geom"] is None and got["edited"] is False


def test_frame_read_path_spans_tracks_and_tags_type(store, video):
    p = store.create_track(video, "player")
    b = store.create_track(video, "ball")
    store.upsert_detection(p, 42, {"kpts": []}, "yolo")
    store.upsert_detection(b, 42, {"pt": [1.0, 1.0], "vis": "visible"}, "cotracker")
    store.upsert_detection(b, 43, {"pt": [2.0, 2.0], "vis": "visible"}, "cotracker")
    at42 = store.detections_in_frame(video, 42)
    assert {d["track_type"] for d in at42} == {"player", "ball"}
    assert len(at42) == 2
    assert len(store.detections_in_frame(video, 43)) == 1


def test_track_detections_ordered_by_frame(store, video):
    t = store.create_track(video, "ball")
    for f in (30, 10, 20):
        store.upsert_detection(t, f, {"pt": [0.0, 0.0], "vis": "visible"}, "cotracker")
    assert [d["frame"] for d in store.track_detections(t)] == [10, 20, 30]


def test_delete_track_cascades_to_detections(store, video):
    t = store.create_track(video, "ball")
    store.upsert_detection(t, 1, {"pt": [0.0, 0.0], "vis": "visible"}, "cotracker")
    store.delete_track(t)
    assert store.get_detection(t, 1) is None
    assert store.list_tracks(video) == []


def test_mask_set_get_and_upsert(store, video):
    t = store.create_track(video, "player")
    d = store.upsert_detection(t, 7, {"kpts": []}, "sam3")
    store.set_mask(d, b"\x01\x02\x03", 1080, 1920)
    m = store.get_mask(d)
    assert m["rle"] == b"\x01\x02\x03" and m["height"] == 1080 and m["width"] == 1920
    store.set_mask(d, b"\x09", 1080, 1920)  # overwrite
    assert store.get_mask(d)["rle"] == b"\x09"


def test_mask_cascades_on_detection_delete(store, video):
    t = store.create_track(video, "player")
    d = store.upsert_detection(t, 7, {"kpts": []}, "sam3")
    store.set_mask(d, b"\x01", 1080, 1920)
    store.delete_detection(d)
    assert store.get_mask(d) is None
