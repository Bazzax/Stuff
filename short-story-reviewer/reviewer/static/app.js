"use strict";

const $ = (id) => document.getElementById(id);
const state = { config: null, file: null, analysis: null, notice: null, estimate: null, running: false };

const BAND_NOTES = {
  "flash": "flash fiction, under 1,500 words",
  "short story": "short story, under 7,500 words",
  "novelette": "novelette, 7,500 to 17,500 words",
  "over novelette length": "over 17,500 words, longer than this reviewer handles",
};
const STAGE_TITLES = {
  cold_read: "Cold read", design: "Design statement", scene_map: "Scene map and structure",
  genre: "Genre layer (speculative fiction only)", register: "Register layer (comic, deadpan, dark)",
  line: "Line pass", triage: "Triage", letter: "Editorial letter",
};

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function radio(name) {
  return document.querySelector(`input[name="${name}"]:checked`).value;
}

function storyPayload() {
  if (state.file) return { file_name: state.file.name, file_b64: state.file.b64 };
  return { text: $("text").value };
}

function briefPayload() {
  const market = $("market").value;
  return {
    title: $("title").value.trim(),
    market_id: market && market !== "__other" ? market : null,
    market_name: market === "__other" ? $("market-name").value.trim() : "",
    draft_stage: radio("draft_stage"),
    edit_level: radio("edit_level"),
    questions: $("questions").value.trim(),
    conventions: radio("conventions"),
    mode: radio("mode"),
  };
}

function headers() {
  const h = { "Content-Type": "application/json" };
  const code = $("access-code").value;
  if (code) h["X-Access-Code"] = code;
  return h;
}

async function post(path, body) {
  const res = await fetch(path, { method: "POST", headers: headers(), body: JSON.stringify(body) });
  let data = null;
  try { data = await res.json(); } catch (_) { /* not JSON */ }
  if (!res.ok) throw new Error((data && data.error) || `The server returned ${res.status}.`);
  return data;
}

function hasStory() {
  return Boolean(state.file || $("text").value.trim());
}

// ------------------------------------------------------------ story

async function analyse() {
  const measure = $("measure");
  measure.classList.remove("error");
  state.analysis = null;
  if (!hasStory()) {
    measure.textContent = "";
    $("counts-box").hidden = true;
    updateEstimate();
    return;
  }
  measure.textContent = "Measuring…";
  try {
    const a = await post("/api/analyse", { story: storyPayload() });
    state.analysis = a;
    measure.innerHTML = `${a.word_count.toLocaleString("en-GB")} words <span class="band">· ${escapeHtml(BAND_NOTES[a.band] || a.band)}</span>`;
    if (a.too_long) measure.classList.add("error");
    $("counts").innerHTML = a.counts_summary.map((l) => `<li>${escapeHtml(l)}</li>`).join("");
    $("counts-box").hidden = false;
  } catch (err) {
    measure.textContent = err.message;
    measure.classList.add("error");
    $("counts-box").hidden = true;
  }
  updateEstimate();
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(new Error("The file could not be read."));
    reader.readAsDataURL(file);
  });
}

async function onFile() {
  const f = $("file").files[0];
  if (!f) return;
  if (f.size > 3 * 1024 * 1024) {
    $("measure").textContent = "That file is larger than 3 MB.";
    $("measure").classList.add("error");
    return;
  }
  state.file = { name: f.name, b64: await readFile(f) };
  $("text").value = "";
  $("text").disabled = true;
  $("text").placeholder = `Using ${f.name}.`;
  $("clear-file").hidden = false;
  if (!$("title").value) $("title").value = f.name.replace(/\.(docx|txt|md)$/i, "");
  analyse();
}

function clearFile() {
  state.file = null;
  $("file").value = "";
  $("text").disabled = false;
  $("text").placeholder = "Paste the story here.";
  $("clear-file").hidden = true;
  analyse();
}

// ------------------------------------------------------------ brief and estimate

function renderNotice(n) {
  const box = $("notice");
  const rewrites = $("mode-rewrites");
  if (!n) {
    box.hidden = true;
    rewrites.disabled = false;
    $("mode-hint").textContent = "Suggested rewrites are labelled as suggestions, kept in the letter, and never put into the manuscript file.";
    return;
  }
  let html = `<h3>${escapeHtml(n.name)}</h3>`;
  if (n.ai_wording) {
    html += `<p>AI policy${n.ai_heading ? `: <em>${escapeHtml(n.ai_heading)}</em>` : ""}</p>`;
    html += `<blockquote>${escapeHtml(n.ai_wording)}</blockquote>`;
  }
  if (n.length_wording) html += `<p>Length: <q>${escapeHtml(n.length_wording)}</q></p>`;
  if (n.date_checked) {
    html += `<p class="checked">Quoted from <a href="${escapeHtml(n.url)}" target="_blank" rel="noopener">the market's guidelines</a>, checked ${escapeHtml(n.date_checked)}. Guidelines change; check them before you submit.</p>`;
  }
  if (n.statements && n.statements.length) {
    html += `<ul>${n.statements.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ul>`;
  }
  box.innerHTML = html;
  box.classList.toggle("bars", Boolean(n.rewrite_blocked));
  box.hidden = false;

  rewrites.disabled = Boolean(n.rewrite_blocked);
  if (n.rewrite_blocked) {
    document.querySelector('input[name="mode"][value="diagnosis"]').checked = true;
    $("mode-hint").textContent = `Rewrite mode is off: ${n.name} bars AI-written or AI-edited text.`;
  }
}

const updateEstimate = debounce(async () => {
  const out = $("estimate");
  if (!hasStory() || !state.analysis) {
    out.textContent = "Add a story to see the estimated cost.";
    const chosen = state.config.markets.find((m) => m.id === briefPayload().market_id);
    renderNotice(chosen ? chosen.notice : null);
    refreshRunButton();
    return;
  }
  try {
    const data = await post("/api/estimate", { story: storyPayload(), brief: briefPayload() });
    state.notice = data.notice;
    state.estimate = data;
    renderNotice(data.notice);
    const e = data.estimate;
    out.innerHTML = `Estimated cost about <strong>$${e.expected_usd.toFixed(2)}</strong>; at most $${e.max_usd.toFixed(2)} if every stage used its full output allowance.`
      + (data.within_run_cap ? "" : ` <strong>That is over this server's per-run cap of $${state.config.max_run_cost_usd.toFixed(2)}.</strong>`);
  } catch (err) {
    out.textContent = err.message;
  }
  refreshRunButton();
}, 350);

function refreshRunButton() {
  const c = state.config;
  const ready = c && c.method_loaded && c.api_key_configured;
  const ok = ready && state.analysis && !state.analysis.too_long && state.estimate && state.estimate.within_run_cap;
  $("run").disabled = !ok || state.running;
}

// ------------------------------------------------------------ run

function stageRow(key) {
  return document.querySelector(`#progress li[data-stage="${key}"]`);
}

function setStage(key, cls, why) {
  const li = stageRow(key);
  if (!li) return;
  li.className = cls;
  if (why) li.insertAdjacentHTML("beforeend", `<span class="why">${escapeHtml(why)}</span>`);
}

async function run() {
  state.running = true;
  refreshRunButton();
  $("results").hidden = true;
  const progress = $("progress");
  progress.innerHTML = state.config.stages.map((s) => `<li data-stage="${s.key}">${escapeHtml(STAGE_TITLES[s.key] || s.key)}</li>`).join("");
  progress.hidden = false;
  const status = $("run-status");
  status.classList.remove("error");
  const started = Date.now();
  const timer = setInterval(() => {
    status.textContent = `Running… ${Math.round((Date.now() - started) / 1000)} s. Keep this page open.`;
  }, 1000);

  try {
    const res = await fetch("/api/run", { method: "POST", headers: headers(), body: JSON.stringify({ story: storyPayload(), brief: briefPayload() }) });
    if (!res.ok) {
      let msg = `The server returned ${res.status}.`;
      try { msg = (await res.json()).error || msg; } catch (_) { /* keep default */ }
      throw new Error(msg);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let finished = false;
    while (!finished) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        const ev = JSON.parse(line);
        if (ev.type === "stage_start") setStage(ev.stage, "running");
        else if (ev.type === "stage_done") setStage(ev.stage, "done");
        else if (ev.type === "stage_skipped") setStage(ev.stage, "skipped", ev.reason);
        else if (ev.type === "assembling") status.textContent = "Writing the files…";
        else if (ev.type === "error") throw new Error(ev.message + (ev.spent_usd ? ` (This run spent $${ev.spent_usd.toFixed(2)}.)` : ""));
        else if (ev.type === "result") { showResults(ev); finished = true; }
      }
    }
    if (!finished) throw new Error("The connection closed before the review finished.");
    clearInterval(timer);
    status.textContent = `Done in ${Math.round((Date.now() - started) / 1000)} s.`;
  } catch (err) {
    clearInterval(timer);
    status.textContent = err.message;
    status.classList.add("error");
    document.querySelectorAll("#progress li.running").forEach((li) => { li.className = ""; });
  } finally {
    state.running = false;
    refreshRunButton();
  }
}

function downloadLink(file, mime, label) {
  let blob;
  if (file.text !== undefined) {
    blob = new Blob([file.text], { type: mime });
  } else {
    const bytes = Uint8Array.from(atob(file.b64), (c) => c.charCodeAt(0));
    blob = new Blob([bytes], { type: mime });
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = file.name;
  a.textContent = label;
  return a;
}

function showResults(r) {
  const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  const dl = $("downloads");
  dl.innerHTML = "";
  dl.append(downloadLink(r.files.letter_docx, DOCX, "Letter (.docx)"));
  dl.append(downloadLink(r.files.letter_md, "text/markdown", "Letter (.md)"));
  if (r.files.annotated_docx) dl.append(downloadLink(r.files.annotated_docx, DOCX, "Manuscript with margin comments (.docx)"));

  const w = $("warnings");
  w.hidden = !r.warnings.length;
  w.innerHTML = r.warnings.length ? `<ul>${r.warnings.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>` : "";

  $("letter").innerHTML = r.letter_html; // built server-side with every value escaped

  const notes = r.located_notes || [];
  $("notes-box").hidden = !notes.length;
  $("notes").innerHTML = notes.map((n) =>
    `<li><q>${escapeHtml(n.anchor)}</q>: <strong>${escapeHtml(n.kind)}</strong>. ${escapeHtml(n.note)}`
    + (n.placed ? "" : ' <span class="unplaced">(not found in the manuscript)</span>') + "</li>").join("");

  const rows = r.cost.by_stage.map((s) =>
    `<tr><td>${escapeHtml(STAGE_TITLES[s.stage] || s.stage)}</td><td>${escapeHtml(s.usage.map((u) => u.model).join(", "))}</td><td class="num-cell">$${s.usd.toFixed(3)}</td></tr>`);
  rows.push(`<tr><th colspan="2">Total</th><th class="num-cell">$${r.cost.total_usd.toFixed(2)}</th></tr>`);
  $("cost").innerHTML = rows.join("");

  $("results").hidden = false;
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ------------------------------------------------------------ start

async function init() {
  try {
    const res = await fetch("/api/config");
    state.config = await res.json();
  } catch (_) {
    $("server-status").textContent = "The server could not be reached.";
    $("server-status").hidden = false;
    return;
  }
  const c = state.config;
  const sel = $("market");
  for (const m of c.markets) sel.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name)}</option>`);
  sel.insertAdjacentHTML("beforeend", '<option value="__other">Another market…</option>');
  $("code-field").hidden = !c.access_code_required;

  const problems = [];
  if (!c.method_loaded) problems.push("The editorial method has not been installed on this server, so runs are switched off.");
  if (!c.api_key_configured) problems.push("No Anthropic API key is configured on this server, so runs are switched off.");
  if (problems.length) {
    $("server-status").innerHTML = problems.map(escapeHtml).join("<br>");
    $("server-status").hidden = false;
  }

  $("file").addEventListener("change", onFile);
  $("clear-file").addEventListener("click", clearFile);
  $("text").addEventListener("input", debounce(analyse, 600));
  $("market").addEventListener("change", () => {
    $("other-market-field").hidden = $("market").value !== "__other";
    if (!$("market").value) state.notice = null;
    updateEstimate();
  });
  for (const id of ["title", "market-name", "questions"]) $(id).addEventListener("input", updateEstimate);
  document.querySelectorAll('input[type="radio"]').forEach((r) => r.addEventListener("change", updateEstimate));
  $("run").addEventListener("click", run);
}

init();
