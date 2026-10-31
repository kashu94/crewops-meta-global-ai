"use strict";

// --- small helpers ---------------------------------------------------------------------------

const $ = (sel) => document.querySelector(sel);
const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const inr = (n) => (typeof n === "number" ? "INR " + n.toLocaleString("en-IN") : "");
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private window */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};

const DEMO_IDS = [
  { label: "Controller: M. Iyer", user: "m.iyer", role: "controller" },
  { label: "Controller: S. Reddy", user: "s.reddy", role: "controller" },
  { label: "Ops board (viewer)", user: "ops.board", role: "viewer" },
  { label: "Crew: Anjali Goud (C-1157)", user: "anjali", role: "crew", crew: "C-1157" },
  { label: "Crew: Pooja Fernandes (C-1167)", user: "pooja.f", role: "crew", crew: "C-1167" },
];

let config = { auth: "demo" };
let me = null;
let conversationId = null;
let lastVersion = "";

function headers() {
  const h = {};
  if (config.auth === "cognito") {
    const t = store.get("crewops.token");
    if (t) h.Authorization = "Bearer " + t;
  } else {
    const id = DEMO_IDS[Number(store.get("crewops.identity") || 0)] || DEMO_IDS[0];
    h["X-Demo-User"] = id.user;
    h["X-Demo-Role"] = id.role;
    if (id.crew) h["X-Demo-Crew-Id"] = id.crew;
  }
  return h;
}

async function api(path, { method = "GET", json, form } = {}) {
  const opts = { method, headers: headers() };
  if (json !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(json);
  } else if (form) {
    opts.body = form;
  }
  const res = await fetch(path, opts);
  if (res.status === 401 && config.auth === "cognito") {
    store.del("crewops.token");
    showLogin();
    throw new Error("Please sign in again.");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
  return body;
}

const tool = (name, args = {}) => api(`/api/tools/${name}`, { method: "POST", json: args });

// --- sign in ---------------------------------------------------------------------------------

function showLogin() {
  $("#login").hidden = false;
  $("#app").hidden = true;
}

async function cognitoSignIn(username, password) {
  const res = await fetch(`https://cognito-idp.${config.region}.amazonaws.com/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
    },
    body: JSON.stringify({
      AuthFlow: "USER_PASSWORD_AUTH",
      ClientId: config.client_id,
      AuthParameters: { USERNAME: username, PASSWORD: password },
    }),
  });
  const body = await res.json();
  if (!res.ok || !body.AuthenticationResult) throw new Error(body.message || "Sign-in failed.");
  store.set("crewops.token", body.AuthenticationResult.IdToken);
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  $("#login-error").textContent = "";
  try {
    await cognitoSignIn(f.get("username"), f.get("password"));
    await start();
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

$("#signout").addEventListener("click", () => {
  store.del("crewops.token");
  location.reload();
});

// --- tabs ------------------------------------------------------------------------------------

document.querySelectorAll(".tabs button").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll("[data-panel]").forEach((p) => (p.hidden = p.dataset.panel !== b.dataset.tab));
    store.set("crewops.tab", b.dataset.tab);
    if (b.dataset.tab === "score") loadScore();
  }),
);

// --- asking ----------------------------------------------------------------------------------

function routeLine(a) {
  if (a.blocked) return `<span class="chip bad">blocked: ${esc(a.blocked)}</span>`;
  const r = a.route;
  const parts = [];
  if (r) parts.push(`<span class="chip">${esc(r.intent)} · routed by ${esc(r.by)}</span>`);
  parts.push(
    a.verified
      ? `<span class="chip good">every figure checked</span>`
      : `<span class="chip warn">unverified</span>`,
  );
  if (a.steps.length) parts.push(`<span class="chip">${a.steps.length} tool calls</span>`);
  return parts.join(" ");
}

function renderTrace(a) {
  const out = [];
  out.push(`<div class="flow">
    <span class="chip">screen</span>→
    <span class="chip">route${a.route ? ": " + esc(a.route.intent) : ""}</span>→
    <span class="chip">plan with ${a.steps.length} tool calls</span>→
    <span class="chip ${a.verified ? "good" : "warn"}">check every figure</span>→
    <span class="chip">answer</span></div>`);
  if (a.blocked) out.push(`<p class="bad">Blocked before planning: ${esc(a.blocked)}</p>`);
  if (a.route) {
    out.push(`<h3>Route</h3><p>${esc(a.route.intent)}, decided by ${esc(a.route.by === "model" ? "Muse Spark Open" : "keyword rules")}; reasoning effort ${esc(a.route.effort)}; tools offered: ${a.route.tools.map(esc).join(", ") || "none"}.</p>`);
  }
  if (a.steps.length) {
    out.push(`<h3>Tool calls (by Muse Spark, answered by the rules engine)</h3><div class="steps">`);
    a.steps.forEach((s, i) => {
      const failed = s.result && s.result.error;
      out.push(`<details><summary>${i + 1}. <b>${esc(s.tool)}</b> ${esc(JSON.stringify(s.arguments))} ${failed ? '<span class="chip bad">error</span>' : ""}</summary><pre>${esc(JSON.stringify(s.result, null, 2))}</pre></details>`);
    });
    out.push(`</div>`);
  }
  out.push(`<h3>Evidence check</h3>`);
  if (a.draft) {
    out.push(`<p class="warn">The first draft stated things no tool returned:</p><ul>${a.draft_problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul><details><summary>First draft</summary><pre>${esc(a.draft)}</pre></details><p>It was rewritten from the evidence.</p>`);
  }
  out.push(
    a.verified
      ? `<p class="good">Every id, time, hour figure, count and amount in the answer matches a tool result.</p>`
      : `<p class="warn">${a.problems.length ? a.problems.map(esc).join("; ") : "Not checked."}</p>`,
  );
  if (a.calls.length) {
    out.push(`<h3>Model calls</h3><table><tr><th>Model</th><th>For</th><th>Effort</th><th class="num">In</th><th class="num">Out</th><th class="num">Reasoning</th><th class="num">Cached</th><th class="num">Seconds</th></tr>`);
    a.calls.forEach((c) =>
      out.push(`<tr><td>${esc(c.model)}</td><td>${esc(c.purpose)}</td><td>${esc(c.effort)}</td><td class="num">${c.prompt}</td><td class="num">${c.completion}</td><td class="num">${c.reasoning}</td><td class="num">${c.cached}</td><td class="num">${c.seconds}</td></tr>`),
    );
    out.push(`</table>`);
  }
  $("#trace").classList.remove("muted");
  $("#trace").innerHTML = out.join("");
}

function say(text) {
  if (!$("#speak").checked || !("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text.replace(/\bC-(\d{4})\b/g, "C $1").replace(/\bT-(\d{4})\b/g, "T $1"));
  const lang = $("#lang").value.split(",")[0];
  u.lang = lang === "Hindi" ? "hi-IN" : lang === "Telugu" ? "te-IN" : "en-IN";
  speechSynthesis.speak(u);
}

async function ask(question) {
  const btn = $("#ask-btn");
  btn.disabled = true;
  btn.textContent = "Working…";
  $("#trace").innerHTML = `<div class="flow"><span class="chip">screen</span>→<span class="chip">route</span>→<span class="chip">plan with tools</span>→<span class="chip">check every figure</span>→<span class="chip">answer</span></div><p class="muted">Muse Spark is working through the tools…</p>`;
  try {
    const a = await api("/api/ask", { method: "POST", json: { question, conversation_id: conversationId } });
    conversationId = a.conversation_id;
    const div = document.createElement("div");
    div.className = "answer";
    div.innerHTML = `<div class="q">${esc(question)}</div><div class="text">${esc(a.text)}</div><div class="row">${routeLine(a)}</div>`;
    $("#answers").prepend(div);
    renderTrace(a);
    say(a.text);
    refresh(true);
  } catch (err) {
    $("#trace").innerHTML = `<p class="bad">${esc(err.message)}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Ask";
  }
}

$("#ask-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#question").value.trim();
  if (q) ask(q);
});
$("#new-convo").addEventListener("click", () => {
  conversationId = null;
  $("#answers").innerHTML = "";
});

// --- voice: record 16 kHz mono WAV in the browser, as Muse Voice Transcribe expects -----------

let recorder = null;

function wav(samples, rate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const w = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true);
  v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
  return new Blob([buf], { type: "audio/wav" });
}

function downsample(chunks, from, to) {
  const all = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let o = 0;
  chunks.forEach((c) => { all.set(c, o); o += c.length; });
  const ratio = from / to;
  const out = new Float32Array(Math.floor(all.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio), end = Math.min(all.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += all[j];
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  const ctx = new AudioContext();
  const source = ctx.createMediaStreamSource(stream);
  const node = ctx.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  node.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  source.connect(node);
  node.connect(ctx.destination);
  recorder = { stream, ctx, node, chunks, started: Date.now() };
}

async function stopRecording() {
  const r = recorder;
  recorder = null;
  r.node.disconnect();
  r.stream.getTracks().forEach((t) => t.stop());
  const rate = r.ctx.sampleRate;
  await r.ctx.close();
  return wav(downsample(r.chunks, rate, 16000), 16000);
}

$("#mic").addEventListener("click", async () => {
  const btn = $("#mic");
  if (!recorder) {
    try {
      await startRecording();
      btn.classList.add("rec");
      btn.textContent = "■ Stop";
      $("#mic-state").textContent = "Listening… press Stop when you finish.";
    } catch (err) {
      $("#mic-state").textContent = "Microphone not available: " + err.message;
    }
    return;
  }
  btn.classList.remove("rec");
  btn.textContent = "🎙 Speak";
  $("#mic-state").textContent = "Transcribing with Muse Voice Transcribe…";
  try {
    const blob = await stopRecording();
    const form = new FormData();
    form.append("audio", blob, "speech.wav");
    form.append("languages", $("#lang").value);
    const t = await api("/api/voice", { method: "POST", form });
    $("#mic-state").textContent = t.text ? `Heard (${t.seconds}s): “${t.text}”` : "Nothing was heard. Try again a little closer.";
    if (t.text) {
      $("#question").value = t.text;
      ask(t.text);
    }
  } catch (err) {
    $("#mic-state").textContent = err.message;
  }
});

// --- desk: issues, callouts, unavailability, messages ----------------------------------------

const isController = () => me && me.role === "controller";

async function loadIssues() {
  const r = await tool("open_issues", { limit: 20 });
  if (r.error) { $("#issues").innerHTML = `<p class="muted">${esc(r.error)}</p>`; return; }
  $("#issues").innerHTML = r.issues.length ? r.issues.map((i) => `
    <div class="item"><div class="top"><b>${esc(i.name)} (${esc(i.crew_id)})</b>
      <span class="chip ${i.kind === "illegal" ? "bad" : i.kind === "fatigue" ? "warn" : ""}">${esc(i.kind)}</span></div>
      <div>${i.trip_id ? esc(i.trip_id) + ", " : ""}${esc(i.day)}: ${esc(i.detail)}</div>
      ${i.suggested_cover ? `<div class="muted">Cheapest legal cover: ${esc(i.suggested_cover)}, ${inr(i.suggested_cost_inr)}</div>` : ""}
      ${i.kind === "illegal" && isController() ? `<div class="row"><button class="ghost" data-callout="${esc(i.trip_id)}|${esc(i.crew_id)}">Start callout</button></div>` : ""}
    </div>`).join("") : `<p class="muted">Nothing found in the next 7 days.</p>`;
}

function offerLine(o) {
  const gone = ["declined", "unavailable", "no answer", "no longer legal"].includes(o.answer);
  return `<li class="${gone ? "struck" : ""}">${esc(o.name)} (${esc(o.crew_id)}), ${inr(o.cost_inr)} <span class="why chip ${o.answer === "accepted" ? "good" : gone ? "bad" : ""}">${esc(o.answer)}</span></li>`;
}

async function loadCallouts() {
  const r = await tool("callout_status", {});
  if (r.error) { $("#callouts").innerHTML = `<p class="muted">${esc(r.error)}</p>`; return; }
  const list = r.callouts || r.offers_to_me || [];
  $("#callouts").innerHTML = list.length ? list.map((c) => {
    const mine = me.role === "crew" && c.waiting_for === me.crew_id;
    const actions = [];
    if (mine) actions.push(`<button data-answer="${esc(c.callout_id)}|yes">Accept</button><button class="ghost" data-answer="${esc(c.callout_id)}|no">Decline</button>`);
    if (isController() && c.status === "needs_decision") (c.desk_options || []).forEach((o) => actions.push(`<button class="ghost" data-decide="${esc(c.callout_id)}|propose_${esc(o.way)}">Propose: ${esc(o.summary)} (${inr(o.cost_inr)})</button>`));
    if (isController() && c.status === "awaiting_approval") actions.push(`<button data-decide="${esc(c.callout_id)}|approve">Approve (second controller)</button><button class="ghost" data-decide="${esc(c.callout_id)}|reject">Reject</button>`);
    return `<div class="item"><div class="top"><b>${esc(c.trip_id)} ${esc(c.seat)}, replacing ${esc(c.replacing)}</b><span class="chip ${c.status === "filled" ? "good" : c.status === "offered" ? "" : "warn"}">${esc(c.status.replace("_", " "))}</span></div>
      <ul>${c.asked.map(offerLine).join("")}</ul>
      ${c.waiting_for ? `<div class="muted">Waiting for ${esc(c.waiting_for)} until ${esc(c.answer_by)}</div>` : ""}
      ${c.to_arrange ? `<div class="warn">To arrange: ${c.to_arrange.map(esc).join("; ")}</div>` : ""}
      ${c.note ? `<div class="warn">${esc(c.note)}</div>` : ""}
      ${c.proposal ? `<div>Proposal: ${esc(c.proposal.summary)} by ${esc(c.proposal.proposed_by)}${c.proposal.approved_by ? ", approved by " + esc(c.proposal.approved_by) : ""}</div>` : ""}
      ${actions.length ? `<div class="row">${actions.join("")}</div>` : ""}</div>`;
  }).join("") : `<p class="muted">No callouts.</p>`;
}

async function loadNotices() {
  const r = await api("/api/notices");
  $("#notices").innerHTML = r.notices.length ? r.notices.map((n) => `<div class="item"><div class="top"><b>${esc(n.subject)}</b><span class="muted">${esc(n.at)}</span></div><div>${esc(n.body)}</div></div>`).join("") : `<p class="muted">No messages.</p>`;
}

document.addEventListener("click", async (e) => {
  const t = e.target.closest("button");
  if (!t) return;
  try {
    if (t.dataset.callout) {
      const [trip_id, replace_crew_id] = t.dataset.callout.split("|");
      const r = await tool("start_callout", { trip_id, replace_crew_id });
      if (r.error) alert(r.error);
    } else if (t.dataset.answer) {
      const [callout_id, yes] = t.dataset.answer.split("|");
      const r = await tool("answer_callout", { callout_id, accept: yes === "yes" });
      if (r.error) alert(r.error);
    } else if (t.dataset.decide) {
      const [callout_id, action] = t.dataset.decide.split("|");
      const r = await tool("decide_callout", { callout_id, action });
      if (r.error) alert(r.error);
    } else if (t.dataset.propose) {
      const call = JSON.parse(t.dataset.propose);
      const r = await tool(call.tool, call.arguments);
      t.closest("div").insertAdjacentHTML("beforeend", `<pre>${esc(JSON.stringify(r, null, 2))}</pre>`);
    } else if (t.dataset.startCover) {
      const [trip_id, replace_crew_id] = t.dataset.startCover.split("|");
      const r = await tool("start_callout", { trip_id, replace_crew_id });
      if (r.error) alert(r.error);
    } else return;
    refresh(true);
  } catch (err) {
    alert(err.message);
  }
});

$("#unavail-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  if (!f.crew_id) delete f.crew_id;
  const r = await tool("report_unavailable", f);
  $("#unavail-result").innerHTML = r.error
    ? `<span class="bad">${esc(r.error)}</span>`
    : `Recorded ${esc(r.crew_id)} unavailable ${esc(r.from)} to ${esc(r.to)}.` +
      (r.own_trips_now_short.length ? ` Their trips now short: ${r.own_trips_now_short.map(esc).join(", ")}.` : "") +
      (r.callout_offers_withdrawn.length ? ` Offers withdrawn: ${r.callout_offers_withdrawn.map(esc).join(", ")}.` : "");
  refresh(true);
});

// --- cover explorer --------------------------------------------------------------------------

let coverArgs = null;

async function loadCover() {
  if (!coverArgs) return;
  const r = await tool("find_cover", { ...coverArgs, limit: 10 });
  if (r.error) { $("#cover").innerHTML = `<p class="bad">${esc(r.error)}</p>`; return; }
  const rows = r.choices.map((c) => `<tr><td>${c.position}</td><td>${esc(c.summary)}${c.fatigue ? c.fatigue.map((f) => `<div class="warn small">${esc(f.severity)}: ${esc(f.detail)}</div>`).join("") : ""}${c.to_arrange ? `<div class="small">To arrange: ${c.to_arrange.map(esc).join("; ")}</div>` : ""}</td><td class="num">${inr(c.cost_inr)}</td></tr>`);
  (r.withdrawn || []).forEach((w) => rows.push(`<tr class="struck"><td>–</td><td>${esc(w.summary)} <span class="why chip bad">withdrawn: ${esc(w.reason)}</span></td><td class="num">${inr(w.cost_inr)}</td></tr>`));
  const funnel = r.funnel.map((s) => `<span class="chip">${esc(s.stage)}: ${s.left} left (−${s.dropped})</span>`).join(" ");
  const start = isController() && coverArgs.vacated_by ? `<button data-start-cover="${esc(coverArgs.trip_id)}|${esc(coverArgs.vacated_by)}">Start callout</button>` : "";
  $("#cover").innerHTML = `<p class="muted">${r.considered} considered. ${funnel}</p><table><tr><th>#</th><th>Choice</th><th class="num">Cost</th></tr>${rows.join("")}</table><div class="row">${start}</div>`;
}

$("#cover-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  if (!f.vacated_by) delete f.vacated_by;
  coverArgs = f;
  loadCover();
});

// --- photos ----------------------------------------------------------------------------------

$("#photo-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const file = f.get("image");
  if (!f.get("tail")) f.delete("tail");
  $("#photo-result").textContent = "Checking the photo…";
  try {
    const r = await api("/api/intake", { method: "POST", form: f });
    const cls = { rejected: "bad", reshoot: "warn", confirm: "warn", draft: "good" }[r.status];
    const out = [`<p><span class="chip ${cls}">${esc(r.status)}</span> ${esc(r.message)}</p>`];
    if (r.confidence) out.push(`<p>Confidence: <b>${esc(r.confidence)}</b></p>`);
    if (r.signals && Object.keys(r.signals).length) out.push(`<details><summary>Signals behind the confidence</summary><pre>${esc(JSON.stringify(r.signals, null, 2))}</pre></details>`);
    if (r.quality) out.push(`<p class="muted small">Picture: ${r.quality.width}×${r.quality.height}, sharpness ${r.quality.sharpness}, brightness ${r.quality.brightness}</p>`);
    if (r.form && Object.keys(r.form).length) out.push(`<details><summary>What Muse Spark read</summary><pre>${esc(JSON.stringify(r.form, null, 2))}</pre></details>`);
    if (r.crew && r.crew.length > 1) out.push(`<p>Possible people: ${r.crew.map((c) => esc(`${c.name} (${c.crew_id})`)).join(", ")}</p>`);
    if (r.proposal) {
      const calls = r.proposal.calls || [r.proposal];
      calls.forEach((c) => out.push(`<div class="row"><button data-propose='${esc(JSON.stringify(c))}'>Confirm: ${esc(c.tool.replace("_", " "))} ${esc(JSON.stringify(c.arguments))}</button></div>`));
    }
    $("#photo-result").classList.remove("muted");
    $("#photo-result").innerHTML = out.join("");
    drawPhoto(file, r.box);
  } catch (err) {
    $("#photo-result").innerHTML = `<p class="bad">${esc(err.message)}</p>`;
  }
});

function drawPhoto(file, box) {
  const img = new Image();
  img.onload = () => {
    const c = $("#photo-canvas");
    c.width = img.naturalWidth;
    c.height = img.naturalHeight;
    const g = c.getContext("2d");
    g.drawImage(img, 0, 0);
    if (box) {
      const sx = c.width / box.width, sy = c.height / box.height;
      g.lineWidth = Math.max(4, c.width / 250);
      g.strokeStyle = "#ff3b30";
      g.strokeRect(box.x1 * sx, box.y1 * sy, (box.x2 - box.x1) * sx, (box.y2 - box.y1) * sy);
      g.font = `${Math.max(18, c.width / 45)}px system-ui`;
      g.fillStyle = "#ff3b30";
      g.fillText(`SAM 3.1: ${Math.round(box.confidence * 100)}%`, box.x1 * sx, Math.max(24, box.y1 * sy - 10));
    }
    c.hidden = false;
  };
  img.src = URL.createObjectURL(file);
}

// --- scorecard -------------------------------------------------------------------------------

async function loadScore() {
  try {
    const s = await api("/api/scorecard");
    const rows = s.scenarios.map((x) => `<tr><td>${esc(x.id)}</td><td>${esc(x.question)}</td><td>${esc(x.expected_intent)}</td><td>${esc(x.intent)}</td><td>${x.passed ? '<span class="good">pass</span>' : `<span class="bad">fail</span> ${esc(x.why)}`}</td><td class="num">${x.tokens}</td></tr>`);
    $("#score").classList.remove("muted");
    $("#score").innerHTML = `<p>${esc(s.summary)}</p><table><tr><th>#</th><th>Scenario</th><th>Expected</th><th>Routed</th><th>Result</th><th class="num">Tokens</th></tr>${rows.join("")}</table>`;
  } catch (err) {
    $("#score").textContent = err.message;
  }
}

// --- live refresh ----------------------------------------------------------------------------

async function refresh(force = false) {
  try {
    const v = await api("/api/version");
    const key = `${v.roster}:${v.callouts}:${v.notices}`;
    if (!force && key === lastVersion) return;
    lastVersion = key;
    await Promise.allSettled([loadIssues(), loadCallouts(), loadNotices(), loadCover()]);
  } catch { /* shown on the next action */ }
}

// --- start -----------------------------------------------------------------------------------

async function start() {
  if (config.auth === "cognito" && !store.get("crewops.token")) return showLogin();
  me = await api("/api/me");
  $("#login").hidden = true;
  $("#app").hidden = false;
  $("#clock").textContent = "Operation clock: " + me.clock;
  $("#signed").textContent = config.auth === "cognito" ? `${me.user} (${me.role})` : "";
  $("#signout").hidden = config.auth !== "cognito";
  const tab = store.get("crewops.tab");
  if (tab) document.querySelector(`.tabs button[data-tab="${tab}"]`)?.click();
  refresh(true);
  setInterval(refresh, 2500);
}

(async function boot() {
  config = await fetch("/api/config").then((r) => r.json());
  if (config.auth === "demo") {
    const sel = $("#identity");
    sel.hidden = false;
    sel.innerHTML = DEMO_IDS.map((d, i) => `<option value="${i}">${esc(d.label)}</option>`).join("");
    sel.value = store.get("crewops.identity") || "0";
    sel.addEventListener("change", () => { store.set("crewops.identity", sel.value); location.reload(); });
  }
  try { await start(); } catch (err) { document.body.insertAdjacentHTML("beforeend", `<p class="bad" style="padding:1rem">${esc(err.message)}</p>`); }
})();
