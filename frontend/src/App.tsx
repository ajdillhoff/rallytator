import { useCallback, useEffect, useRef, useState } from "react";
import {
  createTrack, deleteTrack, fetchFrameBitmap, fetchMaskBitmap, getVideoInfo,
  getFrameDetections, listTracks, upsertDetection,
  runDetect, runSegment, runKeypoints, startTrack, watchJob, type JobStatus,
} from "./api";
import { draftToGeom, geomToDraft } from "./geom";
import { PixiStage, type MaskItem, type RenderItem } from "./pixiStage";
import { LABEL_SCHEMAS, TRACK_TYPES } from "./schemas";
import { applyTemplate } from "./templates";
import type {
  Bbox, Detection, Draft, Track, TrackType, VideoInfo, Visibility,
} from "./types";
import { emptyDraft } from "./types";

const VIS_CYCLE: Visibility[] = ["visible", "occluded", "out-of-frame"];
const nextVis = (v: Visibility): Visibility =>
  VIS_CYCLE[(VIS_CYCLE.indexOf(v) + 1) % VIS_CYCLE.length]!;
const VIS_CHAR: Record<Visibility, string> = { visible: "v", occluded: "o", "out-of-frame": "x" };
const hex = (c: number) => `#${c.toString(16).padStart(6, "0")}`;

// Component-id keys for the ephemeral visibility/lock sets.
const cid = {
  track: (id: number) => `track:${id}`,
  bbox: (id: number) => `bbox:${id}`,
  mask: (id: number) => `mask:${id}`,
  kpt: (id: number, i: number) => `kpt:${id}:${i}`,
};
// Hierarchical resolvers: a track hides/locks all of its parts; a hidden bbox hides kpts.
const trackHidden = (h: Set<string>, id: number) => h.has(cid.track(id));
const bboxHidden = (h: Set<string>, id: number) => trackHidden(h, id) || h.has(cid.bbox(id));
const maskHidden = (h: Set<string>, id: number) => trackHidden(h, id) || h.has(cid.mask(id));
const kptHidden = (h: Set<string>, id: number, i: number) => bboxHidden(h, id) || h.has(cid.kpt(id, i));
const trackLocked = (l: Set<string>, id: number) => l.has(cid.track(id));
const bboxLocked = (l: Set<string>, id: number) => trackLocked(l, id) || l.has(cid.bbox(id));
const kptLocked = (l: Set<string>, id: number, i: number) => trackLocked(l, id) || l.has(cid.kpt(id, i));

const corners = ([x, y, w, h]: Bbox): [number, number][] =>
  [[x, y], [x + w, y], [x + w, y + h], [x, y + h]];

type Drag =
  | { kind: "point"; index: number }
  | { kind: "handle"; corner: number; fixed: [number, number] }
  | { kind: "bbox-draw"; start: [number, number] }
  | { kind: "pan"; last: [number, number] };

type Mode = "idle" | "draw-bbox";

export default function App() {
  const hostRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<PixiStage | null>(null);

  const [info, setInfo] = useState<VideoInfo | null>(null);
  const [ready, setReady] = useState(false);
  const [frame, setFrame] = useState(0);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft());
  const [selected, setSelected] = useState<number | null>(null);
  const [newType, setNewType] = useState<TrackType>("player");
  const [mode, setMode] = useState<Mode>("idle");
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [locked, setLocked] = useState<Set<string>>(new Set());
  const [kptsOpen, setKptsOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Latest state for the stable imperative Pixi pointer callbacks.
  const s = useRef({ activeId, draft, frame, tracks, newType, mode, locked });
  s.current = { activeId, draft, frame, tracks, newType, mode, locked };
  const dragging = useRef<Drag | null>(null);
  const dirty = useRef(false);
  const maskCache = useRef(new Map<number, ImageBitmap>());

  const videoId = info?.video_id ?? null;
  const activeTrack = tracks.find((t) => t.id === activeId) ?? null;
  const activeType = activeTrack?.type ?? newType;
  const schema = LABEL_SCHEMAS[activeType];

  const save = useCallback(async (d: Draft) => {
    const { activeId: id, frame: f, tracks: ts } = s.current;
    if (id == null) return;
    const t = ts.find((x) => x.id === id);
    if (!t) return;
    try {
      const det = await upsertDetection(id, f, draftToGeom(t.type, d));
      setDetections((prev) => {
        const prevDet = prev.find((x) => x.track_id === id);
        return [...prev.filter((x) => x.track_id !== id),
          { ...det, track_type: t.type, has_mask: prevDet?.has_mask }];
      });
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  // ---- init Pixi stage once ------------------------------------------------
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const stage = new PixiStage();
    let alive = true;
    stage.init(host).then(() => {
      if (!alive) return;
      stageRef.current = stage;
      setReady(true);
    });

    stage.onPointerDown = (info) => {
      const cur = s.current;
      const id = cur.activeId;
      const type = id != null ? cur.tracks.find((t) => t.id === id)?.type : undefined;

      if (cur.mode === "draw-bbox" && id != null && type && type !== "ball") {
        if (bboxLocked(cur.locked, id)) return;
        dragging.current = { kind: "bbox-draw", start: [info.x, info.y] };
        dirty.current = true;
        setDraft((d) => ({ ...d, bbox: [info.x, info.y, 0, 0] }));
        return;
      }
      if (id == null || !type) {
        dragging.current = { kind: "pan", last: [info.sx, info.sy] };
        return;
      }
      if (info.hit?.kind === "point") {
        if (kptLocked(cur.locked, id, info.hit.index)) return;
        dragging.current = { kind: "point", index: info.hit.index };
        setSelected(info.hit.index);
        return;
      }
      if (info.hit?.kind === "handle") {
        if (bboxLocked(cur.locked, id) || !cur.draft.bbox) return;
        const fixed = corners(cur.draft.bbox)[(info.hit.corner + 2) % 4]!;
        dragging.current = { kind: "handle", corner: info.hit.corner, fixed };
        return;
      }
      if (type === "ball") {
        if (trackLocked(cur.locked, id)) return;
        dragging.current = { kind: "point", index: 0 };
        dirty.current = true;
        setDraft({ bbox: null, points: [{ x: info.x, y: info.y, vis: "visible" }] });
        setSelected(0);
        return;
      }
      dragging.current = { kind: "pan", last: [info.sx, info.sy] }; // pose, empty -> pan
    };

    stage.onPointerMove = (info) => {
      const d = dragging.current;
      if (!d) return;
      if (d.kind === "pan") {
        stageRef.current?.panBy(info.sx - d.last[0], info.sy - d.last[1]);
        d.last = [info.sx, info.sy];
        return;
      }
      dirty.current = true;
      if (d.kind === "point") {
        setDraft((prev) => ({
          ...prev,
          points: prev.points.map((p, j) => (j === d.index ? { ...p, x: info.x, y: info.y } : p)),
        }));
      } else if (d.kind === "handle" || d.kind === "bbox-draw") {
        const [ax, ay] = d.kind === "handle" ? d.fixed : d.start;
        setDraft((prev) => ({
          ...prev,
          bbox: [Math.min(ax, info.x), Math.min(ay, info.y),
            Math.abs(info.x - ax), Math.abs(info.y - ay)],
        }));
      }
    };

    stage.onPointerUp = () => {
      const d = dragging.current;
      dragging.current = null;
      if (!d || d.kind === "pan") { dirty.current = false; return; }
      if (d.kind === "bbox-draw") {
        const cur = s.current;
        const box = cur.draft.bbox;
        const id = cur.activeId;
        const type = id != null ? cur.tracks.find((t) => t.id === id)?.type : undefined;
        setMode("idle");
        if (box && box[2] > 3 && box[3] > 3 && id != null && type) {
          const nd: Draft = { bbox: box, points: applyTemplate(type, box) };
          setDraft(nd);
          void save(nd);
        }
        dirty.current = false;
        return;
      }
      if (dirty.current) void save(s.current.draft);
      dirty.current = false;
    };

    return () => {
      alive = false;
      stageRef.current = null;
      stage.destroy();
    };
  }, [save]);

  // ---- load video info + tracks -------------------------------------------
  useEffect(() => {
    getVideoInfo()
      .then((v) => {
        setInfo(v);
        if (v.video_id != null) listTracks(v.video_id).then(setTracks);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  // ---- frame change: fetch bitmap + detections ----------------------------
  useEffect(() => {
    if (!ready || videoId == null) return;
    let alive = true;
    fetchFrameBitmap(frame)
      .then((bmp) => alive && stageRef.current?.setFrame(bmp))
      .catch((e) => setErr(String(e)));
    getFrameDetections(videoId, frame)
      .then((dets) => {
        if (!alive) return;
        setDetections(dets);
        const mine = dets.find((d) => d.track_id === s.current.activeId);
        setDraft(mine ? geomToDraft(mine.geom) : emptyDraft());
        setSelected(null);
      })
      .catch((e) => setErr(String(e)));
    return () => { alive = false; };
  }, [frame, videoId, ready]);

  // ---- re-derive draft when the active track changes ----------------------
  useEffect(() => {
    const mine = detections.find((d) => d.track_id === activeId);
    setDraft(mine ? geomToDraft(mine.geom) : emptyDraft());
    setSelected(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  // ---- render vector overlay whenever the model changes -------------------
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const items: RenderItem[] = [];
    for (const t of tracks) {
      if (trackHidden(hidden, t.id)) continue;
      const sch = LABEL_SCHEMAS[t.type];
      const isActive = t.id === activeId;
      let dr: Draft | null;
      if (isActive) dr = draft;
      else {
        const det = detections.find((d) => d.track_id === t.id);
        dr = det ? geomToDraft(det.geom) : null;
      }
      if (!dr) continue;
      items.push({
        points: dr.points,
        pointVisible: dr.points.map((_, i) => !kptHidden(hidden, t.id, i)),
        edges: sch.edges,
        color: sch.color,
        active: isActive,
        bbox: dr.bbox && !bboxHidden(hidden, t.id) ? dr.bbox : null,
      });
    }
    stage.render(items, selected);
  }, [tracks, detections, draft, activeId, selected, hidden]);

  // ---- render mask layer --------------------------------------------------
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    let alive = true;
    (async () => {
      const out: MaskItem[] = [];
      for (const d of detections) {
        if (!d.has_mask || !d.track_type || maskHidden(hidden, d.track_id)) continue;
        let bmp = maskCache.current.get(d.id);
        if (!bmp) {
          try { bmp = await fetchMaskBitmap(d.id); maskCache.current.set(d.id, bmp); }
          catch { continue; }
        }
        out.push({ id: d.id, bitmap: bmp, color: LABEL_SCHEMAS[d.track_type].color, alpha: 0.4 });
      }
      if (alive) stage.setMasks(out);
    })();
    return () => { alive = false; };
  }, [detections, hidden, ready]);

  const step = useCallback((delta: number) => {
    setFrame((f) => Math.max(0, Math.min((info?.n_frames ?? 1) - 1, f + delta)));
  }, [info]);

  const addTrack = useCallback(async () => {
    if (videoId == null) return;
    const type = s.current.newType;
    const t = await createTrack(videoId, type);
    setTracks((prev) => [...prev, t]);
    setActiveId(t.id);
    setDraft(emptyDraft());
    setSelected(null);
    setMode(type === "ball" ? "idle" : "draw-bbox"); // bbox-first for pose tracks
  }, [videoId]);

  const removeActive = useCallback(async () => {
    const id = s.current.activeId;
    if (id == null) return;
    await deleteTrack(id);
    setTracks((prev) => prev.filter((t) => t.id !== id));
    setDetections((prev) => prev.filter((d) => d.track_id !== id));
    setActiveId(null);
    setDraft(emptyDraft());
    setMode("idle");
  }, []);

  const cyclePointVis = useCallback((i: number) => {
    const id = s.current.activeId;
    if (id == null || kptLocked(s.current.locked, id, i)) return;
    setDraft((prev) => {
      const next = { ...prev, points: prev.points.map((p, j) => (j === i ? { ...p, vis: nextVis(p.vis) } : p)) };
      void save(next);
      return next;
    });
  }, [save]);

  const toggleSet = (set: (fn: (p: Set<string>) => Set<string>) => void) => (key: string) =>
    set((prev) => {
      const n = new Set(prev);
      n.has(key) ? n.delete(key) : n.add(key);
      return n;
    });
  const toggleHidden = toggleSet(setHidden);
  const toggleLocked = toggleSet(setLocked);

  // ---- model assist -------------------------------------------------------
  const reloadActive = useCallback(async () => {
    if (videoId == null) return;
    const f = s.current.frame;
    const dets = await getFrameDetections(videoId, f);
    setDetections(dets);
    const mine = dets.find((d) => d.track_id === s.current.activeId);
    if (mine) setDraft(geomToDraft(mine.geom));
  }, [videoId]);

  const runOp = useCallback(async (label: string, op: () => Promise<unknown>) => {
    if (s.current.activeId == null) return;
    setBusy(label);
    try {
      maskCache.current.clear();
      await op();
      await reloadActive();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  }, [reloadActive]);

  const doTrack = useCallback(() => {
    const id = s.current.activeId;
    if (id == null) return;
    const guess = Math.min((info?.n_frames ?? 1) - 1, s.current.frame + 30);
    const endStr = window.prompt("SAM3 track until end frame:", String(guess));
    if (endStr == null) return;
    const end = Number(endStr);
    if (!Number.isFinite(end)) return;
    setBusy("track");
    setJob({ job_id: "", state: "queued", progress: 0 });
    startTrack(id, s.current.frame, end)
      .then(({ job_id }) => {
        const stop = watchJob(job_id, (st) => {
          setJob(st);
          if (st.state === "done" || st.state === "error") {
            stop();
            setBusy(null);
            if (st.state === "error") setErr(st.error ?? "track failed");
            maskCache.current.clear();
            void reloadActive();
          }
        });
      })
      .catch((e) => { setErr(String(e)); setBusy(null); });
  }, [info, reloadActive]);

  // ---- keybinds ------------------------------------------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const big = e.shiftKey ? 10 : 1;
      switch (e.key) {
        case "ArrowRight": case "l": e.preventDefault(); step(big); break;
        case "ArrowLeft": case "h": e.preventDefault(); step(-big); break;
        case "n": e.preventDefault(); void addTrack(); break;
        case "d": e.preventDefault(); void removeActive(); break;
        case "b": {
          e.preventDefault();
          if (activeType !== "ball" && activeId != null) setMode((m) => (m === "draw-bbox" ? "idle" : "draw-bbox"));
          break;
        }
        case "1": setNewType("player"); break;
        case "2": setNewType("racquet"); break;
        case "3": setNewType("ball"); break;
        case "4": setNewType("court"); break;
        case "Tab": {
          e.preventDefault();
          const ts = s.current.tracks;
          if (!ts.length) break;
          const i = ts.findIndex((t) => t.id === s.current.activeId);
          setActiveId(ts[(i + 1) % ts.length]!.id);
          break;
        }
        case "v": if (selected != null) cyclePointVis(selected); break;
        case "Backspace": {
          e.preventDefault();
          if (activeId != null && trackLocked(locked, activeId)) break;
          setDraft((prev) => {
            const next = { ...prev, points: prev.points.slice(0, -1) };
            void save(next);
            return next;
          });
          setSelected(null);
          break;
        }
        case "Escape": setActiveId(null); setSelected(null); setMode("idle"); break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, addTrack, removeActive, save, selected, cyclePointVis, activeId, activeType, locked]);

  const hasDet = (id: number) => detections.some((d) => d.track_id === id);

  // small helpers for the toggle buttons on a card
  const eye = (key: string) => (
    <button className={`tgl ${hidden.has(key) ? "" : "on"}`} title="visibility"
            onClick={(e) => { e.stopPropagation(); toggleHidden(key); }}>👁</button>
  );
  const lock = (key: string) => (
    <button className={`tgl ${locked.has(key) ? "on" : ""}`} title="lock"
            onClick={(e) => { e.stopPropagation(); toggleLocked(key); }}>🔒</button>
  );

  return (
    <div className="app">
      <header>
        RallyTator · {info ? `${info.width}×${info.height} · ${info.fps.toFixed(0)}fps · ${info.n_frames}f` : "no video"}
        {mode === "draw-bbox" && <span className="mode"> · draw bbox</span>}
        {err && <span className="err"> · {err}</span>}
      </header>
      <div ref={hostRef} className="stage" />
      <aside>
        <div className="row"><b>frame</b><span>{frame} / {(info?.n_frames ?? 1) - 1}</span></div>
        <input type="range" min={0} max={Math.max(0, (info?.n_frames ?? 1) - 1)}
               value={frame} onChange={(e) => setFrame(Number(e.target.value))} />
        <div className="row"><b>new type</b>
          <span>{TRACK_TYPES.map((t, i) => (
            <button key={t} className={t === newType ? "on" : ""} onClick={() => setNewType(t)}>
              {i + 1}:{t}
            </button>
          ))}</span>
        </div>
        <div className="row"><b>active</b>
          <span>{activeTrack ? `#${activeTrack.id} ${activeTrack.type} — ${draft.points.length}/${schema.points.length} pts` : "none"}</span>
        </div>

        <h2>tracks</h2>
        <div className="cards">
          {tracks.map((t) => {
            const isActive = t.id === activeId;
            const sch = LABEL_SCHEMAS[t.type];
            return (
              <div key={t.id} className={`card ${isActive ? "active" : ""}`}>
                <div className="card-head" onClick={() => setActiveId(t.id)}
                     style={{ borderLeftColor: hex(sch.color) }}>
                  <span className="chip" style={{ background: hex(sch.color) }} />
                  <span className="grow">#{t.id} {t.type}{hasDet(t.id) ? " ●" : ""}</span>
                  {eye(cid.track(t.id))}
                  {lock(cid.track(t.id))}
                </div>

                {isActive && (
                  <div className="card-body">
                    {t.type !== "ball" && (
                      <>
                        <div className="comp-row"><span className="grow">bbox</span>{eye(cid.bbox(t.id))}{lock(cid.bbox(t.id))}</div>
                        <div className="comp-row"><span className="grow">mask</span>{eye(cid.mask(t.id))}{lock(cid.mask(t.id))}</div>
                      </>
                    )}

                    <div className="actions">
                      {t.type === "player" && <>
                        <button disabled={!!busy} onClick={() => void runOp("detect", () => runDetect(t.id, frame))}>detect</button>
                        <button disabled={!!busy} onClick={() => void runOp("seg", () => runSegment(t.id, frame, "rfdetr"))}>seg·rf</button>
                        <button disabled={!!busy} onClick={() => void runOp("pose", () => runKeypoints(t.id, frame))}>pose</button>
                      </>}
                      {t.type !== "ball" && <>
                        <button disabled={!!busy} onClick={() => void runOp("seg", () => runSegment(t.id, frame, "sam3"))}>seg·sam3</button>
                        <button disabled={!!busy} onClick={doTrack}>track</button>
                      </>}
                    </div>
                    {busy === "track" && job && (
                      <div className="prog" title={job.detail ?? job.state}>
                        <div style={{ width: `${Math.round((job.progress ?? 0) * 100)}%` }} />
                      </div>
                    )}

                    {t.type !== "ball" && (
                      <>
                        <div className="kpt-head" onClick={() => setKptsOpen((o) => !o)}>
                          {kptsOpen ? "▾" : "▸"} keypoints ({sch.points.length})
                        </div>
                        {kptsOpen && (
                          <div className="kpt-list">
                            {sch.points.map((name, i) => (
                              <div key={i} className={`kpt-card ${selected === i ? "sel" : ""}`}
                                   onClick={() => setSelected(i)}>
                                <span className="grow">{i} {name}</span>
                                <button className="vis-badge" title="cycle visibility"
                                        onClick={(e) => { e.stopPropagation(); cyclePointVis(i); }}>
                                  {draft.points[i] ? VIS_CHAR[draft.points[i]!.vis] : "-"}
                                </button>
                                {eye(cid.kpt(t.id, i))}
                                {lock(cid.kpt(t.id, i))}
                              </div>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <h2>keys</h2>
        <pre>
{`←/→  step ±1   (shift ±10)
n    new track (of new-type)
b    draw bbox for active track
1-4  set new-type
Tab  cycle active track
wheel  zoom to cursor
drag   pan (empty) / move point
v    cycle point visibility
Bksp undo last point
d    delete active track
Esc  deselect`}
        </pre>
      </aside>
    </div>
  );
}
