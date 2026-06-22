#!/usr/bin/env python
"""
Hardware-free web dashboard for the SO-101 follower arm.

This module owns *no* devices. It exposes:

  - ``StateBuffer``: a thread-safe holder for the latest observation
    (joint positions + camera frames + connection status).
  - ``make_app(buffer, cfg)``: a FastAPI app that only *reads* the buffer.
  - ``serve_in_thread(app, host, port)``: run the server in a daemon thread.

Whoever owns the hardware (``monitor.py`` standalone, or ``teleop.py`` while
teleoperating) feeds the buffer via :meth:`StateBuffer.update`. Because the
buffer is just memory, the dashboard can run alongside teleop without opening
a second connection to the single-master serial bus.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import cv2
import numpy as np


class StateBuffer:
    """Thread-safe latest-observation store shared between a feeder and the web app."""

    def __init__(
        self,
        robot_name: str,
        joint_names: list[str],
        camera_names: list[str],
        jpeg_quality: int = 80,
    ) -> None:
        self.robot_name = robot_name
        self.joint_names = list(joint_names)
        self.camera_names = list(camera_names)
        self.jpeg_quality = int(jpeg_quality)

        self._lock = threading.Lock()
        self._frames: dict[str, np.ndarray] = {}
        self._joints: dict[str, float] = {}
        self._connected = False
        self._error: str | None = None
        self._meta: Any = None  # session status (mode, recording info), if any
        self._last_update: float | None = None  # wall time of last observation
        self._update_fps: float = 0.0  # smoothed rate observations arrive at

    def update(self, obs: dict[str, Any]) -> None:
        """Store the joints and frames from one observation dict."""
        joints = {k: float(obs[k]) for k in self.joint_names if k in obs}
        frames = {
            cam: obs[cam]
            for cam in self.camera_names
            if cam in obs and obs[cam] is not None
        }
        now = time.time()
        with self._lock:
            if self._last_update is not None:
                dt = now - self._last_update
                if dt > 0:
                    inst = 1.0 / dt
                    self._update_fps = (
                        inst if self._update_fps == 0 else 0.85 * self._update_fps + 0.15 * inst
                    )
            self._last_update = now
            self._joints = joints
            self._frames.update(frames)
            self._connected = True
            self._error = None

    def set_status(self, connected: bool, error: str | None) -> None:
        with self._lock:
            self._connected = connected
            self._error = error

    def set_meta(self, meta: Any) -> None:
        """Store the latest session status blob carried alongside observations."""
        with self._lock:
            self._meta = meta

    def state(self) -> dict:
        now = time.time()
        with self._lock:
            age_ms = None if self._last_update is None else round((now - self._last_update) * 1000)
            return {
                "connected": self._connected,
                "error": self._error,
                "robot": self.robot_name,
                "joints": dict(self._joints),
                "cameras": list(self.camera_names),
                "session": self._meta,
                "stream": {"fps": round(self._update_fps, 1), "age_ms": age_ms},
            }

    def jpeg(self, cam: str) -> bytes | None:
        with self._lock:
            frame = self._frames.get(cam)
        if frame is None:
            return None
        # Observations are RGB; cv2 expects BGR for correct colours.
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        return buf.tobytes() if ok else None


def make_app(
    buffer: StateBuffer,
    cfg: dict[str, Any],
    poll_fps: float = 30.0,
    command_client=None,
):
    """Build a FastAPI app that serves a view of ``buffer``.

    If ``command_client`` is provided (a ``bridge.CommandClient``), the app
    exposes ``POST /api/command`` so the UI can drive a session server; the
    control panel only appears when the live state carries session status.
    """
    from fastapi import Body, FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

    app = FastAPI(title="SO-101 Monitor")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.get("/api/state")
    def api_state() -> JSONResponse:
        return JSONResponse(buffer.state())

    @app.get("/api/events")
    def api_events() -> StreamingResponse:
        """Server-Sent Events: push full state ~30x/s so the UI updates live."""
        period = 1.0 / max(poll_fps, 1.0)

        def gen():
            while True:
                yield "data: " + json.dumps(buffer.state()) + "\n\n"
                time.sleep(period)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/config")
    def api_config() -> JSONResponse:
        return JSONResponse(
            {
                "ports": cfg.get("ports", {}),
                "robot_id": cfg.get("robot", {}).get("id"),
                "teleop_id": cfg.get("teleop", {}).get("id"),
                "controls_enabled": command_client is not None,
                "cameras": {
                    name: {k: c.get(k) for k in ("index_or_path", "width", "height", "fps")}
                    for name, c in (cfg.get("cameras") or {}).items()
                },
            }
        )

    if command_client is not None:

        @app.post("/api/command")
        def api_command(cmd: dict = Body(...)) -> JSONResponse:
            if not isinstance(cmd, dict) or "cmd" not in cmd:
                raise HTTPException(status_code=400, detail="expected JSON with a 'cmd' field")
            return JSONResponse(command_client.request(cmd))

    def _mjpeg(cam: str):
        boundary = b"--frame"
        period = 1.0 / max(poll_fps, 1.0)
        while True:
            jpg = buffer.jpeg(cam)
            if jpg is not None:
                yield boundary + b"\r\nContent-Type: image/jpeg\r\n"
                yield f"Content-Length: {len(jpg)}\r\n\r\n".encode()
                yield jpg + b"\r\n"
            time.sleep(period)

    @app.get("/stream/{cam}")
    def stream(cam: str) -> StreamingResponse:
        if cam not in buffer.camera_names:
            raise HTTPException(status_code=404, detail=f"Unknown camera '{cam}'")
        return StreamingResponse(
            _mjpeg(cam), media_type="multipart/x-mixed-replace; boundary=frame"
        )

    return app


def serve_in_thread(app, host: str, port: int):
    """Run ``app`` with uvicorn in a daemon thread; returns the uvicorn Server.

    Call ``server.should_exit = True`` to ask it to stop.
    """
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>SO-101 Monitor</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; font-family: system-ui, sans-serif; background:#0f1115; color:#e6e6e6; }
  header { padding:12px 20px; background:#171a21; border-bottom:1px solid #262b36;
           display:flex; align-items:center; gap:16px; }
  header h1 { font-size:16px; margin:0; font-weight:600; }
  .dot { width:10px; height:10px; border-radius:50%; background:#777; display:inline-block; }
  .dot.ok { background:#33d17a; box-shadow:0 0 8px #33d17a; }
  .dot.bad { background:#e0564a; box-shadow:0 0 8px #e0564a; }
  #status { font-size:13px; color:#9aa4b2; }
  main { display:grid; grid-template-columns: 2fr 1fr; gap:16px; padding:16px; }
  @media (max-width: 900px){ main { grid-template-columns:1fr; } }
  .panel { background:#171a21; border:1px solid #262b36; border-radius:10px; padding:14px; }
  .panel h2 { font-size:13px; text-transform:uppercase; letter-spacing:.05em;
              color:#9aa4b2; margin:0 0 12px; }
  .cams { display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:12px; }
  .cam { background:#0b0d11; border:1px solid #262b36; border-radius:8px; overflow:hidden; }
  .cam .label { padding:6px 10px; font-size:12px; color:#9aa4b2; border-bottom:1px solid #262b36; }
  .cam img { width:100%; display:block; background:#000; aspect-ratio:4/3; object-fit:contain; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  td { padding:7px 6px; border-bottom:1px solid #21262f; }
  td.name { color:#9aa4b2; }
  td.val { text-align:right; font-variant-numeric:tabular-nums; }
  .bar { height:6px; background:#21262f; border-radius:3px; margin-top:4px; overflow:hidden; }
  .bar > div { height:100%; background:#5b8def; width:50%; }
  .err { color:#e0564a; font-size:13px; margin-top:8px; white-space:pre-wrap; }
  .meta { font-size:12px; color:#6b7280; margin-top:10px; }
  .mode { display:inline-block; padding:2px 10px; border-radius:999px; font-size:12px;
          font-weight:600; text-transform:uppercase; letter-spacing:.04em; }
  .mode.idle { background:#21262f; color:#9aa4b2; }
  .mode.teleop { background:#1d3a5f; color:#7fb3ff; }
  .mode.recording { background:#4a1d22; color:#ff7a7a; }
  .rec-dot { width:9px; height:9px; border-radius:50%; background:#e0564a; display:inline-block;
             margin-right:6px; animation:pulse 1.1s ease-in-out infinite; vertical-align:middle; }
  @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:.25;} }
  .recinfo { font-size:13px; color:#cbd2dc; margin-top:10px; line-height:1.7; }
  .recinfo b { color:#e6e6e6; font-variant-numeric:tabular-nums; }
  .controls { display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }
  button.ctl { font:inherit; font-size:13px; font-weight:600; padding:8px 14px; border-radius:8px;
               border:1px solid #2f3744; background:#202632; color:#e6e6e6; cursor:pointer; }
  button.ctl:hover { background:#2a313f; }
  button.ctl:disabled { opacity:.5; cursor:default; }
  button.ctl.go { background:#1d4d33; border-color:#2a6b46; color:#cdeedb; }
  button.ctl.go:hover { background:#236040; }
  button.ctl.stop { background:#4a2226; border-color:#6b2f35; color:#ffd6d6; }
  button.ctl.stop:hover { background:#5c2a2f; }
  .tel { display:grid; grid-template-columns:auto 1fr; gap:6px 14px; font-size:13px; }
  .tel .k { color:#9aa4b2; }
  .tel .v { text-align:right; color:#e6e6e6; font-variant-numeric:tabular-nums; }
  .tel .v.warn { color:#f0a35a; }
  .tel .v.bad { color:#e0564a; }
</style>
</head>
<body>
<header>
  <span id="led" class="dot"></span>
  <h1>SO-101 Monitor</h1>
  <span id="status">connecting…</span>
</header>
<main>
  <section class="panel">
    <h2>Cameras</h2>
    <div id="cams" class="cams"></div>
  </section>
  <section class="panel" id="session-panel" style="display:none">
    <h2>Session</h2>
    <div id="session"></div>
    <div id="controls" class="controls"></div>
    <div id="cmd-err" class="err"></div>
  </section>
  <section class="panel">
    <h2>Telemetry</h2>
    <div id="telemetry" class="tel"></div>
    <div id="err" class="err"></div>
  </section>
  <section class="panel">
    <h2>Joint positions</h2>
    <table><tbody id="joints"></tbody></table>
    <div id="meta" class="meta"></div>
  </section>
</main>
<script>
const camsEl = document.getElementById('cams');
const jointsEl = document.getElementById('joints');
const statusEl = document.getElementById('status');
const ledEl = document.getElementById('led');
const errEl = document.getElementById('err');
const metaEl = document.getElementById('meta');
const telEl = document.getElementById('telemetry');
const sessionPanel = document.getElementById('session-panel');
const sessionEl = document.getElementById('session');
const controlsEl = document.getElementById('controls');
const cmdErrEl = document.getElementById('cmd-err');

let camsBuilt = false;
let controlsEnabled = false;
let ports = {};
let busy = false;              // a command is in flight
let predictedMode = null;      // optimistic mode shown until the server confirms
let predictedExpiry = 0;
let controlsKey = '';          // cache to avoid rebuilding buttons every frame
let lastState = null;

// --- commands ---------------------------------------------------------------
async function sendCommand(cmd, optimisticMode){
  if(busy) return;
  busy = true; cmdErrEl.textContent = '';
  if(optimisticMode){ predictedMode = optimisticMode; predictedExpiry = Date.now() + 3000; }
  if(lastState) render(lastState);   // instant visual feedback
  try{
    const r = await fetch('/api/command', {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(cmd)
    });
    const res = await r.json();
    if(!res.ok){ cmdErrEl.textContent = '⚠ ' + (res.error || 'command failed'); predictedMode = null; }
  }catch(e){
    cmdErrEl.textContent = '⚠ ' + e; predictedMode = null;
  }finally{
    busy = false;
  }
}

function startRecording(){
  const task = prompt('Task description for this recording:', '');
  if(task === null) return;
  const cmd = {cmd:'start_recording'};
  if(task.trim()) cmd.single_task = task.trim();
  sendCommand(cmd, 'recording');
}

const BUTTONS = {
  idle:      [['Start teleop', {cmd:'start_teleop'}, 'go', 'teleop'], ['Start recording', null, 'go', null]],
  teleop:    [['Stop teleop', {cmd:'stop_teleop'}, 'stop', 'idle'], ['Start recording', null, 'go', null]],
  recording: [['Save episode', {cmd:'save_episode'}, 'go', null],
              ['Discard episode', {cmd:'discard_episode'}, '', null],
              ['Stop recording', {cmd:'stop_recording'}, 'stop', 'idle']],
};

function buildControls(mode){
  controlsEl.innerHTML = '';
  for(const [label, cmd, cls, optimistic] of (BUTTONS[mode] || [])){
    const b = document.createElement('button');
    b.className = 'ctl' + (cls ? ' ' + cls : '');
    b.textContent = label;
    b.disabled = busy;
    b.onclick = cmd ? () => sendCommand(cmd, optimistic) : startRecording;
    controlsEl.appendChild(b);
  }
}

// --- rendering --------------------------------------------------------------
function buildCams(names){
  camsEl.innerHTML = names.length ? '' : '<div class="meta">No cameras configured.</div>';
  for(const n of names){
    const wrap = document.createElement('div'); wrap.className='cam';
    const lbl = document.createElement('div'); lbl.className='label'; lbl.textContent=n;
    const img = document.createElement('img'); img.src='/stream/'+n+'?t='+Date.now();
    wrap.appendChild(lbl); wrap.appendChild(img); camsEl.appendChild(wrap);
  }
  camsBuilt = true;
}

// SO-101 joints roughly span -180..180 deg; normalise for the bar display.
function pct(v){ return Math.max(0, Math.min(100, (v + 180) / 360 * 100)); }

function row(k, v, cls){ return '<div class="k">'+k+'</div><div class="v'+(cls?' '+cls:'')+'">'+v+'</div>'; }

function render(s){
  lastState = s;
  const sess = s.session;
  const stream = s.stream || {};

  // header + connection
  ledEl.className = 'dot ' + (s.connected ? 'ok' : 'bad');
  statusEl.textContent = s.connected ? (s.robot + ' · connected') : 'disconnected';
  errEl.textContent = s.error ? ('⚠ ' + s.error) : '';

  // telemetry — everything we know
  const age = stream.age_ms;
  const ageCls = age == null ? '' : (age > 2000 ? 'bad' : (age > 500 ? 'warn' : ''));
  let tel = row('Connection', s.connected ? 'connected' : 'disconnected', s.connected ? '' : 'bad');
  tel += row('Robot', s.robot || '—');
  if(sess) tel += row('Mode', '<span class="mode '+sess.mode+'">'+sess.mode+'</span>');
  if(sess && sess.loop_hz) tel += row('Control loop', sess.loop_hz.toFixed(0) + ' Hz');
  if(sess && sess.fps) tel += row('Target FPS', sess.fps);
  tel += row('Stream', (stream.fps != null ? stream.fps.toFixed(0) : '–') + ' Hz');
  tel += row('Data age', age == null ? '–' : age + ' ms', ageCls);
  tel += row('Cameras', (s.cameras || []).join(', ') || '—');
  if(ports.follower) tel += row('Follower', ports.follower);
  if(ports.leader) tel += row('Leader', ports.leader);
  telEl.innerHTML = tel;

  // joints
  const names = Object.keys(s.joints || {}).sort();
  let jt = '';
  for(const n of names){
    const v = s.joints[n];
    jt += '<tr><td class="name">'+n.replace('.pos','')+
      '</td><td class="val">'+v.toFixed(2)+'°<div class="bar"><div style="width:'+
      pct(v)+'%"></div></div></td></tr>';
  }
  jointsEl.innerHTML = jt;

  // session controls (optimistic mode until the server confirms)
  if(!controlsEnabled || !sess){ sessionPanel.style.display = 'none'; return; }
  sessionPanel.style.display = '';
  const realMode = sess.mode;
  if(predictedMode && (realMode === predictedMode || Date.now() > predictedExpiry)) predictedMode = null;
  const mode = predictedMode || realMode;

  let sh = '<span class="mode '+mode+'">'+mode+'</span>';
  if(sess.loop_hz) sh += ' <span class="meta">'+sess.loop_hz.toFixed(0)+' Hz</span>';
  const rec = sess.recording;
  if(rec){
    sh += '<div class="recinfo">'+
      (rec.saving ? '<span class="rec-dot"></span>saving…<br>' : '<span class="rec-dot"></span>recording<br>')+
      'dataset: <b>'+(rec.repo_id||'?')+'</b><br>'+
      'episodes saved: <b>'+rec.episodes_saved+' / '+rec.num_episodes+'</b><br>'+
      'frames this episode: <b>'+rec.episode_frames+'</b></div>';
  }
  sessionEl.innerHTML = sh;

  const key = mode + '|' + busy;       // only rebuild buttons when they change
  if(key !== controlsKey){ buildControls(mode); controlsKey = key; }
}

// --- live state via SSE (falls back to polling) -----------------------------
function onState(s){ if(!camsBuilt) buildCams(s.cameras || []); render(s); }

function startStream(){
  if(!('EventSource' in window)){          // very old browser: poll instead
    setInterval(async () => {
      try{ onState(await (await fetch('/api/state')).json()); }
      catch(e){ ledEl.className='dot bad'; statusEl.textContent='server unreachable'; }
    }, 150);
    return;
  }
  const es = new EventSource('/api/events');
  es.onmessage = (e) => onState(JSON.parse(e.data));
  es.onerror = () => { ledEl.className='dot bad'; statusEl.textContent='reconnecting…'; };
}

fetch('/api/config').then(r=>r.json()).then(c=>{
  ports = c.ports || {};
  metaEl.textContent = 'follower '+(ports.follower||'?')+' · leader '+(ports.leader||'?');
  controlsEnabled = !!c.controls_enabled;
}).finally(startStream);
</script>
</body>
</html>
"""
