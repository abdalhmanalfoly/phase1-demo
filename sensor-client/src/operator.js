// Minimal operator/debug panel: polls the host status API once per second (single interval).
const $ = (id) => document.getElementById(id);
let sessionId = new URLSearchParams(location.search).get("session") || "";
let timer = null;

const td = (v) => { const c = document.createElement("td"); c.textContent = v ?? "—"; return c; };

async function poll() {
  try {
    const h = await (await fetch("/api/health")).json();
    $("host-state").textContent = `Host: ok (v${h.host_version}, protocol ${h.protocol_version}), ${h.sessions_active} active session(s)`;
  } catch { $("host-state").textContent = "Host: UNREACHABLE"; return; }
  if (!sessionId) return;
  const r = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`);
  if (!r.ok) { $("s-state").textContent = r.status === 404 ? "unknown session" : `error ${r.status}`; return; }
  const s = await r.json();
  $("s-id").textContent = s.session_id; $("s-state").textContent = s.state;
  $("s-conn").textContent = s.sensors_connected; $("s-rej").textContent = s.messages_rejected;
  $("stop-btn").disabled = s.state !== "active";
  const body = $("sensors"); body.replaceChildren();
  for (const x of s.sensors) {
    const tr = document.createElement("tr");
    const st = document.createElement("td"); const pill = document.createElement("span");
    pill.className = `pill ${x.state}`; pill.textContent = x.state; pill.title = x.state_reason; st.append(pill);
    tr.append(td(x.sensor_id), st, td(x.permission), td(x.camera), td(x.inference), td(x.update_rate_hz),
      td(x.latest_observation_age_ms), td(x.latest_observation_capture_age_ms), td(x.hand ?? "—"),
      td(x.observations_accepted), td(x.observations_rejected), td(x.sequence_gaps), td(x.reconnect_count),
      td(x.last_error ? `${x.last_error.error_code}` : "—"));
    body.append(tr);
  }
  const ul = $("errors"); ul.replaceChildren();
  for (const e of [...s.recent_errors].reverse()) {
    const li = document.createElement("li");
    li.textContent = `${new Date(e.ts_ms).toLocaleTimeString()} ${e.sensor_id ?? "-"} ${e.error_code}: ${e.message}`;
    ul.append(li);
  }
}
function show(id) {
  sessionId = id; $("session-input").value = id;
  $("join").textContent = id ? `Join link: ${location.origin}/client/?session=${id}` : "Join link: —";
}
$("create-btn").addEventListener("click", async () => {
  const r = await fetch("/api/sessions", { method: "POST" });
  if (r.ok) show((await r.json()).session_id); else $("s-state").textContent = `create failed (${r.status})`;
  poll();
});
$("session-input").addEventListener("change", (e) => show(e.target.value.trim()));
$("stop-btn").addEventListener("click", async () => { await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/stop`, { method: "POST" }); poll(); });
show(sessionId); poll();
if (timer === null) timer = setInterval(poll, 1000);
