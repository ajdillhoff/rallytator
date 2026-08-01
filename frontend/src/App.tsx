import { useCallback, useEffect, useRef, useState } from "react";
import {
  createTrack, deleteTrack, fetchFrameBitmap, getVideoInfo,
  getFrameDetections, listTracks, upsertDetection,
} from "./api";
import { geomToPoints, pointsToGeom } from "./geom";
import { PixiStage, type RenderItem } from "./pixiStage";
import { LABEL_SCHEMAS, TRACK_TYPES } from "./schemas";
import type { Detection, EditPoint, Track, TrackType, VideoInfo, Visibility } from "./types";

const VIS_CYCLE: Visibility[] = ["visible", "occluded", "out-of-frame"];
const nextVis = (v: Visibility): Visibility =>
  VIS_CYCLE[(VIS_CYCLE.indexOf(v) + 1) % VIS_CYCLE.length]!;

export default function App() {
  const hostRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<PixiStage | null>(null);

  const [info, setInfo] = useState<VideoInfo | null>(null);
  const [ready, setReady] = useState(false);
  const [frame, setFrame] = useState(0);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [draft, setDraft] = useState<EditPoint[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [newType, setNewType] = useState<TrackType>("player");
  const [err, setErr] = useState<string | null>(null);

  // Latest state for the stable imperative Pixi pointer callbacks.
  const s = useRef({ activeId, draft, frame, tracks, newType });
  s.current = { activeId, draft, frame, tracks, newType };
  const dragging = useRef<number | null>(null);
  const dirty = useRef(false);

  const videoId = info?.video_id ?? null;
  const activeTrack = tracks.find((t) => t.id === activeId) ?? null;
  const activeType = activeTrack?.type ?? newType;
  const schema = LABEL_SCHEMAS[activeType];

  const save = useCallback(async (points: EditPoint[]) => {
    const { activeId: id, frame: f, tracks: ts } = s.current;
    if (id == null) return;
    const t = ts.find((x) => x.id === id);
    if (!t) return;
    try {
      const det = await upsertDetection(id, f, pointsToGeom(t.type, points));
      setDetections((prev) => [
        ...prev.filter((d) => d.track_id !== id),
        { ...det, track_type: t.type },
      ]);
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

    stage.onPointerDown = ({ x, y, hit }) => {
      const cur = s.current;
      if (cur.activeId == null) return;
      const sch = LABEL_SCHEMAS[cur.tracks.find((t) => t.id === cur.activeId)?.type ?? cur.newType];
      if (hit != null) {
        dragging.current = hit;
        setSelected(hit);
      } else if (cur.draft.length < sch.points.length) {
        const pts = [...cur.draft, { x, y, vis: "visible" as Visibility }];
        dragging.current = pts.length - 1;
        dirty.current = true;
        setDraft(pts);
        setSelected(pts.length - 1);
      }
    };
    stage.onPointerMove = ({ x, y }) => {
      const i = dragging.current;
      if (i == null) return;
      dirty.current = true;
      setDraft((prev) => prev.map((p, j) => (j === i ? { ...p, x, y } : p)));
    };
    stage.onPointerUp = () => {
      if (dragging.current != null && dirty.current) void save(s.current.draft);
      dragging.current = null;
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
        setDraft(mine ? geomToPoints(mine.geom) : []);
        setSelected(null);
      })
      .catch((e) => setErr(String(e)));
    return () => { alive = false; };
  }, [frame, videoId, ready]);

  // ---- re-derive draft when the active track changes ----------------------
  useEffect(() => {
    const mine = detections.find((d) => d.track_id === activeId);
    setDraft(mine ? geomToPoints(mine.geom) : []);
    setSelected(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  // ---- render overlay whenever the model changes --------------------------
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const items: RenderItem[] = [];
    for (const t of tracks) {
      const sch = LABEL_SCHEMAS[t.type];
      if (t.id === activeId) {
        items.push({ points: draft, edges: sch.edges, color: sch.color, active: true });
      } else {
        const det = detections.find((d) => d.track_id === t.id);
        if (det) items.push({ points: geomToPoints(det.geom), edges: sch.edges, color: sch.color, active: false });
      }
    }
    stage.render(items, selected);
  }, [tracks, detections, draft, activeId, selected]);

  const step = useCallback((delta: number) => {
    setFrame((f) => {
      const max = (info?.n_frames ?? 1) - 1;
      return Math.max(0, Math.min(max, f + delta));
    });
  }, [info]);

  const addTrack = useCallback(async () => {
    if (videoId == null) return;
    const t = await createTrack(videoId, s.current.newType);
    setTracks((prev) => [...prev, t]);
    setActiveId(t.id);
    setDraft([]);
    setSelected(null);
  }, [videoId]);

  const removeActive = useCallback(async () => {
    const id = s.current.activeId;
    if (id == null) return;
    await deleteTrack(id);
    setTracks((prev) => prev.filter((t) => t.id !== id));
    setDetections((prev) => prev.filter((d) => d.track_id !== id));
    setActiveId(null);
    setDraft([]);
  }, []);

  // ---- keybinds ------------------------------------------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const big = e.shiftKey ? 10 : 1;
      switch (e.key) {
        case "ArrowRight": case "l": e.preventDefault(); step(big); break;
        case "ArrowLeft": case "h": e.preventDefault(); step(-big); break;
        case "n": e.preventDefault(); void addTrack(); break;
        case "d": e.preventDefault(); void removeActive(); break;
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
        case "v": {
          const i = selected;
          if (i == null) break;
          setDraft((prev) => {
            const next = prev.map((p, j) => (j === i ? { ...p, vis: nextVis(p.vis) } : p));
            void save(next);
            return next;
          });
          break;
        }
        case "Backspace": {
          e.preventDefault();
          setDraft((prev) => {
            const next = prev.slice(0, -1);
            void save(next);
            return next;
          });
          setSelected(null);
          break;
        }
        case "Escape": setActiveId(null); setSelected(null); break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, addTrack, removeActive, save, selected]);

  return (
    <div className="app">
      <header>
        RallyTator · {info ? `${info.width}×${info.height} · ${info.fps.toFixed(0)}fps · ${info.n_frames}f` : "no video"}
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
          <span>{activeTrack ? `#${activeTrack.id} ${activeTrack.type} — ${draft.length}/${schema.points.length} pts` : "none"}</span>
        </div>
        <h2>tracks</h2>
        <ul>
          {tracks.map((t) => (
            <li key={t.id} className={t.id === activeId ? "on" : ""} onClick={() => setActiveId(t.id)}
                style={{ borderLeftColor: `#${LABEL_SCHEMAS[t.type].color.toString(16).padStart(6, "0")}` }}>
              #{t.id} {t.type}{detections.some((d) => d.track_id === t.id) ? " ●" : ""}
            </li>
          ))}
        </ul>
        <h2>keys</h2>
        <pre>
{`←/→  step ±1   (shift ±10)
n    new track (of new-type)
1-4  set new-type
Tab  cycle active track
click place / drag move point
v    cycle point visibility
Bksp undo last point
d    delete active track
Esc  deselect`}
        </pre>
      </aside>
    </div>
  );
}
