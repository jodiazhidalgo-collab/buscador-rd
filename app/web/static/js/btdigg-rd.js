let activeModule = "btdigg";
let moduleResults = { btdigg: [] };
let moduleLogs = { btdigg: ["Listo. Escribe una b\u00fasqueda y pulsa BUSCAR."] };
let liveStreams = { btdigg: null };
let moduleBusy = { btdigg: false };
let activeJobIds = { btdigg: null };
let rdFollowTimer = null;
let rdFollowJobId = null;
let rdFollowTraceKind = "job";
let rdFollowCursor = 0;
let rdFollowLines = [];
let rdFollowAdvice = [];
let rdFollowCollapsed = false;
let resultSort = { btdigg: { key: "index", dir: "asc" } };
let settingsCache = null;
let tvRulesCache = null;
let tvRulesDefaults = null;
let formStateRestored = false;
let finishSound = null;
const finishSoundUrl = "/static/sounds/applepay.mp3";
const finishSoundVolume = 0.55;
const notifiedJobs = {};
let qbitSearchEnabled = true;

const formStoreKey = "btdiggRd.form.v1";
const viewStoreKey = "btdiggRd.view.v1";
const activityStoreKey = "btdiggRd.activity.v1";
const activeJobStoreKey = "btdiggRd.activeJob.v1";
const rdFollowStoreKey = "btdiggRd.rdFollow.v1";
const rdFollowTestStoreKey = "btdiggRd.rdFollowTest.v1";
const rdOkVerifyTitleMarker = "__RD_OK_VERIFY_TITLE__";
let historyCache = null;
let historyOpenState = { days: {}, searches: {} };
let historyResultStore = {};

function getFinishSound() {
  if (!finishSound) {
    finishSound = new Audio(finishSoundUrl);
    finishSound.preload = "auto";
    finishSound.volume = finishSoundVolume;
  }
  return finishSound;
}

function prepareFinishSound() {
  try {
    const audio = getFinishSound();
    audio.pause();
    audio.currentTime = 0;
    audio.muted = true;
    const promise = audio.play();
    if (promise && promise.then) {
      promise.then(() => {
        audio.pause();
        audio.currentTime = 0;
        audio.muted = false;
        audio.volume = finishSoundVolume;
      }).catch(() => {
        audio.muted = false;
        audio.volume = finishSoundVolume;
        audio.load();
      });
    } else {
      audio.pause();
      audio.currentTime = 0;
      audio.muted = false;
      audio.volume = finishSoundVolume;
    }
  } catch (e) {}
}

function playFinishSound(jobId) {
  if (jobId && notifiedJobs[jobId]) return;
  if (jobId) notifiedJobs[jobId] = true;
  try {
    const audio = getFinishSound();
    audio.pause();
    audio.currentTime = 0;
    audio.muted = false;
    audio.volume = finishSoundVolume;
    const promise = audio.play();
    if (promise && promise.catch) promise.catch(() => {});
  } catch (e) {}
}

function setStatus(text) {
  const last = document.getElementById("lastAction");
  if (last) last.textContent = text || "Listo";
}

function setQbitToggleState(enabled, busy = false) {
  qbitSearchEnabled = !!enabled;
  const btn = document.getElementById("qbitToggle");
  if (!btn) return;
  btn.classList.toggle("is-on", qbitSearchEnabled && !busy);
  btn.classList.toggle("is-off", !qbitSearchEnabled && !busy);
  btn.classList.toggle("is-busy", !!busy);
  btn.disabled = !!busy;
  btn.textContent = qbitSearchEnabled ? "qB ON" : "qB OFF";
  btn.title = qbitSearchEnabled
    ? "qBittorrent activo para la siguiente búsqueda"
    : "qBittorrent desactivado para la siguiente búsqueda";
  btn.setAttribute("aria-pressed", qbitSearchEnabled ? "true" : "false");
}

async function loadQbitToggle() {
  try {
    const res = await fetch("/api/qbit-toggle", { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "No se pudo leer qBit");
    setQbitToggleState(data.enabled !== false, false);
  } catch (e) {
    setQbitToggleState(true, false);
  }
}

async function toggleQbitSearch(btn = null) {
  const nextEnabled = !(btn && btn.getAttribute("aria-pressed") === "true");
  setQbitToggleState(nextEnabled, true);
  try {
    const res = await fetch("/api/qbit-toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: nextEnabled })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "No se pudo guardar qBit");
    setQbitToggleState(data.enabled !== false, false);
    setStatus((data.enabled !== false) ? "qBit activado" : "Solo RD");
  } catch (e) {
    setQbitToggleState(qbitSearchEnabled, false);
    setStatus("Error qBit");
  }
}

function saveFormState() {
  try {
    const data = {
      query: document.getElementById("bQuery").value,
      pages: document.getElementById("bPages").value,
      mode: document.getElementById("bMode").value,
      minGb: document.getElementById("bMinGb").value
    };
    localStorage.setItem(formStoreKey, JSON.stringify(data));
  } catch (e) {}
}

function restoreFormState() {
  formStateRestored = false;
  const query = document.getElementById("bQuery");
  const pages = document.getElementById("bPages");
  const mode = document.getElementById("bMode");
  const minGb = document.getElementById("bMinGb");
  let data = null;
  try {
    data = JSON.parse(localStorage.getItem(formStoreKey) || "null");
  } catch (e) {}
  if (data && typeof data === "object") {
    if (query) query.value = data.query || "2160p";
    if (pages && data.pages !== undefined) pages.value = data.pages;
    if (mode && data.mode !== undefined) mode.value = data.mode;
    if (minGb && data.minGb !== undefined) minGb.value = data.minGb;
    formStateRestored = true;
    return;
  }
  if (query) query.value = "2160p";
}

function settingsVisible() {
  const view = document.getElementById("settingsView");
  return !!view && !view.classList.contains("hidden");
}

function historyVisible() {
  const view = document.getElementById("historyView");
  return !!view && !view.classList.contains("hidden");
}

function setSettingsSectionCollapsed(sectionId, collapsed) {
  const section = document.getElementById(sectionId);
  if (!section) return;
  const body = section.querySelector(".settings-section-body");
  const head = section.querySelector(".settings-section-head");
  const toggle = section.querySelector(".settings-section-toggle");
  if (body) body.classList.toggle("is-hidden", collapsed);
  if (toggle) toggle.classList.toggle("is-collapsed", collapsed);
  if (head) head.setAttribute("aria-expanded", collapsed ? "false" : "true");
}

function toggleSettingsSection(sectionId) {
  const section = document.getElementById(sectionId);
  if (!section) return;
  const body = section.querySelector(".settings-section-body");
  const collapsed = !body || body.classList.contains("is-hidden");
  setSettingsSectionCollapsed(sectionId, !collapsed);
}

function collapseSettingsSections() {
  setSettingsSectionCollapsed("settingsGeneralSection", true);
  setSettingsSectionCollapsed("settingsRdSection", true);
  setSettingsSectionCollapsed("rdFollowSection", true);
  setSettingsSectionCollapsed("settingsTvRulesSection", true);
}

function setSettingsView(show, persist = true) {
  const main = document.getElementById("mainView");
  const settings = document.getElementById("settingsView");
  const history = document.getElementById("historyView");
  const toggle = document.getElementById("settingsToggle");
  const historyToggle = document.getElementById("historyToggle");
  if (!main || !settings) return;
  main.classList.toggle("hidden", show);
  settings.classList.toggle("hidden", !show);
  if (history) history.classList.add("hidden");
  if (toggle) {
    toggle.classList.toggle("is-active", show);
    toggle.title = show ? "Volver a b\u00fasqueda" : "Ajustes";
    toggle.setAttribute("aria-pressed", show ? "true" : "false");
  }
  if (historyToggle) {
    historyToggle.classList.remove("is-active");
    historyToggle.setAttribute("aria-pressed", "false");
  }
  if (persist) {
    try { localStorage.setItem(viewStoreKey, show ? "settings" : "main"); } catch (e) {}
  }
  if (show) {
    loadSettings(false);
  }
}

function toggleSettingsView() {
  setSettingsView(!settingsVisible(), true);
}

function setHistoryView(show, persist = true) {
  const main = document.getElementById("mainView");
  const settings = document.getElementById("settingsView");
  const history = document.getElementById("historyView");
  const toggle = document.getElementById("historyToggle");
  const settingsToggle = document.getElementById("settingsToggle");
  if (!main || !history) return;
  main.classList.toggle("hidden", show);
  history.classList.toggle("hidden", !show);
  if (settings) settings.classList.add("hidden");
  if (toggle) {
    toggle.classList.toggle("is-active", show);
    toggle.title = show ? "Volver a b\u00fasqueda" : "Historial";
    toggle.setAttribute("aria-pressed", show ? "true" : "false");
  }
  if (settingsToggle) {
    settingsToggle.classList.remove("is-active");
    settingsToggle.setAttribute("aria-pressed", "false");
  }
  if (persist) {
    try { localStorage.setItem(viewStoreKey, show ? "history" : "main"); } catch (e) {}
  }
  if (show) loadHistory(false);
}

function toggleHistoryView() {
  setHistoryView(!historyVisible(), true);
}

function restoreViewState() {
  setSettingsView(false, false);
}

function setActivityCollapsed(collapsed, persist = true) {
  const log = document.getElementById("log-btdigg");
  const btn = document.getElementById("activityToggle");
  if (!log || !btn) return;
  log.classList.toggle("is-hidden", collapsed);
  btn.classList.toggle("is-collapsed", collapsed);
  btn.textContent = "\u25be";
  btn.title = collapsed ? "Mostrar actividad" : "Ocultar actividad";
  btn.setAttribute("aria-pressed", collapsed ? "true" : "false");
  if (persist) {
    try { localStorage.setItem(activityStoreKey, collapsed ? "collapsed" : "open"); } catch (e) {}
  }
}

function toggleActivity() {
  const log = document.getElementById("log-btdigg");
  setActivityCollapsed(!(log && log.classList.contains("is-hidden")), true);
}

function restoreActivityState() {
  let collapsed = false;
  try {
    collapsed = localStorage.getItem(activityStoreKey) === "collapsed";
  } catch (e) {}
  setActivityCollapsed(collapsed, false);
}

function setRdFollowCollapsed(collapsed, persist = true) {
  const log = document.getElementById("rdFollowLog");
  const btn = document.getElementById("rdFollowToggle");
  rdFollowCollapsed = !!collapsed;
  if (log) log.classList.toggle("is-hidden", rdFollowCollapsed);
  if (btn) {
    btn.classList.toggle("is-collapsed", rdFollowCollapsed);
    btn.textContent = "\u25be";
    btn.title = rdFollowCollapsed ? "Mostrar seguimiento" : "Ocultar seguimiento";
    btn.setAttribute("aria-pressed", rdFollowCollapsed ? "true" : "false");
  }
  if (persist) {
    try { localStorage.setItem(rdFollowStoreKey, rdFollowCollapsed ? "collapsed" : "open"); } catch (e) {}
  }
}

function toggleRdFollow() {
  const log = document.getElementById("rdFollowLog");
  setRdFollowCollapsed(!(log && log.classList.contains("is-hidden")), true);
}

function restoreRdFollowState() {
  let collapsed = false;
  try {
    collapsed = localStorage.getItem(rdFollowStoreKey) === "collapsed";
  } catch (e) {}
  setRdFollowCollapsed(collapsed, false);
  restoreRdFollowTestState();
}

function setRdFollowStatus(text, tone = "mid") {
  const status = document.getElementById("rdFollowStatus");
  if (!status) return;
  status.className = "status-pill " + tone;
  status.textContent = text || "Esperando";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderRdFollowMetrics(summary) {
  const box = document.getElementById("rdFollowMetrics");
  if (!box) return;
  const run = summary?.run || {};
  const progress = summary?.progress || {};
  const rd = summary?.rd_counts || {};
  const rate = summary?.rate || {};
  const pacer = summary?.pacer || {};
  const cleanup = summary?.cleanup || {};
  const active = summary?.active_count || {};
  const by429 = pacer["429_by_group"] || {};
  const parts = [];
  const addMetric = (label, value, tone = "") => {
    if (value === undefined || value === null || value === "") return;
    parts.push('<div class="rd-follow-metric ' + tone + '"><span>' + escapeHtml(label) + '</span><strong>' + escapeHtml(String(value)) + '</strong></div>');
  };
  addMetric("Estado", run.status || summary?.operation_status || summary?.diagnostic_status || "-");
  addMetric("Tiempo", summary?.elapsed_sec ? String(summary.elapsed_sec) + " s" : "-");
  addMetric("Busqueda", run.query || "-");
  addMetric("Paginas", run.pages || "-");
  if (Number(progress.total || 0) > 0) {
    addMetric("Progreso", String(progress.done || 0) + "/" + String(progress.total || 0));
  }
  addMetric("RD OK", rd.RD_OK || 0, Number(rd.RD_OK || 0) ? "good" : "");
  addMetric("No instant", rd.NO_INSTANT || 0);
  addMetric("Pack fuera", rd.PACK_SIN_COINCIDENCIA || 0);
  addMetric("429", Object.values(by429).reduce((a, b) => a + Number(b || 0), 0), Object.values(by429).some(v => Number(v || 0) > 0) ? "warn" : "");
  addMetric("API", String(rate.api_calls_total || 0) + " / pico " + String(rate.max_window_count || 0));
  addMetric("Limpieza", "P" + String(cleanup.pending || 0) + " L" + String(cleanup.leftover || 0), (Number(cleanup.pending || 0) || Number(cleanup.leftover || 0)) ? "warn" : "");
  addMetric("Activos RD", String(active?.before?.nb ?? "-") + ">" + String(active?.after?.nb ?? "-") + "/" + String(active?.after?.limit ?? active?.before?.limit ?? "-"), Number(active?.after?.nb || 0) ? "warn" : "");
  box.innerHTML = parts.join("");
}

function rdFollowSafeTone(value, fallback = "neutral") {
  const tone = String(value || fallback).replace(/[^a-z0-9_-]/gi, "").toLowerCase();
  return tone || fallback;
}

function rdFollowMarkerLabel(item, tone, level, kind) {
  if (kind !== "advice" && level !== "warn" && level !== "error") return "";
  const badge = String(item.badge || "").trim();
  if (badge && !["OK", "RD", "Aviso", "Consejo"].includes(badge)) return badge;
  if (tone === "principal") return "Principal";
  if (tone === "secundario") return "Secundario";
  if (tone === "avanzado") return "Avanzado";
  if (tone === "ajuste") return "Ajuste";
  return kind === "advice" ? "Consejo" : "Aviso";
}

function appendRdFollowLine(box, item) {
  const div = document.createElement("div");
  const level = String(item.level || "info");
  const kind = String(item.kind || "info").replace(/[^a-z0-9_-]/gi, "");
  const tone = rdFollowSafeTone(item.tone, level === "ok" ? "ok" : level === "warn" ? "principal" : "neutral");
  div.className = "line rd-follow-line rd-follow-kind-" + kind + " rd-follow-tone-" + tone;
  if (item.line_id) div.dataset.lineId = item.line_id;
  if (item.source_event_id) div.dataset.eventId = item.source_event_id;
  if (item.source_event) div.dataset.sourceEvent = item.source_event;
  if (item.internal_code) div.title = item.internal_code;
  if (level === "ok") div.classList.add("is-ok");
  else if (level === "warn") div.classList.add("is-warn");
  else if (level === "error") div.classList.add("is-err");

  const text = document.createElement("span");
  text.className = "rd-follow-text";
  text.textContent = item.text || "";

  const marker = document.createElement("span");
  marker.className = "rd-follow-marker rd-follow-marker-" + tone;
  marker.textContent = rdFollowMarkerLabel(item, tone, level, kind);

  const seconds = document.createElement("span");
  seconds.className = "rd-follow-seconds";
  seconds.textContent = item.elapsed || item.ts || "--";

  div.appendChild(marker);
  div.appendChild(text);
  div.appendChild(seconds);
  box.appendChild(div);
}

function renderRdFollowLines() {
  const box = document.getElementById("rdFollowLog");
  if (!box) return;
  box.innerHTML = "";
  const baseLines = rdFollowLines.slice(-130);
  const advice = (rdFollowAdvice || []).filter(Boolean).slice(0, 3).map(item => {
    if (typeof item === "string") {
      return {
        elapsed: "FINAL",
        level: "info",
        kind: "advice",
        badge: "Consejo",
        tone: "ajuste",
        text: item
      };
    }
    return {
      elapsed: "FINAL",
      level: item.level || "warn",
      kind: item.kind || "advice",
      badge: item.badge || "Consejo",
      tone: item.tone || "ajuste",
      text: item.text || "",
      advice_id: item.advice_id || "",
      rule_id: item.rule_id || "",
      config_targets: item.config_targets || [],
      evidence: item.evidence || {}
    };
  });
  const lines = advice.length && baseLines.length ? baseLines.concat(advice) : baseLines;
  if (!lines.length) {
    appendRdFollowLine(box, {
      elapsed: "+0.0s",
      level: "info",
      kind: "start",
      tone: "neutral",
      text: "Sin señales RD todavía. Cuando arranque el motor aparecerá aquí."
    });
    return;
  }
  lines.forEach(item => {
    appendRdFollowLine(box, item);
  });
  box.scrollTop = box.scrollHeight;
}

function renderRdFollowPayload(follow) {
  if (!follow) return;
  renderRdFollowMetrics(follow.summary || {});
  const summary = follow.summary || {};
  rdFollowAdvice = Array.isArray(summary.advice) ? summary.advice : [];
  const lines = follow.lines || [];
  if (lines.length) {
    lines.forEach(item => {
      const key = String(item.line_id || item.source_event_id || "");
      const duplicated = key ? rdFollowLines.slice(-80).some(prev => String(prev.line_id || prev.source_event_id || "") === key) : false;
      if (!duplicated) rdFollowLines.push(item);
    });
    rdFollowLines = rdFollowLines.slice(-220);
  }
  renderRdFollowLines();
  if (!follow.has_diagnostics) {
    setRdFollowStatus("Esperando RD", "mid");
  } else if (String(follow.job_status || "").toLowerCase() === "done" || summary.operation_status === "ok") {
    setRdFollowStatus("Terminado", "good");
  } else if (String(follow.job_status || "").toLowerCase() === "error" || summary.operation_status === "error") {
    setRdFollowStatus("Error", "bad");
  } else {
    setRdFollowStatus("En vivo", "good");
  }
}

async function fetchRdFollow(finalRead = false) {
  if (!rdFollowJobId) return false;
  try {
    const base = rdFollowTraceKind === "rd_test" ? "/api/rd-test/job/" : "/api/job/";
    const suffix = rdFollowTraceKind === "rd_test" ? "/follow" : "/rd-follow";
    const response = await fetch(base + encodeURIComponent(rdFollowJobId) + suffix + "?after=" + encodeURIComponent(rdFollowCursor), { cache: "no-store" });
    const data = await response.json();
    if (!data.ok || !data.follow) {
      if (!finalRead) setRdFollowStatus("Sin datos", "mid");
      return false;
    }
    renderRdFollowPayload(data.follow);
    rdFollowCursor = Number(data.follow.cursor || rdFollowCursor || 0);
    const status = String(data.follow.job_status || "").toLowerCase();
    if (status === "done" || status === "error") stopRdFollow(false);
    return true;
  } catch (e) {
    if (!finalRead) setRdFollowStatus("Sin conexión", "bad");
    return false;
  }
}

function startRdFollow(jobId, reset = true, traceKind = "job") {
  if (!jobId) return;
  if (rdFollowTimer) clearInterval(rdFollowTimer);
  rdFollowJobId = String(jobId);
  rdFollowTraceKind = traceKind || "job";
  if (reset || rdFollowCursor < 0) {
    rdFollowCursor = 0;
    rdFollowLines = [];
    rdFollowAdvice = [];
  }
  setRdFollowStatus("Conectando", "mid");
  renderRdFollowLines();
  fetchRdFollow();
  rdFollowTimer = setInterval(() => fetchRdFollow(), 1000);
}

function stopRdFollow(clear = false) {
  if (rdFollowTimer) clearInterval(rdFollowTimer);
  rdFollowTimer = null;
  if (clear) {
    rdFollowJobId = null;
    rdFollowTraceKind = "job";
    rdFollowCursor = 0;
    rdFollowLines = [];
    rdFollowAdvice = [];
    renderRdFollowMetrics({});
    renderRdFollowLines();
    setRdFollowStatus("Esperando", "mid");
  }
}

function finishRdFollow(jobId) {
  if (jobId && rdFollowJobId && String(jobId) !== String(rdFollowJobId)) return;
  setTimeout(() => fetchRdFollow(true).finally(() => stopRdFollow(false)), 700);
}

function saveRdFollowTestState() {
  try {
    const data = {
      query: document.getElementById("rdFollowQuery")?.value || "",
      pages: document.getElementById("rdFollowPages")?.value || "1-1"
    };
    localStorage.setItem(rdFollowTestStoreKey, JSON.stringify(data));
  } catch (e) {}
}

function restoreRdFollowTestState() {
  let data = null;
  try { data = JSON.parse(localStorage.getItem(rdFollowTestStoreKey) || "null"); } catch (e) {}
  const query = document.getElementById("rdFollowQuery");
  const pages = document.getElementById("rdFollowPages");
  if (query) query.value = data?.query || "2160p";
  if (pages) pages.value = data?.pages || "1-1";
}

function rdFollowClearTest(btn = null) {
  const query = document.getElementById("rdFollowQuery");
  const pages = document.getElementById("rdFollowPages");
  if (query) query.value = "2160p";
  if (pages) pages.value = "1-1";
  stopRdFollow(true);
  saveRdFollowTestState();
  setRdFollowStatus("Limpio", "mid");
  setActionButtonState(btn, "done", "OK");
}

async function rdFollowExportTest(btn = null) {
  if (!rdFollowJobId || rdFollowTraceKind !== "rd_test") {
    setRdFollowStatus("Sin prueba RD", "mid");
    setActionButtonState(btn, "error", "!");
    return;
  }
  setActionButtonState(btn, "loading");
  try {
    const response = await fetch("/api/rd-test/job/" + encodeURIComponent(rdFollowJobId) + "/export", { method: "POST" });
    const data = await response.json();
    if (!data.ok) {
      setRdFollowStatus(data.error || "No exportó", "bad");
      setActionButtonState(btn, "error", "!");
      return;
    }
    setRdFollowStatus("ZIP creado", "good");
    setActionButtonState(btn, "done", "OK");
  } catch (e) {
    setRdFollowStatus("Sin conexión", "bad");
    setActionButtonState(btn, "error", "!");
  }
}

async function rdFollowStartTest(btn = null) {
  const query = (document.getElementById("rdFollowQuery")?.value || "").trim();
  if (!query) {
    setRdFollowStatus("Falta título", "bad");
    setActionButtonState(btn, "error", "!");
    return;
  }
  saveRdFollowTestState();
  setActionButtonState(btn, "loading");
  setRdFollowStatus("Arrancando", "mid");
  try {
    const payload = {
      module: "btdigg",
      action: "rd_tuning",
      query,
      pages: document.getElementById("rdFollowPages")?.value || "1-1"
    };
    const response = await fetch("/api/rd-test/job", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await response.json();
    if (!data.ok) {
      setRdFollowStatus(data.error || "No arrancÃ³", "bad");
      setActionButtonState(btn, "error", "!");
      if (data.running_job_id) startRdFollow(data.running_job_id, true, data.running_kind || "job");
      return;
    }
    startRdFollow(data.run_id || data.job_id, true, "rd_test");
    setActionButtonState(btn, "done", "OK");
  } catch (e) {
    setRdFollowStatus("Sin conexiÃ³n", "bad");
    setActionButtonState(btn, "error", "!");
  }
}

function resetStartupMemory() {
  try {
    localStorage.removeItem(viewStoreKey);
  } catch (e) {}
}

function formatLiveLine(line) {
  let l = String(line || "").trim();
  if (!l || /^=+$/.test(l)) return null;
  const hideContains = [
    "Comando interno preparado",
    "ARRANQUE MOTOR",
    "Editor Maestro",
    "opci\u00f3n 1 limpia",
    "Escribe abajo",
    "RESULTADOS LISTOS",
    "Resultados guardados para el Editor",
    "Links qB/RD PRO actualizado",
    "/app/tools/",
    "Solo se ense\u00f1ar\u00e1n vivos reales"
  ];
  if (hideContains.some(x => l.includes(x))) return null;
  if (/^https?:\/\//i.test(l)) return null;
  if (/^archivo RD:/i.test(l)) return null;
  if (/^archivo BTDigg:/i.test(l)) return null;
  if (/^\[\d+\]\s+RD:/i.test(l)) return null;
  if (/^\[Q\d+\]/i.test(l)) return null;
  if (/^\[T\d+\]/i.test(l)) return null;
  if (/^TOP LIMPIO$/i.test(l)) return null;
  if (/^Elige:/i.test(l)) return null;
  if (/^Historial qB actualizado:/i.test(l)) return null;
  if (/^Real-Debrid temporal limpio:/i.test(l)) return null;
  if (/^qBit vivo:\s*QBT_VIVO\s*\|/i.test(l)) return null;

  let m = l.match(/^Navegador autom.tico p.gina\s+(\d+)\s+\((\d+)\/(\d+)\):/i);
  if (m) return `BTDigg: revisando p\u00e1gina ${m[2]}/${m[3]}...`;
  m = l.match(/^Token Real-Debrid OK:/i);
  if (m) return "Real-Debrid OK.";
  m = l.match(/^Encontrados\s+(\d+)\s+resultados brutos/i);
  if (m) return `Encontrados ${m[1]} candidatos. Filtrando...`;
  m = l.match(/^qBit progreso:\s*(\d+)\/(\d+)\s+comprobados\s+\|\s+vivos\s+(\d+)/i);
  if (m) return `qBit: ${m[1]}/${m[2]} comprobados | vivos ${m[3]}`;
  m = l.match(/^qBit vivo\s+(\d+)\/(\d+):\s*(.+)$/i);
  if (m) return `qBit vivo ${m[1]}/${m[2]}: ${m[3]}`;
  m = l.match(/^Cola RD\s+\d+\/\d+:/i);
  if (m) return null;
  m = l.match(/^RD cola comprobados:/i);
  if (m) return null;
  m = l.match(/^RD OK\s+(\d+)\/(\d+):\s*(.+)$/i);
  if (m) return `${rdOkVerifyTitleMarker}Verificando ${m[1]}/${m[2]}: ${m[3]}`;
  m = l.match(/^Resultados v.lidos para JDownloader\/RD:\s*(.+)$/i);
  if (m) return `Resultados v\u00e1lidos RD: ${m[1]}`;
  m = l.match(/^Lista extra qBittorrent vivos reales:\s*(.+)$/i);
  if (m) return `Lista extra qBittorrent vivos: ${m[1]}`;
  m = l.match(/^B.SQUEDA:\s*(.+)$/i);
  if (m) return `B\u00fasqueda: ${m[1]}`;
  m = l.match(/^BTDigg \+ RD/i);
  if (m) return "BTDigg + RD preparado.";
  if (l.length > 190) l = l.slice(0, 190) + "...";
  return l;
}

function cleanLines(lines) {
  const out = [];
  for (const raw of (lines || [])) {
    const line = formatLiveLine(raw);
    if (!line) continue;
    if (out[out.length - 1] !== line) out.push(line);
  }
  return out.slice(-80);
}

function addLogPart(parent, text, className) {
  if (!text) return;
  const span = document.createElement("span");
  if (className) span.className = className;
  span.textContent = text;
  parent.appendChild(span);
}

function paintMetricLine(div, line) {
  const parts = String(line || "").split(/(RD_OK=\d+|RD_ERROR=\d+|RD_FAIL=\d+|NO_INSTANT=\d+|PACK_SIN_COINCIDENCIA=\d+|qB vivos=\d+|RD listos=\d+)/g);
  parts.forEach(part => {
    if (!part) return;
    if (/^(RD_OK|RD listos)=/i.test(part)) addLogPart(div, part, "log-part-rd");
    else if (/^(qB vivos)=/i.test(part)) addLogPart(div, part, "log-part-qbit");
    else if (/^(RD_ERROR|RD_FAIL)=/i.test(part)) addLogPart(div, part, "log-part-err");
    else if (/^(NO_INSTANT|PACK_SIN_COINCIDENCIA)=/i.test(part)) addLogPart(div, part, "log-part-warn");
    else addLogPart(div, part);
  });
}

function renderLogLine(div, line) {
  let text = String(line || "");
  const rdOkVerifyTitle = text.startsWith(rdOkVerifyTitleMarker);
  if (rdOkVerifyTitle) text = text.slice(rdOkVerifyTitleMarker.length);
  const lower = text.toLowerCase();
  let match = text.match(/^(Verificando\s+\d+\/\d+:\s*)(.+)$/i);
  if (match) {
    addLogPart(div, match[1], "log-part-work");
    addLogPart(div, match[2], rdOkVerifyTitle ? "log-part-ok" : "");
    return;
  }
  match = text.match(/^(qBit:\s*)(.+)$/i);
  if (match) {
    addLogPart(div, match[1], "log-part-qbit");
    addLogPart(div, match[2]);
    return;
  }
  match = text.match(/^(P.ginas:\s*)(.+)$/i);
  if (match) {
    addLogPart(div, match[1]);
    addLogPart(div, match[2], "log-part-warn");
    return;
  }
  match = text.match(/^(BTDigg:\s*revisando p.gina\s+)(\d+\/\d+)(.*)$/i);
  if (match) {
    addLogPart(div, match[1]);
    addLogPart(div, match[2], "log-part-warn");
    addLogPart(div, match[3]);
    return;
  }
  match = text.match(/^(Rescate DOM:\s*)(\d+)(\s+magnets encontrados.*)$/i);
  if (match) {
    addLogPart(div, match[1]);
    addLogPart(div, match[2], "log-part-warn");
    addLogPart(div, match[3]);
    return;
  }
  match = text.match(/^(Criba b.squeda seria:\s*)(\d+\/\d+.*)$/i);
  if (match) {
    addLogPart(div, match[1]);
    addLogPart(div, match[2], "log-part-warn");
    return;
  }
  if (/^Resumen RD:/i.test(text) || /^Links qB\/RD PRO actualizado:/i.test(text)) {
    paintMetricLine(div, text);
    return;
  }
  if (/^qBit vivo\b/i.test(text) || /^Lista extra qBittorrent vivos\b/i.test(text)) {
    div.classList.add("is-qbit-strong");
    addLogPart(div, text);
    return;
  }
  if (/^Resultados v.lidos RD:/i.test(text) || /^Resultados v.lidos para JDownloader\/RD:/i.test(text)) {
    div.classList.add("is-rd-strong");
    addLogPart(div, text);
    return;
  }
  if (/^Real-Debrid OK\.?$/i.test(text)) {
    div.classList.add("is-rd-strong");
    addLogPart(div, text);
    return;
  }
  if (/^Listo\. Resultados cargados:/i.test(text)) {
    div.classList.add("is-warn");
    addLogPart(div, text);
    return;
  }
  if (/^(ERROR|FALLO)\b/i.test(text) || /\b(error grave|fallo real)\b/i.test(lower)) {
    div.classList.add("is-err");
    addLogPart(div, text);
    return;
  }
  if (/^(Aviso|Descartado)\b/i.test(text)) {
    div.classList.add("is-warn");
    addLogPart(div, text);
    return;
  }
  if (/\b(RD OK|Real-Debrid OK|qBit OK|Enviado OK|Listo|RESULTADOS LISTOS|Resultados cargados)\b/i.test(text)) {
    div.classList.add("is-ok");
    addLogPart(div, text);
    return;
  }
  addLogPart(div, text);
}

function renderLog(module) {
  const box = document.getElementById("log-" + module);
  if (!box) return;
  box.innerHTML = "";
  cleanLines(moduleLogs[module] || []).forEach(line => {
    const div = document.createElement("div");
    div.className = "line";
    renderLogLine(div, line);
    box.appendChild(div);
  });
  box.scrollTop = box.scrollHeight;
}

function clearCurrent() {
  const query = document.getElementById("bQuery");
  if (query) query.value = "2160p";
  moduleResults.btdigg = [];
  moduleLogs.btdigg = ["Limpio. Preparado."];
  renderLog("btdigg");
  renderResults([]);
  stopRdFollow(true);
  setStatus("Limpio");
  saveFormState();
}

function closeLive(module) {
  try {
    if (liveStreams[module]) liveStreams[module].close();
  } catch (e) {}
  liveStreams[module] = null;
}

function saveActiveJob(id, module = "btdigg") {
  if (!id) return;
  activeJobIds[module] = id;
  try {
    localStorage.setItem(activeJobStoreKey, JSON.stringify({
      id,
      module,
      savedAt: Date.now()
    }));
  } catch (e) {}
}

function storedActiveJob() {
  try {
    const raw = localStorage.getItem(activeJobStoreKey);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!data || !data.id) return null;
    return { id: String(data.id), module: String(data.module || "btdigg") };
  } catch (e) {
    return null;
  }
}

function clearActiveJob(id = null, module = "btdigg") {
  if (!id || activeJobIds[module] === id) activeJobIds[module] = null;
  try {
    const current = storedActiveJob();
    if (!id || (current && current.id === id)) localStorage.removeItem(activeJobStoreKey);
  } catch (e) {}
}

function applyJobSnapshot(job, module = "btdigg", options = {}) {
  if (!job) return false;
  const status = String(job.status || "queued");
  const id = String(job.id || "");
  const traceKind = String(job.kind || "job");
  activeModule = module;
  moduleLogs[module] = job.log || [];
  renderLog(module);
  if (status === "done" || status === "error") {
    closeLive(module);
    moduleBusy[module] = false;
    moduleResults[module] = job.results || [];
    renderResults(moduleResults[module]);
    historyCache = null;
    setStatus(status === "done" ? "Terminado" : "Error");
    clearActiveJob(id, module);
    if (id) startRdFollow(id, true, traceKind);
    finishRdFollow(id);
    if (options.notify) playFinishSound(id);
    return true;
  }
  moduleBusy[module] = true;
  saveActiveJob(id, module);
  startRdFollow(id, true, traceKind);
  setStatus(status === "running" ? "Trabajando LIVE..." : "En cola...");
  return true;
}

async function resumeJob(id, module = "btdigg", options = {}) {
  if (!id) return false;
  if (moduleBusy[module] && activeJobIds[module] === id && liveStreams[module]) return true;
  try {
    const response = await fetch("/api/job/" + encodeURIComponent(id));
    const data = await response.json();
    if (!data.ok || !data.job) {
      clearActiveJob(id, module);
      return false;
    }
    const status = String(data.job.status || "");
    if (status === "done" || status === "error") {
      applyJobSnapshot(data.job, module, options);
      return true;
    }
    activeModule = module;
    moduleBusy[module] = true;
    saveActiveJob(id, module);
    startRdFollow(id, false, String(data.job.kind || "job"));
    setStatus(status === "running" ? "Trabajando LIVE..." : "En cola...");
    if (!liveStreams[module]) {
      moduleLogs[module] = ["Reconectando actividad LIVE..."];
      renderLog(module);
      openLive(id, module);
    }
    return true;
  } catch (e) {
    return false;
  }
}

async function reconnectActiveJob() {
  const saved = storedActiveJob();
  if (saved && await resumeJob(saved.id, saved.module)) return true;
  try {
    const response = await fetch("/api/job/active");
    const data = await response.json();
    if (data.ok && data.active && data.job && data.job.id) {
      return await resumeJob(data.job.id, data.job.module || "btdigg");
    }
  } catch (e) {}
  return false;
}

function pushLog(module, line) {
  if (!moduleLogs[module]) moduleLogs[module] = [];
  moduleLogs[module].push(line);
  if (moduleLogs[module].length > 650) moduleLogs[module] = moduleLogs[module].slice(-650);
  renderLog(module);
}

async function start(payload) {
  const module = payload.module || "btdigg";
  activeModule = module;
  saveFormState();

  if (moduleBusy[module]) {
    setStatus("Ya est\u00e1 trabajando");
    pushLog(module, "Aviso: BTDigg + RD ya est\u00e1 trabajando. Espera a que termine.");
    return;
  }

  prepareFinishSound();
  moduleBusy[module] = true;
  closeLive(module);
  setStatus("Trabajando LIVE...");
  moduleLogs[module] = ["Conectando actividad LIVE..."];
  renderLog(module);

  try {
    const response = await fetch("/api/job", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await response.json();
    if (!data.ok) {
      if (data.running_job_id) {
        pushLog(module, "Reconectando con la b\u00fasqueda que ya est\u00e1 trabajando...");
        await resumeJob(data.running_job_id, module);
        return;
      }
      moduleBusy[module] = false;
      setStatus("Error");
      pushLog(module, "ERROR: " + (data.error || "no se pudo arrancar"));
      return;
    }
    saveActiveJob(data.job_id, module);
    startRdFollow(data.job_id, true);
    openLive(data.job_id, module);
  } catch (e) {
    moduleBusy[module] = false;
    setStatus("Error");
    pushLog(module, "ERROR arrancando buscador: " + e);
  }
}

function openLive(id, module) {
  saveActiveJob(id, module);
  if (!window.EventSource) {
    pushLog(module, "Aviso: navegador sin LIVE real. Uso modo seguro.");
    poll(id, module);
    return;
  }
  let finished = false;
  const es = new EventSource("/api/job/" + encodeURIComponent(id) + "/stream");
  liveStreams[module] = es;

  es.addEventListener("log", ev => {
    try {
      const data = JSON.parse(ev.data || "{}");
      if (data.line) pushLog(module, data.line);
    } catch (e) {}
  });
  es.addEventListener("status", ev => {
    try {
      const data = JSON.parse(ev.data || "{}");
      if (data.status === "running") setStatus("Trabajando LIVE...");
      if (data.status === "queued") setStatus("En cola...");
    } catch (e) {}
  });
  es.addEventListener("done", ev => {
    finished = true;
    let data = {};
    try { data = JSON.parse(ev.data || "{}"); } catch (e) {}
    closeLive(module);
    moduleBusy[module] = false;
    setStatus(data.status === "done" ? "Terminado" : "Error");
    moduleResults[module] = data.results || [];
    renderResults(moduleResults[module]);
    historyCache = null;
    clearActiveJob(id, module);
    finishRdFollow(id);
    playFinishSound(id);
  });
  es.onerror = () => {
    if (finished) return;
    closeLive(module);
    pushLog(module, "Aviso: canal LIVE cortado. Sigo por modo seguro.");
    setStatus("Modo seguro...");
    poll(id, module);
  };
}

async function poll(id, module) {
  let done = false;
  while (!done) {
    const response = await fetch("/api/job/" + encodeURIComponent(id));
    const data = await response.json();
    if (data.ok) {
      moduleLogs[module] = data.job.log || [];
      renderLog(module);
      if (data.job.status === "done" || data.job.status === "error") {
        done = true;
        moduleBusy[module] = false;
        setStatus(data.job.status === "done" ? "Terminado" : "Error");
        moduleResults[module] = data.job.results || [];
        renderResults(moduleResults[module]);
        historyCache = null;
        clearActiveJob(id, module);
        finishRdFollow(id);
        playFinishSound(id);
      }
    }
    if (!done) await new Promise(resolve => setTimeout(resolve, 1000));
  }
}

function searchBT() {
  start({
    module: "btdigg",
    action: "search",
    query: document.getElementById("bQuery").value,
    pages: document.getElementById("bPages").value,
    mode: document.getElementById("bMode").value,
    min_gb: document.getElementById("bMinGb").value
  });
}

function setActionButtonState(btn, state, label) {
  if (!btn) return;
  if (!btn.dataset.originalHtml) btn.dataset.originalHtml = btn.innerHTML;
  if (!btn.dataset.originalWidth) {
    const rect = btn.getBoundingClientRect();
    if (rect.width) {
      btn.dataset.originalWidth = String(Math.ceil(rect.width));
      btn.style.minWidth = btn.dataset.originalWidth + "px";
    }
  }
  btn.classList.remove("is-loading", "is-done", "is-error");
  if (state === "loading") {
    btn.disabled = true;
    btn.classList.add("is-loading");
    btn.innerHTML = '<span class="btn-spinner"></span>';
    return;
  }
  if (state === "done") {
    btn.disabled = true;
    btn.classList.add("is-done");
    btn.textContent = label || "OK";
    setTimeout(() => {
      btn.disabled = false;
      btn.classList.remove("is-done");
      btn.innerHTML = btn.dataset.originalHtml || "";
    }, 900);
    return;
  }
  if (state === "error") {
    btn.disabled = true;
    btn.classList.add("is-error");
    btn.textContent = label || "!";
    setTimeout(() => {
      btn.disabled = false;
      btn.classList.remove("is-error");
      btn.innerHTML = btn.dataset.originalHtml || "";
    }, 1200);
    return;
  }
  btn.disabled = false;
  btn.innerHTML = btn.dataset.originalHtml || btn.innerHTML;
}

function itemDownloadHash(item, link) {
  return String((item && (item.hash || item.btih || item.infohash || (item.raw && item.raw.hash))) || link || "").trim().toLowerCase();
}

function itemDownloadContract(item) {
  const raw = item && item.raw && typeof item.raw === "object" ? item.raw : {};
  return {
    rd_status: raw.rd_status || "",
    rd_existing: !!raw.rd_existing,
    rd_links: raw.rd_links || 0,
    rd_torrent_id: raw.rd_torrent_id || "",
    qbt_status: raw.qbt_status || "",
    qbt_was_existing: !!raw.qbt_was_existing,
    selected_file_name: raw.selected_file_name || "",
    selected_file_ids: raw.selected_file_ids || ""
  };
}

async function sendDownloadItem(item, btn = null, options = {}) {
  const link = item.link || item.magnet || item.url || "";
  const itemHash = itemDownloadHash(item, link);
  if (!link) {
    setStatus("Sin enlace");
    moduleLogs.btdigg = ["Esta tarjeta no trae enlace/magnet para enviar."];
    renderLog("btdigg");
    setActionButtonState(btn, "error", "!");
    return;
  }

  setActionButtonState(btn, "loading");
  setStatus("Enviando...");
    moduleLogs.btdigg = ["Resolviendo ruta de descarga...", item.title || "(sin t\u00edtulo)"];
  renderLog("btdigg");

  try {
    const response = await fetch("/api/rdt/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        module: "btdigg",
        index: item.index,
        title: item.title || "",
        link,
        hash: itemHash,
        source: item.source || item.quality || "",
        status: item.status || item.confidence || "",
        size: item.size || "",
        from_history: options.origin === "history",
        history_id: options.historyId || "",
        history_result: options.historyResult || "",
        contract: itemDownloadContract(item)
      })
    });
    const data = await response.json();
    if (data.ok) {
      moduleLogs.btdigg.push((data.engine || "Motor") + ": enviado OK.");
      if (data.trace_id) moduleLogs.btdigg.push("Trace: " + data.trace_id);
      setStatus(data.engine === "qBittorrent" ? "Enviado a qBit" : "Enviado a RDT");
      setActionButtonState(btn, "done", "OK");
    } else {
      moduleLogs.btdigg.push("ERROR: " + (data.error || "fallo enviando"));
      if (data.trace_id) moduleLogs.btdigg.push("Trace: " + data.trace_id);
      setStatus("Error env\u00edo");
      setActionButtonState(btn, "error", "!");
    }
    renderLog("btdigg");
  } catch (e) {
    moduleLogs.btdigg.push("ERROR env\u00edo: " + e);
    setStatus("Error env\u00edo");
    setActionButtonState(btn, "error", "!");
    renderLog("btdigg");
  }
}

async function downloadItem(index, btn = null) {
  const list = moduleResults.btdigg || [];
  const item = list.find(x => String(x.index) === String(index)) || list[index - 1];
  if (!item) {
    setStatus("Resultado no encontrado");
    moduleLogs.btdigg = ["No encuentro esa tarjeta en pantalla."];
    renderLog("btdigg");
    return;
  }
  return sendDownloadItem(item, btn, { origin: "current" });
}

async function downloadHistoryItem(key, btn = null) {
  const saved = historyResultStore[key];
  if (!saved || !saved.item) {
    setStatus("Historial no encontrado");
    moduleLogs.btdigg = ["No encuentro esa tarjeta guardada en historial."];
    renderLog("btdigg");
    setActionButtonState(btn, "error", "!");
    return;
  }
  return sendDownloadItem(saved.item, btn, {
    origin: "history",
    historyId: saved.historyId,
    historyResult: saved.historyResult
  });
}

async function loadResults(show = true) {
  const response = await fetch("/api/results/btdigg");
  const data = await response.json();
  moduleResults.btdigg = data.results || [];
  if (show) renderResults(moduleResults.btdigg);
}

function resultSortValue(item, key) {
  if (key === "size") return Number(item.size_value || 0);
  if (key === "seeds") return Number(item.seeds_value || item.seeds || 0);
  if (key === "peers") return Number(item.peers_value || item.peers || 0);
  if (key === "added") return Number(item.added_value || item.index || 0);
  if (key === "index") return Number(item.index || 0);
  if (key === "source") return String(item.source || item.quality || "").toLowerCase();
  if (key === "status") return String(item.status || item.confidence || "").toLowerCase();
  return String(item.title || "").toLowerCase();
}

function sortedResults(items) {
  const sort = resultSort.btdigg || { key: "index", dir: "asc" };
  const dir = sort.dir === "desc" ? -1 : 1;
  return [...(items || [])].sort((a, b) => {
    const av = resultSortValue(a, sort.key);
    const bv = resultSortValue(b, sort.key);
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
    return String(av).localeCompare(String(bv), "es", { numeric: true, sensitivity: "base" }) * dir;
  });
}

function toggleResultSort(key) {
  const current = resultSort.btdigg || { key: "index", dir: "asc" };
  const numeric = ["size", "seeds", "peers", "added"];
  const dir = current.key === key ? (current.dir === "asc" ? "desc" : "asc") : (numeric.includes(key) ? "desc" : "asc");
  resultSort.btdigg = { key, dir };
  renderResults(moduleResults.btdigg || []);
}

function resultSortMark(key) {
  const sort = resultSort.btdigg || {};
  if (sort.key !== key) return "";
  return sort.dir === "asc" ? " \u2191" : " \u2193";
}

function resultSourceClass(source) {
  const x = String(source || "").toLowerCase();
  if (x === "rd") return " source-rd";
  if (x.includes("qbit")) return " source-qbit";
  return "";
}

function resultStatusClass(status) {
  const x = String(status || "").toLowerCase();
  if (x.includes("rd")) return " rd-status";
  if (x.includes("qbit") || x.includes("vivo")) return " qbit-status";
  if (x.includes("%")) return " good";
  if (x.includes("error") || x.includes("dead") || x.includes("muerto")) return " bad";
  return " mid";
}

function translateAddedLabel(value) {
  const text = String(value || "hoy").trim();
  if (!text) return "hoy";
  const lower = text.toLowerCase();
  if (lower === "hoy" || lower === "today") return "hoy";
  if (lower === "yesterday") return "ayer";
  const m = lower.match(/^(\d+|a|an|one)\s+(second|minute|hour|day|week|month|year)s?\s+ago$/i);
  if (!m) return text;
  const amount = /^(a|an|one)$/i.test(m[1]) ? 1 : Number(m[1]);
  if (!Number.isFinite(amount) || amount <= 0) return text;
  const unit = m[2].toLowerCase();
  const labels = {
    second: ["segundo", "segundos"],
    minute: ["minuto", "minutos"],
    hour: ["hora", "horas"],
    day: ["d\u00eda", "d\u00edas"],
    week: ["semana", "semanas"],
    month: ["mes", "meses"],
    year: ["a\u00f1o", "a\u00f1os"]
  };
  const pair = labels[unit];
  if (!pair) return text;
  return "hace " + amount + " " + (amount === 1 ? pair[0] : pair[1]);
}

function historyRouteKind(item, source, status) {
  const raw = item && item.raw ? item.raw : {};
  const text = [
    source,
    status,
    item && item.quality,
    item && item.confidence,
    raw.qbt_status,
    raw.rd_status
  ].map(v => String(v || "").toLowerCase()).join(" ");
  if (text.includes("qbit") || text.includes("qbt") || text.includes("vivo")) return "qbit";
  if (text.includes("rd") || text.includes("direct")) return "rd";
  return "download";
}

function historyRouteLabel(kind) {
  if (kind === "qbit") return "qBit";
  if (kind === "rd") return "RD";
  return "Bajar";
}

function historyRouteTitle(kind) {
  if (kind === "qbit") return "Descargar por qBit";
  if (kind === "rd") return "Descargar por RD";
  return "Descargar";
}

function renderResults(items) {
  const box = document.getElementById("results");
  box.innerHTML = "";
  if (!items.length) {
    box.innerHTML = '<p class="hint" style="padding:12px">Sin resultados todav\u00eda.</p>';
    return;
  }
  const rows = sortedResults(items);
  const heads = [["title", "T\u00edtulo"], ["size", "Tama\u00f1o"], ["seeds", "Seeds"], ["peers", "Peers"], ["added", "A\u00f1adido"]];
  const table = document.createElement("div");
  table.className = "results-table";
  const head = document.createElement("div");
  head.className = "results-row results-head";
  head.innerHTML = '<div class="results-cell result-num">#</div>' + heads.map(([key, label]) =>
    '<button class="results-cell result-sort result-' + key + '" type="button" onclick="toggleResultSort(\'' + key + '\')">' + esc(label + resultSortMark(key)) + "</button>"
  ).join("") + '<div class="results-cell result-actions-head">Acciones</div>';
  table.appendChild(head);
  rows.forEach((item, idx) => {
    const source = item.source || item.quality || "-";
    const status = item.status || item.confidence || "-";
    const routeKind = historyRouteKind(item, source, status);
    const routeLabel = historyRouteLabel(routeKind);
    const routeTitle = historyRouteTitle(routeKind);
    const row = document.createElement("div");
    row.className = "results-row";
    row.innerHTML =
      '<div class="results-cell result-num">' + esc(String(idx + 1)) + "</div>" +
      '<div class="results-cell result-title" title="' + escAttr(item.title || "") + '">' + esc(item.title || "(sin t\u00edtulo)") + "</div>" +
      '<div class="results-cell result-size">' + esc(item.size || "-") + "</div>" +
      '<div class="results-cell result-seeds">' + esc(String(item.seeds || "0")) + "</div>" +
      '<div class="results-cell result-peers">' + esc(String(item.peers || "0")) + "</div>" +
      '<div class="results-cell result-added">' + esc(translateAddedLabel(item.added || "hoy")) + "</div>" +
      '<div class="results-cell result-actions">' +
        '<button class="result-icon result-download history-route-btn history-route-' + escAttr(routeKind) + '" type="button" title="' + escAttr(routeTitle) + '" aria-label="' + escAttr(routeTitle) + '">' + esc(routeLabel) + "</button>" +
        '<button class="result-icon result-copy" type="button" title="Copiar enlace">\u29c9</button>' +
      "</div>";
    const dl = row.querySelector(".result-download");
    const cp = row.querySelector(".result-copy");
    dl.onclick = () => downloadItem(item.index, dl);
    cp.onclick = () => copyText(item.link || "", cp);
    table.appendChild(row);
  });
  box.appendChild(table);
}

async function loadHistory(force = false) {
  const panel = document.getElementById("historyPanel");
  if (!panel) return;
  if (force) {
    historyOpenState = { days: {}, searches: {} };
    historyResultStore = {};
  }
  if (!historyCache || force) {
    panel.innerHTML = '<p class="hint history-empty">Cargando historial...</p>';
    try {
      const response = await fetch("/api/history/btdigg");
      const data = await response.json();
      if (!data.ok) throw new Error(data.error || "fallo historial");
      historyCache = data.history || {};
    } catch (e) {
      panel.innerHTML = '<p class="hint history-empty">No se pudo cargar el historial.</p>';
      return;
    }
  }
  renderHistory();
}

function historySourceRank(item) {
  const source = String((item && (item.source || item.quality)) || "").toLowerCase();
  if (source === "rd") return 0;
  if (source.includes("qbit")) return 1;
  return 2;
}

function historySizeValue(item) {
  const direct = Number(item && item.size_value);
  if (Number.isFinite(direct)) return direct;
  const match = String((item && item.size) || "").replace(",", ".").match(/([\d.]+)\s*(tb|gb|mb)?/i);
  if (!match) return 0;
  const value = Number(match[1]);
  if (!Number.isFinite(value)) return 0;
  const unit = String(match[2] || "gb").toLowerCase();
  if (unit === "tb") return value * 1024;
  if (unit === "mb") return value / 1024;
  return value;
}

function sortedHistoryResults(items) {
  return (items || [])
    .map((item, originalIndex) => ({ item, originalIndex }))
    .sort((a, b) => {
      const source = historySourceRank(a.item) - historySourceRank(b.item);
      if (source) return source;
      const size = historySizeValue(b.item) - historySizeValue(a.item);
      if (size) return size;
      return a.originalIndex - b.originalIndex;
    });
}
function renderHistory() {
  const panel = document.getElementById("historyPanel");
  if (!panel) return;
  const days = (historyCache && historyCache.days) || [];
  panel.innerHTML = "";
  historyResultStore = {};
  if (!days.length) {
    panel.innerHTML = '<p class="hint history-empty">Todav\u00eda no hay b\u00fasquedas guardadas.</p>';
    return;
  }
  days.forEach((day, dayIndex) => {
    const dayCard = document.createElement("details");
    dayCard.className = "history-day";
    const dayKey = String(day.date || day.label || dayIndex);
    dayCard.open = !!historyOpenState.days[dayKey];
    dayCard.innerHTML = '<summary><span>' + esc(day.label || day.date || "") + '</span></summary>';
    dayCard.addEventListener("toggle", () => {
      historyOpenState.days[dayKey] = dayCard.open;
    });
    const searchesBox = document.createElement("div");
    searchesBox.className = "history-searches";
    (day.searches || []).forEach((search, searchIndex) => {
      const searchCard = document.createElement("details");
      searchCard.className = "history-search";
      const searchKey = String(search.id || (dayKey + "-" + (search.created_at || searchIndex)));
      searchCard.open = !!historyOpenState.searches[searchKey];
      searchCard.addEventListener("toggle", () => {
        historyOpenState.searches[searchKey] = searchCard.open;
      });
      const query = search.query || "(sin b\u00fasqueda)";
      searchCard.innerHTML =
        '<summary><span><b>' + esc(search.time_label || "") + '</b> ' + esc(query) + '</span></summary>' +
        '<div class="history-meta">P\u00e1ginas ' + esc(search.pages || "-") + ' &middot; resultados ' + esc(String(search.result_count || 0)) + '</div>';
      const results = document.createElement("div");
      results.className = "history-results";
      sortedHistoryResults(search.results || []).forEach(({ item, originalIndex }) => {
        const result = document.createElement("div");
        const source = item.source || item.quality || "-";
        const status = item.status || item.confidence || "-";
        const routeKind = historyRouteKind(item, source, status);
        const routeLabel = historyRouteLabel(routeKind);
        const routeTitle = historyRouteTitle(routeKind);
        const metaText = [item.size || "-", translateAddedLabel(item.added || "hoy")].filter(Boolean).join(" \u00b7 ");
        const resultKey = searchKey + "-" + originalIndex;
        historyResultStore[resultKey] = {
          item,
          historyId: search.id || "",
          historyResult: originalIndex + 1
        };
        result.className = "history-result";
        result.innerHTML =
          '<div class="history-result-scroll">' +
            '<div class="history-result-main">' +
              '<strong>' + esc(item.title || "(sin t\u00edtulo)") + '</strong>' +
              '<span>' + esc(metaText) + '</span>' +
            '</div>' +
          '</div>' +
          '<div class="history-result-actions">' +
            '<button class="result-icon result-download history-download history-route-btn history-route-' + escAttr(routeKind) + '" type="button" title="' + escAttr(routeTitle) + '" aria-label="' + escAttr(routeTitle) + '">' + esc(routeLabel) + '</button>' +
          '</div>';
        const dl = result.querySelector(".history-download");
        if (dl) dl.onclick = () => downloadHistoryItem(resultKey, dl);
        results.appendChild(result);
      });
      searchCard.appendChild(results);
      searchesBox.appendChild(searchCard);
    });
    dayCard.appendChild(searchesBox);
    panel.appendChild(dayCard);
  });
}

async function copyText(text, btn = null) {
  if (!text) {
    setStatus("Sin enlace");
    setActionButtonState(btn, "error", "!");
    return;
  }
  setActionButtonState(btn, "loading");
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text || "");
    } else {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setStatus("Enlace copiado");
    setActionButtonState(btn, "done", "OK");
  } catch (e) {
    setStatus("No pude copiar");
    setActionButtonState(btn, "error", "!");
  }
}

function settingsMap() {
  const out = {};
  const cfg = settingsCache && settingsCache.btdigg ? settingsCache.btdigg : {};
  (cfg.fields || []).forEach(field => { out[field.key] = field.value; });
  return out;
}

function linesToText(value) {
  return Array.isArray(value) ? value.join("\n") : String(value || "");
}

function textToLines(value) {
  return String(value || "").split(/\r?\n/).map(line => line.trim()).filter(Boolean);
}

function setTvRulesForm(rules) {
  const templates = document.getElementById("tvSeriesTemplates");
  const words = document.getElementById("tvSeriesWords");
  if (templates) templates.value = linesToText((rules || {}).series_templates);
  if (words) words.value = linesToText((rules || {}).series_words);
}

function collectTvRulesForm() {
  const templates = document.getElementById("tvSeriesTemplates");
  const words = document.getElementById("tvSeriesWords");
  return {
    series_templates: textToLines(templates ? templates.value : ""),
    series_words: textToLines(words ? words.value : "")
  };
}

async function loadTvRules(force = false) {
  const panel = document.getElementById("tvRulesPanel");
  if (!panel) return;
  if (!tvRulesCache || force) {
    try {
      const response = await fetch("/api/tv-rules");
      const data = await response.json();
      if (!data.ok) throw new Error(data.error || "fallo reglas");
      tvRulesCache = data.rules || {};
      tvRulesDefaults = data.defaults || tvRulesCache;
    } catch (e) {
      const status = document.getElementById("settingsStatus");
      if (status) status.textContent = "Error cargando reglas TV.";
      return;
    }
  }
  setTvRulesForm(tvRulesCache);
}

function applyTvRuleDefaults() {
  if (!tvRulesDefaults) return;
  setTvRulesForm(tvRulesDefaults);
  const result = document.getElementById("tvClassifyResult");
  if (result) {
    result.className = "status-pill mid";
    result.textContent = "Sin probar";
  }
}

async function restoreTvRuleDefaults(btn = null) {
  applyTvRuleDefaults();
  const status = document.getElementById("settingsStatus");
  if (status) status.textContent = "Reglas restauradas. Pulsa Guardar.";
  setActionButtonState(btn, "done", "OK");
  return true;
}

async function saveTvRules() {
  const panel = document.getElementById("tvRulesPanel");
  if (!panel) return true;
  const response = await fetch("/api/tv-rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rules: collectTvRulesForm() })
  });
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "reglas no guardadas");
  tvRulesCache = data.rules || collectTvRulesForm();
  return true;
}

async function testTvRules(btn = null) {
  const input = document.getElementById("tvClassifyTitle");
  const result = document.getElementById("tvClassifyResult");
  const title = input ? input.value.trim() : "";
  if (!title) {
    if (result) {
      result.className = "status-pill mid";
      result.textContent = "Escribe titulo";
    }
    return;
  }
  setActionButtonState(btn, "loading");
  try {
    const response = await fetch("/api/tv-rules/classify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, rules: collectTvRulesForm() })
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "fallo prueba");
    if (result) {
      const isTv = data.destination === "tv";
      result.className = "status-pill " + (isTv ? "good" : "mid");
      result.textContent = isTv ? "Series / TV" : "Peliculas";
      if (data.matched_rule) result.title = "Regla: " + data.matched_rule;
    }
    setActionButtonState(btn, "done", "OK");
  } catch (e) {
    if (result) {
      result.className = "status-pill bad";
      result.textContent = "Error";
    }
    setActionButtonState(btn, "error", "!");
  }
}

function setControlValue(id, value) {
  const el = document.getElementById(id);
  if (!el || value === null || value === undefined) return;
  if (formStateRestored && el.value) return;
  el.value = String(value);
}

function applySettingsToSearchForm() {
  if (!settingsCache) return;
  const b = settingsMap();
  setControlValue("bPages", b.default_pages);
  setControlValue("bMode", b.default_mode);
  setControlValue("bMinGb", b.min_size_gb);
}

async function loadSettings(force = false) {
  const panel = document.getElementById("settingsPanel");
  const status = document.getElementById("settingsStatus");
  if (!panel) return;
  if (!settingsCache || force) {
    if (status) status.textContent = "Cargando...";
    try {
      const response = await fetch("/api/settings");
      const data = await response.json();
      if (!data.ok) throw new Error(data.error || "fallo ajustes");
      settingsCache = data.settings || {};
      if (status) status.textContent = "Ajustes cargados.";
    } catch (e) {
      panel.innerHTML = '<p class="hint">No se pudieron cargar los ajustes.</p>';
      if (status) status.textContent = "Error cargando.";
      return;
    }
  }
  applySettingsToSearchForm();
  renderSettings();
  await loadTvRules(force);
}

function settingControlHtml(field, id) {
  if (field.type === "bool") {
    return '<label class="setting-switch"><input id="' + escAttr(id) + '" data-key="' + escAttr(field.key) + '" data-type="bool" type="checkbox" ' + (field.value ? "checked" : "") + '><span>Activado</span></label>';
  }
  if (field.type === "select") {
    return '<select id="' + escAttr(id) + '" data-key="' + escAttr(field.key) + '" data-type="select">' + (field.options || []).map(option =>
      '<option value="' + escAttr(option.value) + '" ' + (String(option.value) === String(field.value) ? "selected" : "") + ">" + esc(option.label) + "</option>"
    ).join("") + "</select>";
  }
  const step = field.type === "float" ? "0.01" : "1";
  const inputType = field.type === "text" ? "text" : "number";
  const min = field.min === undefined ? "" : ' min="' + escAttr(field.min) + '"';
  const max = field.max === undefined ? "" : ' max="' + escAttr(field.max) + '"';
  return '<input id="' + escAttr(id) + '" data-key="' + escAttr(field.key) + '" data-type="' + escAttr(field.type) + '" type="' + inputType + '" step="' + step + '"' + min + max + ' value="' + escAttr(field.value === null || field.value === undefined ? "" : field.value) + '">';
}

function buildSettingItem(field) {
  const wrap = document.createElement("div");
  const fieldText = String((field.key || "") + " " + (field.label || "") + " " + (field.help || "")).toLowerCase();
  const isQbitSetting = fieldText.includes("qbit") || fieldText.includes("qbittorrent");
  const isRdSetting = field.section === "rd" || (!isQbitSetting && (String(field.key || "").startsWith("verify_") || fieldText.includes("real-debrid")));
  wrap.className = "setting-item" + (isQbitSetting ? " qbit-setting" : isRdSetting ? " rd-setting" : "");
  const id = "set-btdigg-" + field.key;
  const recommendation = field.recommendation ? ' <span class="setting-rec">' + esc(field.recommendation) + "</span>" : "";
  wrap.innerHTML = '<label for="' + escAttr(id) + '">' + esc(field.label || field.key) + "</label>" + settingControlHtml(field, id) + "<small>" + esc(field.help || "") + recommendation + "</small>";
  return wrap;
}

function renderSettings() {
  const panel = document.getElementById("settingsPanel");
  const rdPanel = document.getElementById("settingsRdPanel");
  if ((!panel && !rdPanel) || !settingsCache) return;
  const cfg = settingsCache.btdigg || {};
  const rdGroups = ["Ritmo RD", "RD a la vez", "Enfado RD / 429", "RD avanzado"];
  if (panel) panel.innerHTML = "";
  if (rdPanel) rdPanel.innerHTML = "";
  const fields = cfg.fields || [];
  fields.forEach(field => {
    if (field.section === "rd") return;
    if (panel) panel.appendChild(buildSettingItem(field));
  });
  rdGroups.forEach(groupName => {
    const groupFields = fields.filter(field => field.section === "rd" && field.group === groupName);
    if (!groupFields.length || !rdPanel) return;
    const group = document.createElement("div");
    group.className = "settings-rd-group";
    const title = document.createElement("div");
    title.className = "settings-rd-group-title";
    title.textContent = groupName;
    const grid = document.createElement("div");
    grid.className = "settings-grid settings-grid-full settings-grid-compact";
    groupFields.forEach(field => grid.appendChild(buildSettingItem(field)));
    group.appendChild(title);
    group.appendChild(grid);
    rdPanel.appendChild(group);
  });
}

const SETTINGS_RESET_VALUES = {
  default_mode: "0",
  default_pages: "1",
  safe_max_pages_when_zero: "30",
  max_results_to_show: "30",
  min_size_gb: "0",
  max_size_gb: "120",
  request_timeout_sec: "30",
  delay_between_btdigg_pages_sec: "4",
  pack_query_match_min_ratio: "0.55",
  verify_max_candidates: "40",
  verify_wait_sec: "2",
  rd_addmagnet_min_interval_sec: "1",
  rd_selectfiles_min_interval_sec: "0.75",
  rd_delete_min_interval_sec: "0.65",
  rd_info_min_interval_sec: "0.1",
  rd_addmagnet_max_concurrent: "1",
  rd_selectfiles_max_concurrent: "1",
  rd_delete_max_concurrent: "1",
  rd_info_max_concurrent: "4",
  rd_api_429_cooldown_sec: "3",
  rd_endpoint_429_cooldown_sec: "6",
  rd_429_retry_attempts: "6",
  rd_api_rate_limit_per_min: "235",
  rd_api_rate_limit_burst: "4",
  qbit_probe_max_candidates: "25",
  qbit_probe_wait_sec: "25",
  qbit_same_file_min_ratio: "0.85",
  qbit_probe_parallel_workers: "4",
  hide_non_working_results: true
};

function openSettingsResetModal() {
  const modal = document.getElementById("settingsResetModal");
  if (!modal) return;
  modal.classList.remove("hidden");
  const btn = document.getElementById("settingsResetConfirmBtn");
  if (btn) btn.focus();
}

function closeSettingsResetModal() {
  const modal = document.getElementById("settingsResetModal");
  if (modal) modal.classList.add("hidden");
}

function applySettingsResetValues() {
  Object.keys(SETTINGS_RESET_VALUES).forEach(key => {
    const el = document.querySelector('#settingsPanel [data-key="' + escAttr(key) + '"], #settingsRdPanel [data-key="' + escAttr(key) + '"]');
    if (!el) return;
    if (el.dataset.type === "bool") {
      el.checked = Boolean(SETTINGS_RESET_VALUES[key]);
    } else {
      el.value = String(SETTINGS_RESET_VALUES[key]);
    }
  });
}

async function confirmSettingsReset(btn = null) {
  applySettingsResetValues();
  applyTvRuleDefaults();
  const ok = await saveSettings(btn || document.getElementById("settingsResetConfirmBtn"));
  if (ok) closeSettingsResetModal();
}

async function saveSettings(btn = null) {
  const saveBtn = btn || document.getElementById("settingsSaveBtn");
  const status = document.getElementById("settingsStatus");
  const values = {};
  document.querySelectorAll("#settingsPanel [data-key], #settingsRdPanel [data-key]").forEach(el => {
    values[el.dataset.key] = el.dataset.type === "bool" ? el.checked : el.value;
  });
  setActionButtonState(saveBtn, "loading");
  if (status) status.textContent = "Guardando...";
  try {
    const response = await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ module: "btdigg", values }) });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "no guardado");
    await saveTvRules();
    settingsCache = null;
    tvRulesCache = null;
    await loadSettings(true);
    if (status) status.textContent = "Guardado OK.";
    setStatus("Ajustes guardados");
    setActionButtonState(saveBtn, "done", "OK");
    return true;
  } catch (e) {
    if (status) status.textContent = "Error: " + e.message;
    setStatus("Error ajustes");
    setActionButtonState(saveBtn, "error", "!");
    return false;
  }
}

function esc(s) {
  return (s === null || s === undefined ? "" : String(s)).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function escAttr(s) {
  return esc(s).replace(/[']/g, "&#39;");
}

document.addEventListener("keydown", ev => {
  if (ev.key !== "Enter" || !ev.target || ev.isComposing) return;
  if (ev.target.id !== "bQuery") return;
  ev.preventDefault();
  searchBT();
});

document.addEventListener("keydown", ev => {
  if (ev.key === "Escape") closeSettingsResetModal();
});

const settingsResetModal = document.getElementById("settingsResetModal");
if (settingsResetModal) {
  settingsResetModal.addEventListener("click", ev => {
    if (ev.target === settingsResetModal) closeSettingsResetModal();
  });
}

["bQuery", "bPages", "bMode", "bMinGb"].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener("input", saveFormState);
});

["rdFollowQuery", "rdFollowPages"].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener("input", saveRdFollowTestState);
});

resetStartupMemory();
restoreFormState();
restoreViewState();
restoreActivityState();
restoreRdFollowState();
loadQbitToggle();
loadSettings(true);
renderResults([]);
reconnectActiveJob();

window.addEventListener("pageshow", () => {
  reconnectActiveJob();
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) reconnectActiveJob();
});
