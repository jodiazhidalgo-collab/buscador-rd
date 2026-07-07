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
let rdFollowMagnets = [];
let rdFollowCollapsed = false;
let rdFollowMagnetsCollapsed = false;
let resultSort = { btdigg: { key: "index", dir: "asc" } };
let settingsCache = null;
let tvRulesCache = null;
let tvRulesDefaults = null;
let formStateRestored = false;
let finishSound = null;
let voiceStartSound = null;
let voiceDoneSound = null;
const finishSoundUrl = "/static/sounds/applepay.mp3";
const voiceStartSoundUrl = "/static/sounds/micro_inicio.mp3";
const voiceDoneSoundUrl = "/static/sounds/micro_terminado.mp3";
const finishSoundVolume = 0.55;
const voiceStartSoundVolume = 0.7;
const voiceDoneSoundVolume = 0.5;
const notifiedJobs = {};
let qbitSearchEnabled = true;
let queueQbitEnabled = true;
let searchQueueDraftItems = [];
let searchQueueServerState = null;
let searchQueuePollTimer = null;
const searchModeValues = new Set(["0", "1", "3"]);

function normalizeSearchMode(value) {
  const mode = String(value ?? "").trim();
  return searchModeValues.has(mode) ? mode : "0";
}

const formStoreKey = "btdiggRd.form.v1";
const viewStoreKey = "btdiggRd.view.v1";
const searchQueueDraftStoreKey = "btdiggRd.searchQueue.draft.v1";
const activityStoreKey = "btdiggRd.activity.v1";
const activeJobStoreKey = "btdiggRd.activeJob.v1";
const rdFollowStoreKey = "btdiggRd.rdFollow.v1";
const rdFollowMagnetsStoreKey = "btdiggRd.rdFollowMagnets.v1";
const rdFollowTestStoreKey = "btdiggRd.rdFollowTest.v1";
const uiStateStoreKey = "btdiggRd.uiState.v1";
const uiStateClientStoreKey = "btdiggRd.uiClient.v1";
const uiStateEndpoint = "/api/ui-state";
const rdOkVerifyTitleMarker = "__RD_OK_VERIFY_TITLE__";
const terminalJobStatuses = new Set(["done", "error", "cancelled"]);
const activeJobStatuses = new Set(["queued", "running", "cancelling"]);
const activeQueueStatuses = new Set(["running", "stopping"]);
let historyCache = null;
let historyOpenState = { days: {}, searches: {} };
let historyResultStore = {};
let titleResolveOpenKey = "";
let titleResolveCache = {};
let resultsSnapshot = "";
let uiStateClientId = "";
let uiStateSaveTimer = null;
let uiStateSaveInFlight = false;
let suppressUiStateSave = false;
let lastUiStateRemoteMs = 0;
let lastLocalUiStateChangeAt = 0;
let sharedRefreshTimer = null;
let lastResultsRefreshAt = 0;
let voiceRecorder = null;
let voiceStream = null;
let voiceChunks = [];
let voiceRecording = false;
let voiceSpeechDetected = false;
let voiceResolveSeq = 0;
let voiceTraceId = "";
let voiceTraceStartedAt = 0;
let voiceDiagnosticQueue = Promise.resolve();
let voiceClickGuardUntil = 0;
let voiceMonitorTimer = null;
let voiceMaxRecordTimer = null;
let voicePendingStopReason = "";
let voiceAudioContext = null;
let voiceAnalyser = null;
let voiceSourceNode = null;
let voiceStartPending = false;
let voiceDoneSoundPlayed = false;
const voiceInitialSpeechTimeoutMs = 5000;
const voiceSilenceStopMs = 1700;
const voiceMaxRecordMs = 15000;

function getUiStateClientId() {
  try {
    let id = localStorage.getItem(uiStateClientStoreKey);
    if (!id) {
      id = "ui-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8);
      localStorage.setItem(uiStateClientStoreKey, id);
    }
    return id;
  } catch (e) {
    return "ui-" + Date.now().toString(36);
  }
}

uiStateClientId = getUiStateClientId();

function visibleNow() {
  return !document.hidden;
}

function currentViewName() {
  if (settingsVisible()) return "settings";
  if (historyVisible()) return "history";
  if (queueMockVisible()) return "queue";
  return "main";
}

function readFormState() {
  const query = document.getElementById("bQuery");
  const pages = document.getElementById("bPages");
  const mode = document.getElementById("bMode");
  const minGb = document.getElementById("bMinGb");
  return {
    query: query ? query.value : "",
    pages: pages ? pages.value : "",
    mode: mode ? normalizeSearchMode(mode.value) : "0",
    minGb: minGb ? minGb.value : ""
  };
}

function focusedFormField() {
  const active = document.activeElement;
  return !!(active && ["bQuery", "bPages", "bMode", "bMinGb"].includes(active.id));
}

function applyFormState(data) {
  if (!data || typeof data !== "object") return;
  const fields = [
    ["bQuery", data.query || ""],
    ["bPages", data.pages],
    ["bMode", data.mode],
    ["bMinGb", data.minGb]
  ];
  fields.forEach(([id, value]) => {
    const el = document.getElementById(id);
    if (!el || document.activeElement === el || value === undefined) return;
    if (id === "bMode") value = normalizeSearchMode(value);
    el.value = value;
  });
}

function applyJobPayloadToForm(payload) {
  if (!payload || typeof payload !== "object" || focusedFormField()) return;
  applyFormState({
    query: payload.query || "",
    pages: payload.pages,
    mode: payload.mode,
    minGb: payload.min_gb || payload.minGb
  });
  saveFormState(false);
}

function uiStatePayload() {
  return {
    version: 1,
    view: currentViewName(),
    form: readFormState(),
    history_open: {
      days: historyOpenState.days || {},
      searches: historyOpenState.searches || {}
    },
    result_sort: resultSort.btdigg || { key: "index", dir: "asc" }
  };
}

function saveUiStateLocal(state) {
  try { localStorage.setItem(uiStateStoreKey, JSON.stringify(state)); } catch (e) {}
}

function applyLocalUiState() {
  try {
    const local = JSON.parse(localStorage.getItem(uiStateStoreKey) || "null");
    return local ? applyUiState(local, false) : false;
  } catch (e) {
    return false;
  }
}

function markUiStateChanged(delay = 700) {
  if (suppressUiStateSave) return;
  lastLocalUiStateChangeAt = Date.now();
  if (uiStateSaveTimer) clearTimeout(uiStateSaveTimer);
  uiStateSaveTimer = setTimeout(saveSharedUiState, delay);
}

async function saveSharedUiState() {
  if (uiStateSaveInFlight) {
    markUiStateChanged(900);
    return;
  }
  const state = uiStatePayload();
  saveUiStateLocal(state);
  uiStateSaveInFlight = true;
  try {
    const response = await fetch(uiStateEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        state,
        client_id: uiStateClientId,
        client_updated_at: Date.now()
      })
    });
    const data = await response.json();
    if (data.ok && data.state) lastUiStateRemoteMs = Number(data.state.server_updated_at || lastUiStateRemoteMs || 0);
  } catch (e) {
  } finally {
    uiStateSaveInFlight = false;
  }
}

function normalizeHistoryOpenState(value) {
  const raw = value && typeof value === "object" ? value : {};
  return {
    days: raw.days && typeof raw.days === "object" ? raw.days : {},
    searches: raw.searches && typeof raw.searches === "object" ? raw.searches : {}
  };
}

function applyUiState(state, remote = false) {
  if (!state || typeof state !== "object") return false;
  const remoteMs = Number(state.server_updated_at || 0);
  if (remote && remoteMs && remoteMs <= lastUiStateRemoteMs) return false;
  if (remote && Date.now() - lastLocalUiStateChangeAt < 2500) return false;
  suppressUiStateSave = true;
  try {
    if (!focusedFormField()) applyFormState(state.form || {});
    historyOpenState = normalizeHistoryOpenState(state.history_open);
    if (state.result_sort && typeof state.result_sort === "object") {
      resultSort.btdigg = {
        key: String(state.result_sort.key || "index"),
        dir: String(state.result_sort.dir || "asc") === "desc" ? "desc" : "asc"
      };
    }
    restoreViewState(String(state.view || "main"));
    saveFormState(false);
    saveUiStateLocal(state);
    if (remoteMs) lastUiStateRemoteMs = remoteMs;
    if (historyVisible()) loadHistory(false);
    if (!historyVisible() && (moduleResults.btdigg || []).length) renderResults(moduleResults.btdigg || []);
  } finally {
    suppressUiStateSave = false;
  }
  return true;
}

async function loadSharedUiState(remote = false) {
  const localApplied = remote ? false : applyLocalUiState();
  try {
    const response = await fetch(uiStateEndpoint, { cache: "no-store" });
    const data = await response.json();
    if (response.ok && data.ok && data.state && Number(data.state.server_updated_at || 0) > 0) {
      return applyUiState(data.state, remote) || localApplied;
    }
  } catch (e) {}
  return localApplied;
}

function buildUiSound(url, volume) {
  const audio = new Audio(url);
  audio.preload = "auto";
  audio.volume = volume;
  return audio;
}

function getFinishSound() {
  if (!finishSound) finishSound = buildUiSound(finishSoundUrl, finishSoundVolume);
  return finishSound;
}

function getVoiceStartSound() {
  if (!voiceStartSound) voiceStartSound = buildUiSound(voiceStartSoundUrl, voiceStartSoundVolume);
  return voiceStartSound;
}

function getVoiceDoneSound() {
  if (!voiceDoneSound) voiceDoneSound = buildUiSound(voiceDoneSoundUrl, voiceDoneSoundVolume);
  return voiceDoneSound;
}

function prepareUiSound(getAudio, volume) {
  try {
    const audio = getAudio();
    audio.pause();
    audio.currentTime = 0;
    audio.muted = true;
    const promise = audio.play();
    if (promise && promise.then) {
      promise.then(() => {
        audio.pause();
        audio.currentTime = 0;
        audio.muted = false;
        audio.volume = volume;
      }).catch(() => {
        audio.muted = false;
        audio.volume = volume;
        audio.load();
      });
    } else {
      audio.pause();
      audio.currentTime = 0;
      audio.muted = false;
      audio.volume = volume;
    }
  } catch (e) {}
}

function playUiSound(getAudio, volume) {
  try {
    const audio = getAudio();
    audio.pause();
    audio.currentTime = 0;
    audio.muted = false;
    audio.volume = volume;
    const promise = audio.play();
    if (promise && promise.catch) promise.catch(() => {});
  } catch (e) {}
}

function prepareFinishSound() {
  prepareUiSound(getFinishSound, finishSoundVolume);
}

function playFinishSound(jobId) {
  if (jobId && notifiedJobs[jobId]) return;
  if (jobId) notifiedJobs[jobId] = true;
  playUiSound(getFinishSound, finishSoundVolume);
}

function prepareVoiceDoneSound() {
  prepareUiSound(getVoiceDoneSound, voiceDoneSoundVolume);
}

function playVoiceStartSound() {
  playUiSound(getVoiceStartSound, voiceStartSoundVolume);
}

function playVoiceDoneSoundOnce() {
  if (voiceDoneSoundPlayed) return;
  voiceDoneSoundPlayed = true;
  playUiSound(getVoiceDoneSound, voiceDoneSoundVolume);
}

function createVoiceTraceId() {
  const stamp = new Date().toISOString().replace(/[^0-9A-Za-z]+/g, "").slice(0, 15);
  const rnd = Math.random().toString(36).slice(2, 8);
  return "voice-" + stamp + "-" + rnd;
}

function voiceElapsedMs() {
  if (!voiceTraceStartedAt) return 0;
  try {
    return Math.max(0, Math.round(performance.now() - voiceTraceStartedAt));
  } catch (e) {
    return 0;
  }
}

function voiceViewportData() {
  return {
    w: window.innerWidth || 0,
    h: window.innerHeight || 0,
    dpr: window.devicePixelRatio || 1
  };
}

function voiceScreenData() {
  const s = window.screen || {};
  return {
    w: s.width || 0,
    h: s.height || 0
  };
}

function sendVoiceDiagnostic(eventName, data = {}) {
  const traceId = voiceTraceId || createVoiceTraceId();
  if (!voiceTraceId) voiceTraceId = traceId;
  const payload = {
    trace_id: traceId,
    event: eventName,
    data: {
      url: location.origin + location.pathname,
      is_secure_context: !!window.isSecureContext,
      has_media_devices: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
      has_media_recorder: !!window.MediaRecorder,
      lang: navigator.language || "",
      languages: Array.isArray(navigator.languages) ? navigator.languages.slice(0, 4) : [],
      platform: navigator.platform || "",
      vendor: navigator.vendor || "",
      mobile: /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent || ""),
      touch_points: navigator.maxTouchPoints || 0,
      visibility: document.visibilityState || "",
      viewport: voiceViewportData(),
      screen: voiceScreenData(),
      elapsed_ms: voiceElapsedMs(),
      ...data
    }
  };
  const post = () => fetch("/api/voice/diagnostic", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true
    }).catch(() => {});
  try {
    voiceDiagnosticQueue = voiceDiagnosticQueue.catch(() => {}).then(post);
  } catch (e) {}
}

function reportVoicePermissionState() {
  if (!navigator.permissions || !navigator.permissions.query) {
    sendVoiceDiagnostic("voice_permission_state", { permission_state: "unsupported" });
    return;
  }
  try {
    navigator.permissions.query({ name: "microphone" }).then(result => {
      sendVoiceDiagnostic("voice_permission_state", { permission_state: result && result.state ? result.state : "unknown" });
    }).catch(err => {
      sendVoiceDiagnostic("voice_permission_state", { permission_state: "error", permission_error: err && err.name ? err.name : String(err || "") });
    });
  } catch (e) {
    sendVoiceDiagnostic("voice_permission_state", { permission_state: "error", permission_error: e && e.name ? e.name : String(e || "") });
  }
}

function cleanVoiceTitle(value) {
  return String(value || "")
    .trim()
    .replace(/\s+/g, " ")
    .replace(/\b([12])\.(\d{3})\b/g, "$1$2")
    .replace(/[.,;:!?]+$/g, "")
    .trim();
}

function titleQueryWithFlatYear(value) {
  return cleanVoiceTitle(value).replace(/\s+\((\d{4})\)\s*$/, " $1").trim();
}

function voiceResolverAttempts(transcript, alternatives) {
  const raw = String(transcript || "").trim();
  const values = [
    cleanVoiceTitle(raw),
    cleanVoiceTitle(raw.replace(/\b([2-9])\.(0\d{2})\b/g, "$1 2$2")),
    ...(alternatives || []).map(cleanVoiceTitle)
  ];
  return [...new Set(values.filter(Boolean))];
}

function setVoiceButtonState(state) {
  const btn = document.getElementById("voiceQueryBtn");
  if (!btn) return;
  btn.classList.toggle("is-listening", state === "recording");
  btn.classList.toggle("is-resolving", state === "resolving");
  btn.disabled = state === "resolving";
  if (state === "unsupported") {
    btn.disabled = false;
    btn.classList.add("is-unsupported");
    btn.title = "Micro no disponible en este navegador";
    return;
  }
  btn.classList.remove("is-unsupported");
  btn.title = state === "recording" ? "Grabando..." : "Dictar titulo";
}

function releaseQueryKeyboardFocus() {
  const query = document.getElementById("bQuery");
  if (!query) return;
  if (document.activeElement === query) query.blur();
}

function clearVoiceTimers() {
  if (voiceMonitorTimer) {
    clearInterval(voiceMonitorTimer);
    voiceMonitorTimer = null;
  }
  if (voiceMaxRecordTimer) {
    clearTimeout(voiceMaxRecordTimer);
    voiceMaxRecordTimer = null;
  }
}

function cleanupVoiceCapture(stopTracks = true) {
  clearVoiceTimers();
  if (voiceSourceNode) {
    try { voiceSourceNode.disconnect(); } catch (e) {}
    voiceSourceNode = null;
  }
  voiceAnalyser = null;
  if (voiceAudioContext) {
    try { voiceAudioContext.close(); } catch (e) {}
    voiceAudioContext = null;
  }
  if (stopTracks && voiceStream && voiceStream.getTracks) {
    voiceStream.getTracks().forEach(track => {
      try { track.stop(); } catch (e) {}
    });
  }
  voiceStream = null;
}

function showVoiceProblem(message) {
  voiceRecording = false;
  voiceRecorder = null;
  cleanupVoiceCapture(true);
  setVoiceButtonState("idle");
  setStatus(message || "Micro no disponible");
}

function setQueryFromVoice(value, shared = true) {
  const query = document.getElementById("bQuery");
  if (!query) return;
  query.value = cleanVoiceTitle(value);
  query.dispatchEvent(new Event("input", { bubbles: true }));
  saveFormState(shared);
}

function bestVoiceResolvedTitle(data, fallback) {
  if (!data || data.status !== "resolved" || !data.safe || !data.copy) return "";
  const copy = data.copy || {};
  return titleQueryWithFlatYear(
    copy.es_with_year ||
    copy.original_with_year ||
    copy.en_with_year ||
    copy.english_with_year ||
    copy.es ||
    copy.original ||
    copy.en ||
    fallback
  );
}

async function resolveVoiceTitle(transcript, alternatives) {
  const seq = ++voiceResolveSeq;
  setVoiceButtonState("resolving");
  setStatus("Resolviendo titulo...");
  const attempts = voiceResolverAttempts(transcript, alternatives);
  sendVoiceDiagnostic("voice_resolver_start", {
    transcript_preview: String(transcript || "").slice(0, 120),
    alternatives_count: alternatives && alternatives.length ? alternatives.length : 0,
    attempts_count: attempts.length
  });
  try {
    const response = await fetch("/api/spoken-title-resolver/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transcript: attempts[0] || transcript,
        alternatives: attempts,
        locale: navigator.language || "es-ES",
        region: "ES"
      })
    });
    const data = await response.json();
    if (seq !== voiceResolveSeq) return;
    const resolved = bestVoiceResolvedTitle(data, attempts[0] || transcript);
    if (response.ok && resolved) {
      setQueryFromVoice(resolved, true);
      sendVoiceDiagnostic("voice_resolver_ok", { resolved: true, response_ok: true, text_len: resolved.length, decision: data.decision || "" });
      setStatus("Titulo listo. Pulsa BUSCAR.");
      return;
    }
    sendVoiceDiagnostic("voice_resolver_ok", { resolved: false, response_ok: true, decision: data && data.decision ? data.decision : "" });
    setStatus("Texto listo. Revisa y pulsa BUSCAR.");
  } catch (e) {
    sendVoiceDiagnostic("voice_resolver_error", {
      error: e && e.name ? e.name : "resolver_error",
      message: e && e.message ? e.message : String(e || "")
    });
    if (seq === voiceResolveSeq) setStatus("Texto listo. Revisa y pulsa BUSCAR.");
  } finally {
    if (seq === voiceResolveSeq) {
      setVoiceButtonState("idle");
      playVoiceDoneSoundOnce();
    }
  }
}

function bestVoiceMimeType() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
    "audio/wav"
  ];
  if (!window.MediaRecorder || !window.MediaRecorder.isTypeSupported) return "";
  for (const item of candidates) {
    try {
      if (window.MediaRecorder.isTypeSupported(item)) return item;
    } catch (e) {}
  }
  return "";
}

function voiceUploadName(mimeType) {
  const type = String(mimeType || "").toLowerCase();
  if (type.includes("mp4")) return "voice.mp4";
  if (type.includes("ogg")) return "voice.ogg";
  if (type.includes("wav")) return "voice.wav";
  return "voice.webm";
}

function stopVoiceRecording(reason = "manual_stop") {
  voicePendingStopReason = reason;
  clearVoiceTimers();
  if (!voiceRecorder) return;
  try {
    if (voiceRecorder.state !== "inactive") {
      voiceRecorder.stop();
      return;
    }
  } catch (e) {
    sendVoiceDiagnostic("voice_recorder_error", {
      error: e && e.name ? e.name : "stop_error",
      message: e && e.message ? e.message : String(e || "")
    });
  }
  cleanupVoiceCapture(true);
  voiceRecording = false;
  voiceRecorder = null;
  setVoiceButtonState("idle");
}

function startVoiceLevelMonitor(stream) {
  if (!stream || !(window.AudioContext || window.webkitAudioContext)) return;
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    voiceAudioContext = new AudioCtx();
    if (voiceAudioContext.state === "suspended" && voiceAudioContext.resume) {
      voiceAudioContext.resume().catch(() => {});
    }
    voiceSourceNode = voiceAudioContext.createMediaStreamSource(stream);
    voiceAnalyser = voiceAudioContext.createAnalyser();
    voiceAnalyser.fftSize = 512;
    voiceSourceNode.connect(voiceAnalyser);
    const data = new Uint8Array(voiceAnalyser.fftSize);
    let lastLoudAt = 0;
    const startedAt = performance.now();
    voiceMonitorTimer = setInterval(() => {
      if (!voiceRecorder || voiceRecorder.state === "inactive" || !voiceAnalyser) return;
      voiceAnalyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i += 1) {
        const centered = (data[i] - 128) / 128;
        sum += centered * centered;
      }
      const level = Math.sqrt(sum / data.length);
      const now = performance.now();
      if (level > 0.028) {
        if (!voiceSpeechDetected) {
          voiceSpeechDetected = true;
          sendVoiceDiagnostic("voice_audio_detected", { state: "voice_detected", elapsed_ms: voiceElapsedMs() });
        }
        lastLoudAt = now;
      }
      if (!voiceSpeechDetected && now - startedAt >= voiceInitialSpeechTimeoutMs) {
        sendVoiceDiagnostic("voice_no_speech_timeout", {
          timeout_ms: voiceInitialSpeechTimeoutMs,
          state: "no_voice_detected"
        });
        stopVoiceRecording("no_speech");
      } else if (voiceSpeechDetected && lastLoudAt && now - lastLoudAt >= voiceSilenceStopMs) {
        sendVoiceDiagnostic("voice_silence_auto_stop", {
          timeout_ms: voiceSilenceStopMs,
          state: "silence_after_voice"
        });
        stopVoiceRecording("auto_silence");
      }
    }, 160);
  } catch (e) {
    sendVoiceDiagnostic("voice_recorder_error", {
      error: e && e.name ? e.name : "audio_monitor_error",
      message: e && e.message ? e.message : String(e || "")
    });
  }
}

async function transcribeVoiceBlob(blob) {
  if (!blob || !blob.size) {
    sendVoiceDiagnostic("voice_upload_error", { error: "empty_blob", audio_size: 0 });
    showVoiceProblem("No he oido voz");
    playVoiceDoneSoundOnce();
    return;
  }
  setVoiceButtonState("resolving");
  setStatus("Transcribiendo...");
  sendVoiceDiagnostic("voice_upload_start", {
    audio_size: blob.size,
    mime_type: blob.type || ""
  });
  const form = new FormData();
  form.append("audio", blob, voiceUploadName(blob.type));
  form.append("lang", "es");
  form.append("trace_id", voiceTraceId || createVoiceTraceId());
  try {
    const response = await fetch("/api/voice/transcribe", {
      method: "POST",
      body: form
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data || data.ok === false) {
      const code = data && data.error_code ? String(data.error_code) : "upload_failed";
      sendVoiceDiagnostic("voice_upload_error", {
        error: code,
        message: data && data.message ? data.message : "",
        provider: data && data.provider ? data.provider : "",
        status_code: response.status
      });
      if (code === "transcriber_not_configured" || code === "openai_key_missing") {
        setStatus("Transcriptor no configurado");
      } else {
        setStatus("No se pudo transcribir");
      }
      setVoiceButtonState("idle");
      playVoiceDoneSoundOnce();
      return;
    }
    const transcript = cleanVoiceTitle(data.text || "");
    sendVoiceDiagnostic("voice_upload_ok", {
      audio_size: blob.size,
      provider: data.provider || "",
      text_len: transcript.length,
      transcript_preview: transcript.slice(0, 120)
    });
    if (!transcript) {
      setStatus("No he oido voz");
      setVoiceButtonState("idle");
      playVoiceDoneSoundOnce();
      return;
    }
    setQueryFromVoice(transcript, true);
    await resolveVoiceTitle(transcript, [transcript]);
  } catch (e) {
    sendVoiceDiagnostic("voice_upload_error", {
      error: e && e.name ? e.name : "upload_exception",
      message: e && e.message ? e.message : String(e || "")
    });
    setStatus("No se pudo transcribir");
    setVoiceButtonState("idle");
    playVoiceDoneSoundOnce();
  }
}

async function startVoiceQuery(ev) {
  if (ev && ev.preventDefault) ev.preventDefault();
  if (ev && ev.stopPropagation) ev.stopPropagation();
  releaseQueryKeyboardFocus();
  const clickNow = Date.now();
  if (voiceRecording && voiceRecorder) {
    sendVoiceDiagnostic("voice_manual_stop", { state: "manual_stop", reason: "button" });
    stopVoiceRecording("manual_stop");
    return;
  }
  if (voiceStartPending) {
    sendVoiceDiagnostic("voice_busy_click", { state: "ignored_while_starting" });
    setStatus("Preparando micro...");
    return;
  }
  if (clickNow < voiceClickGuardUntil) {
    sendVoiceDiagnostic("voice_busy_click", { state: "ignored_by_guard" });
    setStatus("Un momento...");
    return;
  }
  voiceClickGuardUntil = clickNow + 450;
  voiceTraceId = createVoiceTraceId();
  try {
    voiceTraceStartedAt = performance.now();
  } catch (e) {
    voiceTraceStartedAt = 0;
  }
  voiceSpeechDetected = false;
  voiceChunks = [];
  voicePendingStopReason = "";
  voiceDoneSoundPlayed = false;
  sendVoiceDiagnostic("voice_record_click", {
    button_disabled: !!(document.getElementById("voiceQueryBtn") || {}).disabled
  });
  if (!window.isSecureContext) {
    sendVoiceDiagnostic("voice_insecure_context", {
      error: "insecure-context",
      message: "secure_context_required"
    });
    showVoiceProblem("Micro requiere HTTPS");
    return;
  }
  reportVoicePermissionState();
  if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) || !window.MediaRecorder) {
    setVoiceButtonState("unsupported");
    sendVoiceDiagnostic("voice_unsupported", { message: "media_recorder_missing" });
    showVoiceProblem("Sin micro");
    setVoiceButtonState("unsupported");
    return;
  }
  voiceStartPending = true;
  prepareVoiceDoneSound();
  setStatus("Preparando micro...");
  sendVoiceDiagnostic("voice_get_user_media_start", { state: "requesting_micro" });
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1
      }
    });
    voiceStream = stream;
    sendVoiceDiagnostic("voice_get_user_media_ok", { state: "micro_ready" });
    const mimeType = bestVoiceMimeType();
    const options = mimeType ? { mimeType } : {};
    const recorder = new MediaRecorder(stream, options);
    voiceRecorder = recorder;
    recorder.ondataavailable = event => {
      if (event && event.data && event.data.size) voiceChunks.push(event.data);
    };
    recorder.onstart = () => {
      voiceStartPending = false;
      voiceRecording = true;
      setVoiceButtonState("recording");
      setStatus("Grabando...");
      playVoiceStartSound();
      sendVoiceDiagnostic("voice_recorder_start", { mime_type: recorder.mimeType || mimeType || "" });
      startVoiceLevelMonitor(stream);
      voiceMaxRecordTimer = setTimeout(() => stopVoiceRecording("max_duration"), voiceMaxRecordMs);
    };
    recorder.onerror = event => {
      const err = event && event.error ? event.error : null;
      sendVoiceDiagnostic("voice_recorder_error", {
        error: err && err.name ? err.name : "recorder_error",
        message: err && err.message ? err.message : ""
      });
      showVoiceProblem("No se pudo grabar");
    };
    recorder.onstop = () => {
      clearVoiceTimers();
      const reason = voicePendingStopReason || "stop";
      const mime = recorder.mimeType || mimeType || "audio/webm";
      const blob = new Blob(voiceChunks, { type: mime });
      const duration = voiceElapsedMs();
      voiceRecording = false;
      voiceRecorder = null;
      cleanupVoiceCapture(true);
      sendVoiceDiagnostic("voice_recorder_stop", {
        reason,
        audio_size: blob.size,
        duration_ms: duration,
        mime_type: mime,
        state: voiceSpeechDetected ? "speech_detected" : "no_speech_detected"
      });
      voiceChunks = [];
      if (reason === "no_speech" || !voiceSpeechDetected) {
        setVoiceButtonState("idle");
        setStatus("No he oido voz");
        playVoiceDoneSoundOnce();
        return;
      }
      transcribeVoiceBlob(blob);
    };
    recorder.start(250);
  } catch (e) {
    voiceStartPending = false;
    const errorName = e && e.name ? e.name : "get_user_media_error";
    sendVoiceDiagnostic("voice_get_user_media_error", {
      error: errorName,
      message: e && e.message ? e.message : String(e || ""),
      state: "micro_error"
    });
    if (errorName === "NotAllowedError" || errorName === "PermissionDeniedError") {
      showVoiceProblem("Micro bloqueado");
    } else {
      showVoiceProblem("No se pudo abrir micro");
    }
    playVoiceDoneSoundOnce();
  }
}

function setStatus(text) {
  const last = document.getElementById("lastAction");
  if (last) last.textContent = text || "Listo";
}

function isTerminalJobStatus(status) {
  return terminalJobStatuses.has(String(status || "").toLowerCase());
}

function isActiveJobStatus(status) {
  return activeJobStatuses.has(String(status || "").toLowerCase());
}

function jobStatusLabel(status) {
  const value = String(status || "").toLowerCase();
  if (value === "done") return "Terminado";
  if (value === "error") return "Error";
  if (value === "cancelled") return "Cancelado";
  if (value === "cancelling") return "Deteniendo...";
  if (value === "running") return "Trabajando LIVE...";
  return "En cola...";
}

function updateStopButton(status = null) {
  const btn = document.getElementById("stopBTBtn");
  if (!btn) return;
  const value = String(status || "").toLowerCase();
  const active = value ? isActiveJobStatus(value) : !!(moduleBusy.btdigg && activeJobIds.btdigg);
  btn.classList.toggle("is-stopping", value === "cancelling");
  btn.textContent = value === "cancelling" ? "Deteniendo..." : "Detener";
  btn.disabled = !active || value === "cancelling";
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

async function loadQbitToggle(options = {}) {
  const silent = !!(options && options.silent);
  try {
    const res = await fetch("/api/qbit-toggle", { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "No se pudo leer qBit");
    setQbitToggleState(data.enabled !== false, false);
  } catch (e) {
    if (!silent) setQbitToggleState(true, false);
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

function saveFormState(shared = true) {
  try {
    localStorage.setItem(formStoreKey, JSON.stringify(readFormState()));
  } catch (e) {}
  if (shared) markUiStateChanged();
}

function restoreFormState() {
  formStateRestored = false;
  const query = document.getElementById("bQuery");
  let data = null;
  try {
    data = JSON.parse(localStorage.getItem(formStoreKey) || "null");
  } catch (e) {}
  if (data && typeof data === "object") {
    applyFormState(data);
    formStateRestored = true;
    return;
  }
  if (query) query.value = "";
}

function settingsVisible() {
  const view = document.getElementById("settingsView");
  return !!view && !view.classList.contains("hidden");
}

function historyVisible() {
  const view = document.getElementById("historyView");
  return !!view && !view.classList.contains("hidden");
}

function queueMockVisible() {
  const view = document.getElementById("queueMockView");
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
  const queue = document.getElementById("queueMockView");
  const toggle = document.getElementById("settingsToggle");
  const historyToggle = document.getElementById("historyToggle");
  const queueToggle = document.getElementById("queueMockToggle");
  if (!main || !settings) return;
  main.classList.toggle("hidden", show);
  settings.classList.toggle("hidden", !show);
  if (history) history.classList.add("hidden");
  if (queue) queue.classList.add("hidden");
  if (toggle) {
    toggle.classList.toggle("is-active", show);
    toggle.title = show ? "Volver a b\u00fasqueda" : "Ajustes";
    toggle.setAttribute("aria-pressed", show ? "true" : "false");
  }
  if (historyToggle) {
    historyToggle.classList.remove("is-active");
    historyToggle.setAttribute("aria-pressed", "false");
  }
  if (queueToggle) {
    queueToggle.classList.remove("is-active");
    queueToggle.setAttribute("aria-pressed", "false");
  }
  if (persist) {
    try { localStorage.setItem(viewStoreKey, show ? "settings" : "main"); } catch (e) {}
    markUiStateChanged();
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
  const queue = document.getElementById("queueMockView");
  const toggle = document.getElementById("historyToggle");
  const settingsToggle = document.getElementById("settingsToggle");
  const queueToggle = document.getElementById("queueMockToggle");
  if (!main || !history) return;
  main.classList.toggle("hidden", show);
  history.classList.toggle("hidden", !show);
  if (settings) settings.classList.add("hidden");
  if (queue) queue.classList.add("hidden");
  if (toggle) {
    toggle.classList.toggle("is-active", show);
    toggle.title = show ? "Volver a b\u00fasqueda" : "Historial";
    toggle.setAttribute("aria-pressed", show ? "true" : "false");
  }
  if (settingsToggle) {
    settingsToggle.classList.remove("is-active");
    settingsToggle.setAttribute("aria-pressed", "false");
  }
  if (queueToggle) {
    queueToggle.classList.remove("is-active");
    queueToggle.setAttribute("aria-pressed", "false");
  }
  if (persist) {
    try { localStorage.setItem(viewStoreKey, show ? "history" : "main"); } catch (e) {}
    markUiStateChanged();
  }
  if (show) loadHistory(false);
}

function toggleHistoryView() {
  setHistoryView(!historyVisible(), true);
}

function setQueueMockView(show, persist = true) {
  const main = document.getElementById("mainView");
  const settings = document.getElementById("settingsView");
  const history = document.getElementById("historyView");
  const queue = document.getElementById("queueMockView");
  const toggle = document.getElementById("queueMockToggle");
  const settingsToggle = document.getElementById("settingsToggle");
  const historyToggle = document.getElementById("historyToggle");
  if (!main || !queue) return;
  main.classList.toggle("hidden", show);
  queue.classList.toggle("hidden", !show);
  if (settings) settings.classList.add("hidden");
  if (history) history.classList.add("hidden");
  if (toggle) {
    toggle.classList.toggle("is-active", show);
    toggle.title = show ? "Volver a b\u00fasqueda" : "Lista";
    toggle.setAttribute("aria-pressed", show ? "true" : "false");
  }
  if (settingsToggle) {
    settingsToggle.classList.remove("is-active");
    settingsToggle.setAttribute("aria-pressed", "false");
  }
  if (historyToggle) {
    historyToggle.classList.remove("is-active");
    historyToggle.setAttribute("aria-pressed", "false");
  }
  if (persist) {
    try { localStorage.setItem(viewStoreKey, show ? "queue" : "main"); } catch (e) {}
    markUiStateChanged();
  }
}

function toggleQueueMockView() {
  setQueueMockView(!queueMockVisible(), true);
}

function queueModeLabel(mode) {
  const value = normalizeSearchMode(mode);
  if (value === "3") return "Castellano";
  if (value === "1") return "Calidad pura";
  return "Sin filtro";
}

function queueIsActive(state = searchQueueServerState) {
  return !!(state && activeQueueStatuses.has(String(state.status || "")));
}

function setQueueStatusText(text) {
  const el = document.getElementById("queueStatus");
  if (el) el.textContent = text || "Cola de busquedas.";
}

function setQueueQbitState(enabled) {
  queueQbitEnabled = !!enabled;
  const btn = document.getElementById("queueQbitToggle");
  if (!btn) return;
  btn.classList.toggle("is-on", queueQbitEnabled);
  btn.classList.toggle("is-off", !queueQbitEnabled);
  btn.textContent = queueQbitEnabled ? "qB ON" : "qB OFF";
  btn.setAttribute("aria-pressed", queueQbitEnabled ? "true" : "false");
}

function toggleQueueQbit() {
  if (queueIsActive()) return;
  setQueueQbitState(!queueQbitEnabled);
}

function saveSearchQueueDraft() {
  try {
    localStorage.setItem(searchQueueDraftStoreKey, JSON.stringify(searchQueueDraftItems));
  } catch (e) {}
}

function restoreSearchQueueDraft() {
  try {
    const data = JSON.parse(localStorage.getItem(searchQueueDraftStoreKey) || "[]");
    if (Array.isArray(data)) {
      searchQueueDraftItems = data
        .filter(item => item && item.query)
        .slice(0, 40)
        .map(item => ({
          id: String(item.id || ("q_" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6))),
          query: String(item.query || "").slice(0, 220),
          pages: String(item.pages || "1"),
          mode: normalizeSearchMode(item.mode),
          min_gb: String(item.min_gb || ""),
          qbit_enabled: item.qbit_enabled !== false,
          status: "pending"
        }));
    }
  } catch (e) {
    searchQueueDraftItems = [];
  }
}

function queueCurrentItems() {
  if (searchQueueServerState && Array.isArray(searchQueueServerState.items) && searchQueueServerState.items.length) {
    return searchQueueServerState.items;
  }
  return searchQueueDraftItems;
}

function queueCardClass(status) {
  const value = String(status || "pending");
  if (value === "done") return "is-done";
  if (value === "running" || value === "queued") return "is-running";
  if (value === "error") return "is-error";
  if (value === "cancelled") return "is-cancelled";
  return "is-pending";
}

function queueCardTitle(status) {
  const value = String(status || "pending");
  if (value === "done") return "Completada";
  if (value === "running" || value === "queued") return "Trabajando";
  if (value === "error") return "Error";
  if (value === "cancelled") return "Cancelada";
  return "Pendiente";
}

function queueItemMeta(item) {
  const parts = [
    "Pag. " + (item.pages || "1"),
    queueModeLabel(item.mode),
    (item.min_gb ? item.min_gb : "0") + " GB",
    item.qbit_enabled === false ? "qB OFF" : "qB ON"
  ];
  const count = Number(item.results_count || 0);
  if (String(item.status || "") === "done") parts.push(count + " resultados");
  if (String(item.status || "") === "error" && item.error) parts.push("error");
  return parts.join(" - ");
}

function renderSearchQueue() {
  const list = document.getElementById("queueCardList");
  if (!list) return;
  const active = queueIsActive();
  const items = queueCurrentItems();
  if (!items.length) {
    list.innerHTML = '<div class="queue-empty">Sin tareas en la lista.</div>';
  } else {
    list.innerHTML = items.map((item, index) => {
      const id = escAttr(item.id || "");
      const status = String(item.status || "pending");
      const canMove = !active && !searchQueueServerState;
      const upDisabled = !canMove || index === 0 ? " disabled" : "";
      const downDisabled = !canMove || index === items.length - 1 ? " disabled" : "";
      return [
        '<article class="queue-task-card ' + queueCardClass(status) + '" title="' + escAttr(queueCardTitle(status)) + '">',
        '<div class="queue-task-main"><strong>' + esc(item.query || "") + '</strong><small>' + esc(queueItemMeta(item)) + '</small></div>',
        '<div class="queue-card-actions" aria-label="Ordenar">',
        '<button class="queue-order-btn" type="button" title="Subir" onclick="moveSearchQueueItem(\'' + id + '\', -1)"' + upDisabled + '>&#9650;</button>',
        '<button class="queue-order-btn" type="button" title="Bajar" onclick="moveSearchQueueItem(\'' + id + '\', 1)"' + downDisabled + '>&#9660;</button>',
        '</div>',
        '</article>'
      ].join("");
    }).join("");
  }

  const addBtn = document.getElementById("queueAddBtn");
  const startBtn = document.getElementById("queueStartBtn");
  const clearBtn = document.getElementById("queueClearBtn");
  const stopBtn = document.getElementById("queueStopBtn");
  const title = document.getElementById("queueTitle");
  const pages = document.getElementById("queuePages");
  const minGb = document.getElementById("queueMinGb");
  const mode = document.getElementById("queueMode");
  const qbit = document.getElementById("queueQbitToggle");
  [addBtn, title, pages, minGb, mode, qbit].forEach(el => { if (el) el.disabled = active; });
  if (startBtn) startBtn.disabled = active || !searchQueueDraftItems.length || !!searchQueueServerState;
  if (clearBtn) clearBtn.disabled = active;
  if (stopBtn) stopBtn.disabled = !active;

  if (active) {
    setQueueStatusText("Lista trabajando en el NAS...");
  } else if (searchQueueServerState && String(searchQueueServerState.status || "") === "done") {
    setQueueStatusText("Lista completada.");
  } else if (searchQueueServerState && String(searchQueueServerState.status || "") === "error") {
    setQueueStatusText("Lista terminada con avisos.");
  } else if (searchQueueServerState && String(searchQueueServerState.status || "") === "cancelled") {
    setQueueStatusText("Lista detenida.");
  } else {
    setQueueStatusText(searchQueueDraftItems.length ? "Lista preparada: " + searchQueueDraftItems.length : "Cola de busquedas.");
  }
}

function addSearchQueueItem() {
  if (queueIsActive()) return;
  const title = document.getElementById("queueTitle");
  const pages = document.getElementById("queuePages");
  const mode = document.getElementById("queueMode");
  const minGb = document.getElementById("queueMinGb");
  const query = title ? String(title.value || "").trim() : "";
  if (!query) {
    setQueueStatusText("Escribe un titulo antes de anadir.");
    if (title) title.focus();
    return;
  }
  searchQueueServerState = null;
  searchQueueDraftItems.push({
    id: "q_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 6),
    query,
    pages: pages ? String(pages.value || "1").trim() || "1" : "1",
    mode: mode ? normalizeSearchMode(mode.value) : "0",
    min_gb: minGb ? String(minGb.value || "").trim() : "",
    qbit_enabled: queueQbitEnabled,
    status: "pending"
  });
  if (title) title.value = "";
  saveSearchQueueDraft();
  renderSearchQueue();
}

function moveSearchQueueItem(id, dir) {
  if (queueIsActive() || searchQueueServerState) return;
  const index = searchQueueDraftItems.findIndex(item => String(item.id) === String(id));
  const next = index + Number(dir || 0);
  if (index < 0 || next < 0 || next >= searchQueueDraftItems.length) return;
  const [item] = searchQueueDraftItems.splice(index, 1);
  searchQueueDraftItems.splice(next, 0, item);
  saveSearchQueueDraft();
  renderSearchQueue();
}

function applySearchQueueState(state) {
  searchQueueServerState = state && Array.isArray(state.items) && state.items.length ? state : null;
  if (searchQueueServerState && searchQueueServerState.current_job_id && queueIsActive(searchQueueServerState)) {
    const currentId = String(searchQueueServerState.current_job_id || "");
    if (currentId && activeJobIds.btdigg !== currentId) {
      resumeJob(currentId, "btdigg");
    }
  }
  if (searchQueueServerState && !queueIsActive(searchQueueServerState)) {
    try { localStorage.removeItem(searchQueueDraftStoreKey); } catch (e) {}
    searchQueueDraftItems = [];
    stopSearchQueuePolling();
  }
  renderSearchQueue();
}

function stopSearchQueuePolling() {
  if (searchQueuePollTimer) clearInterval(searchQueuePollTimer);
  searchQueuePollTimer = null;
}

function startSearchQueuePolling() {
  if (searchQueuePollTimer) return;
  searchQueuePollTimer = setInterval(loadSearchQueueStatus, 1500);
}

async function loadSearchQueueStatus() {
  try {
    const response = await fetch("/api/search-queue", { cache: "no-store" });
    const data = await response.json();
    if (!data.ok) return;
    const queue = data.queue || null;
    if (queue && Array.isArray(queue.items) && queue.items.length) {
      applySearchQueueState(queue);
      if (queueIsActive(queue)) startSearchQueuePolling();
      return;
    }
  } catch (e) {}
  if (!searchQueueServerState) renderSearchQueue();
}

async function startSearchQueue() {
  if (queueIsActive()) return;
  if (!searchQueueDraftItems.length) {
    setQueueStatusText("Anade al menos una busqueda.");
    return;
  }
  const btn = document.getElementById("queueStartBtn");
  setActionButtonState(btn, "loading");
  try {
    const response = await fetch("/api/search-queue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: searchQueueDraftItems })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "no se pudo arrancar la lista");
    searchQueueDraftItems = [];
    try { localStorage.removeItem(searchQueueDraftStoreKey); } catch (e) {}
    applySearchQueueState(data.queue);
    startSearchQueuePolling();
    setActionButtonState(btn, "done", "OK");
  } catch (e) {
    setQueueStatusText("Error: " + e.message);
    setActionButtonState(btn, "error", "!");
  }
}

async function stopSearchQueue() {
  const btn = document.getElementById("queueStopBtn");
  setActionButtonState(btn, "loading");
  try {
    const response = await fetch("/api/search-queue/stop", { method: "POST" });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "no se pudo detener");
    applySearchQueueState(data.queue);
    startSearchQueuePolling();
    setActionButtonState(btn, "done", "OK");
  } catch (e) {
    setQueueStatusText("Error: " + e.message);
    setActionButtonState(btn, "error", "!");
  }
}

async function clearSearchQueue() {
  if (queueIsActive()) return;
  const btn = document.getElementById("queueClearBtn");
  setActionButtonState(btn, "loading");
  try {
    const response = await fetch("/api/search-queue/clear", { method: "POST" });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "no se pudo limpiar");
    searchQueueDraftItems = [];
    searchQueueServerState = null;
    try { localStorage.removeItem(searchQueueDraftStoreKey); } catch (e) {}
    renderSearchQueue();
    setActionButtonState(btn, "done", "OK");
  } catch (e) {
    setQueueStatusText("Error: " + e.message);
    setActionButtonState(btn, "error", "!");
  }
}

function restoreViewState(savedView = null) {
  let view = savedView;
  if (!view) {
    try { view = localStorage.getItem(viewStoreKey) || "main"; } catch (e) { view = "main"; }
  }
  if (view === "settings") {
    setSettingsView(true, false);
    return;
  }
  if (view === "history") {
    setHistoryView(true, false);
    return;
  }
  if (view === "queue") {
    setQueueMockView(true, false);
    return;
  }
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

function setRdFollowMagnetsCollapsed(collapsed, persist = true) {
  const list = document.getElementById("rdFollowMagnetsList");
  const btn = document.getElementById("rdFollowMagnetsToggle");
  rdFollowMagnetsCollapsed = !!collapsed;
  if (list) list.classList.toggle("is-hidden", rdFollowMagnetsCollapsed);
  if (btn) {
    btn.classList.toggle("is-collapsed", rdFollowMagnetsCollapsed);
    btn.textContent = "\u25be";
    btn.title = rdFollowMagnetsCollapsed ? "Mostrar magnets" : "Ocultar magnets";
    btn.setAttribute("aria-pressed", rdFollowMagnetsCollapsed ? "true" : "false");
  }
  if (persist) {
    try { localStorage.setItem(rdFollowMagnetsStoreKey, rdFollowMagnetsCollapsed ? "collapsed" : "open"); } catch (e) {}
  }
}

function toggleRdFollowMagnets() {
  const list = document.getElementById("rdFollowMagnetsList");
  setRdFollowMagnetsCollapsed(!(list && list.classList.contains("is-hidden")), true);
}

function restoreRdFollowState() {
  let collapsed = false;
  try {
    collapsed = localStorage.getItem(rdFollowStoreKey) === "collapsed";
  } catch (e) {}
  setRdFollowCollapsed(collapsed, false);
  try {
    collapsed = localStorage.getItem(rdFollowMagnetsStoreKey) === "collapsed";
  } catch (e) {
    collapsed = false;
  }
  setRdFollowMagnetsCollapsed(collapsed, false);
  renderRdFollowMagnets();
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

function rdFollowMagnetKey(item) {
  return String(item?.hash || item?.magnet || item?.title || "").trim().toLowerCase();
}

function mergeRdFollowMagnets(items) {
  if (!Array.isArray(items)) return;
  items.forEach(raw => {
    const magnet = String(raw?.magnet || "").trim();
    if (!magnet) return;
    const item = {
      key: rdFollowMagnetKey(raw) || magnet,
      seq: raw.seq,
      ts: raw.ts || "",
      n: raw.n,
      total: raw.total,
      title: String(raw.title || "").trim() || "Magnet sin titulo",
      hash: String(raw.hash || "").trim(),
      size_gb: raw.size_gb,
      magnet
    };
    const index = rdFollowMagnets.findIndex(prev => rdFollowMagnetKey(prev) === item.key);
    if (index >= 0) rdFollowMagnets[index] = Object.assign({}, rdFollowMagnets[index], item);
    else rdFollowMagnets.push(item);
  });
  rdFollowMagnets = rdFollowMagnets.slice(-160);
}

function renderRdFollowMagnets() {
  const box = document.getElementById("rdFollowMagnetsList");
  const count = document.getElementById("rdFollowMagnetsCount");
  const items = rdFollowMagnets.slice(-120);
  if (count) {
    count.textContent = String(items.length || 0);
    count.className = "status-pill " + (items.length ? "good" : "mid");
  }
  if (!box) return;
  box.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "rd-follow-magnet-empty";
    empty.textContent = "Sin magnets enviados a RD todavía.";
    box.appendChild(empty);
    return;
  }
  items.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "rd-follow-magnet-row";

    const main = document.createElement("div");
    main.className = "rd-follow-magnet-main";

    const title = document.createElement("strong");
    title.className = "rd-follow-magnet-title";
    title.textContent = item.title || "Magnet sin titulo";
    title.title = item.title || "";

    const meta = document.createElement("span");
    meta.className = "rd-follow-magnet-meta";
    const pos = Number(item.n || 0) > 0 ? String(item.n) + (Number(item.total || 0) > 0 ? "/" + String(item.total) : "") : String(index + 1);
    const parts = ["#" + pos];
    if (Number(item.size_gb || 0) > 0) parts.push(String(item.size_gb) + " GB");
    if (item.hash) parts.push(item.hash.slice(0, 12));
    meta.textContent = parts.join(" · ");

    const btn = document.createElement("button");
    btn.className = "mini-copy rd-follow-magnet-copy";
    btn.type = "button";
    btn.title = "Copiar magnet";
    btn.textContent = "Copiar";
    btn.onclick = () => copyText(item.magnet, btn, "Magnet copiado");

    main.appendChild(title);
    main.appendChild(meta);
    row.appendChild(main);
    row.appendChild(btn);
    box.appendChild(row);
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
  mergeRdFollowMagnets(follow.magnets || []);
  renderRdFollowLines();
  renderRdFollowMagnets();
  if (!follow.has_diagnostics) {
    setRdFollowStatus("Esperando RD", "mid");
  } else if (String(follow.job_status || "").toLowerCase() === "cancelled" || summary.operation_status === "cancelled") {
    setRdFollowStatus("Cancelado", "mid");
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
    if (isTerminalJobStatus(status)) stopRdFollow(false);
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
    rdFollowMagnets = [];
  }
  setRdFollowStatus("Conectando", "mid");
  renderRdFollowLines();
  renderRdFollowMagnets();
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
    rdFollowMagnets = [];
    renderRdFollowMetrics({});
    renderRdFollowLines();
    renderRdFollowMagnets();
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
      setRdFollowStatus(data.error || "No arrancó", "bad");
      setActionButtonState(btn, "error", "!");
      if (data.running_job_id) startRdFollow(data.running_job_id, true, data.running_kind || "job");
      return;
    }
    startRdFollow(data.run_id || data.job_id, true, "rd_test");
    setActionButtonState(btn, "done", "OK");
  } catch (e) {
    setRdFollowStatus("Sin conexión", "bad");
    setActionButtonState(btn, "error", "!");
  }
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
  let rdVerifyDisplayIndex = 0;
  for (const raw of (lines || [])) {
    let line = formatLiveLine(raw);
    if (!line) continue;
    const rdOkPrefix = line.startsWith(rdOkVerifyTitleMarker);
    const visibleLine = rdOkPrefix ? line.slice(rdOkVerifyTitleMarker.length) : line;
    const rdMatch = visibleLine.match(/^Verificando\s+\d+\/(\d+):\s*(.+)$/i);
    if (rdMatch) {
      rdVerifyDisplayIndex += 1;
      line = `${rdOkPrefix ? rdOkVerifyTitleMarker : ""}${rdVerifyDisplayIndex}/${rdMatch[1]}: ${rdMatch[2]}`;
    }
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
  let match = text.match(/^(\d+\/\d+:\s*)(.+)$/i);
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

function createLogLineElement(line) {
  const div = document.createElement("div");
  div.className = "line";
  updateLogLineElement(div, line);
  return div;
}

function updateLogLineElement(div, line) {
  div.className = "line";
  div.dataset.rawLine = String(line || "");
  div.textContent = "";
  renderLogLine(div, line);
}

function renderLog(module) {
  const box = document.getElementById("log-" + module);
  if (!box) return;
  const lines = cleanLines(moduleLogs[module] || []);
  while (box.children.length > lines.length) box.removeChild(box.lastElementChild);
  lines.forEach((line, index) => {
    const current = box.children[index];
    const raw = String(line || "");
    if (current && current.dataset.rawLine === raw) return;
    if (current) updateLogLineElement(current, line);
    else box.appendChild(createLogLineElement(line));
  });
  box.scrollTop = box.scrollHeight;
}

function clearCurrent() {
  const query = document.getElementById("bQuery");
  if (query) query.value = "";
  setModuleResults("btdigg", [], true, true);
  moduleLogs.btdigg = ["Limpio. Preparado."];
  renderLog("btdigg");
  stopRdFollow(true);
  setStatus("Limpio");
  updateStopButton();
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
  applyJobPayloadToForm(job.payload);
  moduleLogs[module] = job.log || [];
  renderLog(module);
  if (isTerminalJobStatus(status)) {
    closeLive(module);
    moduleBusy[module] = false;
    setModuleResults(module, status === "done" ? (job.results || []) : [], true, true);
    historyCache = null;
    setStatus(jobStatusLabel(status));
    updateStopButton(status);
    clearActiveJob(id, module);
    if (id) startRdFollow(id, true, traceKind);
    finishRdFollow(id);
    if (options.notify) playFinishSound(id);
    return true;
  }
  moduleBusy[module] = true;
  saveActiveJob(id, module);
  startRdFollow(id, true, traceKind);
  setStatus(jobStatusLabel(status));
  updateStopButton(status);
  return true;
}

async function resumeJob(id, module = "btdigg", options = {}) {
  if (!id) return false;
  if (moduleBusy[module] && activeJobIds[module] === id) return true;
  try {
    const response = await fetch("/api/job/" + encodeURIComponent(id));
    const data = await response.json();
    if (!data.ok || !data.job) {
      clearActiveJob(id, module);
      return false;
    }
    const status = String(data.job.status || "");
    if (isTerminalJobStatus(status)) {
      applyJobSnapshot(data.job, module, options);
      return true;
    }
    activeModule = module;
    moduleBusy[module] = true;
    saveActiveJob(id, module);
    startRdFollow(id, false, String(data.job.kind || "job"));
    setStatus(jobStatusLabel(status));
    updateStopButton(status);
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

async function refreshSharedRuntime() {
  if (!visibleNow()) return;
  await loadQbitToggle({ silent: true });
  await loadSharedUiState(true);
  await loadSearchQueueStatus();
  const connected = await reconnectActiveJob();
  const now = Date.now();
  if (!connected && !moduleBusy.btdigg && now - lastResultsRefreshAt > 30000) {
    lastResultsRefreshAt = now;
    await loadResults(true);
  }
}

function startSharedRefresh() {
  if (sharedRefreshTimer) return;
  sharedRefreshTimer = setInterval(refreshSharedRuntime, 15000);
}

function pushLog(module, line) {
  if (!moduleLogs[module]) moduleLogs[module] = [];
  const nextLine = String(line || "");
  if (
    moduleLogs[module].length === 1 &&
    ["Conectando actividad LIVE...", "Reconectando actividad LIVE..."].includes(String(moduleLogs[module][0] || ""))
  ) {
    moduleLogs[module] = [];
  }
  if (moduleLogs[module].length && String(moduleLogs[module][moduleLogs[module].length - 1] || "") === nextLine) return;
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
  updateStopButton("running");
  moduleLogs[module] = ["Arrancando motor..."];
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
      updateStopButton("error");
      pushLog(module, "ERROR: " + (data.error || "no se pudo arrancar"));
      return;
    }
    saveActiveJob(data.job_id, module);
    startRdFollow(data.job_id, true);
    openLive(data.job_id, module);
  } catch (e) {
    moduleBusy[module] = false;
    setStatus("Error");
    updateStopButton("error");
    pushLog(module, "ERROR arrancando buscador: " + e);
  }
}

function openLive(id, module) {
  saveActiveJob(id, module);
  if (!window.EventSource) {
    poll(id, module);
    return;
  }
  let finished = false;
  let liveLogReceived = false;
  let fallbackStarted = false;
  let liveFallbackTimer = null;
  const clearLiveFallback = () => {
    if (liveFallbackTimer) clearTimeout(liveFallbackTimer);
    liveFallbackTimer = null;
  };
  const startPollingFallback = () => {
    if (finished || fallbackStarted) return;
    fallbackStarted = true;
    clearLiveFallback();
    closeLive(module);
    poll(id, module);
  };
  const es = new EventSource("/api/job/" + encodeURIComponent(id) + "/stream");
  liveStreams[module] = es;
  liveFallbackTimer = setTimeout(() => {
    if (!liveLogReceived) startPollingFallback();
  }, 2500);

  es.addEventListener("log", ev => {
    try {
      liveLogReceived = true;
      clearLiveFallback();
      const data = JSON.parse(ev.data || "{}");
      if (data.line) pushLog(module, data.line);
    } catch (e) {}
  });
  es.addEventListener("status", ev => {
    try {
      const data = JSON.parse(ev.data || "{}");
      setStatus(jobStatusLabel(data.status));
      updateStopButton(data.status);
    } catch (e) {}
  });
  es.addEventListener("done", ev => {
    finished = true;
    clearLiveFallback();
    let data = {};
    try { data = JSON.parse(ev.data || "{}"); } catch (e) {}
    closeLive(module);
    moduleBusy[module] = false;
    setStatus(jobStatusLabel(data.status));
    updateStopButton(data.status);
    setModuleResults(module, data.status === "done" ? (data.results || []) : [], true, true);
    historyCache = null;
    if (data.status === "cancelled" && (data.forced_stop || data.cleanup_uncertain)) {
      pushLog(module, "Aviso: cancelacion forzada. Revisa caja negra.");
    }
    clearActiveJob(id, module);
    finishRdFollow(id);
    playFinishSound(id);
  });
  es.onerror = () => {
    if (finished) return;
    startPollingFallback();
  };
}

async function poll(id, module) {
  let done = false;
  while (!done) {
    const response = await fetch("/api/job/" + encodeURIComponent(id));
    const data = await response.json();
    if (data.ok) {
      const nextLog = data.job.log || [];
      if (!isActiveJobStatus(data.job.status) || nextLog.length >= (moduleLogs[module] || []).length) {
        moduleLogs[module] = nextLog;
        renderLog(module);
      }
      if (isActiveJobStatus(data.job.status)) {
        setStatus(jobStatusLabel(data.job.status));
        updateStopButton(data.job.status);
      }
      if (isTerminalJobStatus(data.job.status)) {
        done = true;
        moduleBusy[module] = false;
        setStatus(jobStatusLabel(data.job.status));
        updateStopButton(data.job.status);
        setModuleResults(module, data.job.status === "done" ? (data.job.results || []) : [], true, true);
        historyCache = null;
        if (data.job.status === "cancelled" && (data.job.forced_stop || data.job.cleanup_uncertain)) {
          pushLog(module, "Aviso: cancelacion forzada. Revisa caja negra.");
        }
        clearActiveJob(id, module);
        finishRdFollow(id);
        playFinishSound(id);
      }
    }
    if (!done) await new Promise(resolve => setTimeout(resolve, 1000));
  }
}

async function stopBT() {
  const module = "btdigg";
  const saved = storedActiveJob();
  const id = activeJobIds[module] || (saved && saved.module === module ? saved.id : "");
  if (!id) {
    setStatus("Sin job");
    updateStopButton();
    return;
  }
  setStatus("Deteniendo...");
  updateStopButton("cancelling");
  pushLog(module, "Deteniendo busqueda...");
  try {
    const response = await fetch("/api/job/" + encodeURIComponent(id) + "/cancel", { method: "POST" });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "no se pudo detener");
    if (data.job) {
      applyJobSnapshot(data.job, module);
    } else {
      updateStopButton("cancelling");
    }
  } catch (e) {
    setStatus("Error detener");
    updateStopButton("running");
    pushLog(module, "ERROR deteniendo: " + e);
  }
}

function searchBT() {
  start({
    module: "btdigg",
    action: "search",
    query: document.getElementById("bQuery").value,
    pages: document.getElementById("bPages").value,
    mode: normalizeSearchMode(document.getElementById("bMode").value),
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

function resultsSignature(items) {
  try {
    return JSON.stringify((items || []).map(item => [
      item.index,
      item.title,
      item.link,
      item.size,
      item.status || item.confidence,
      item.added
    ]));
  } catch (e) {
    return String((items || []).length);
  }
}

function setModuleResults(module, items, show = true, force = false) {
  const next = items || [];
  const sig = resultsSignature(next);
  const changed = sig !== resultsSnapshot;
  moduleResults[module] = next;
  if (module === "btdigg") resultsSnapshot = sig;
  if (show && (force || changed)) renderResults(moduleResults[module]);
}

async function loadResults(show = true) {
  const response = await fetch("/api/results/btdigg", { cache: "no-store" });
  const data = await response.json();
  if (!data.ok) return false;
  setModuleResults("btdigg", data.results || [], show, false);
  return true;
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
  markUiStateChanged();
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

function titleResolveKey(item, idx) {
  const raw = item && item.raw ? item.raw : {};
  return String(item && (item.hash || item.btih || item.infohash || raw.hash || item.link || item.title || idx) || idx);
}

function titleResolveEvidence(item) {
  const raw = item && item.raw ? item.raw : {};
  return [
    item && item.title,
    item && item.name,
    item && item.link,
    raw.title,
    raw.name,
    raw.selected_file_name
  ].filter(Boolean).map(value => String(value));
}

function closeOtherTitleResolveRows(activeRow) {
  document.querySelectorAll(".result-detail-row").forEach(row => {
    if (row !== activeRow) row.classList.add("is-hidden");
  });
}

function renderTitleResolveLoading(detailRow) {
  detailRow.innerHTML = '<div class="results-cell result-detail-cell"><div class="title-resolve-card"><span class="status-pill mid">Cargando</span></div></div>';
}

function cleanTitleCopyValue(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Za-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function titleResolveBlock(label, title, copyTitle, copyWithYear) {
  const cleanCopyTitle = cleanTitleCopyValue(copyTitle || title || "");
  const cleanCopyWithYear = cleanTitleCopyValue(copyWithYear || title || "");
  return '' +
    '<section class="title-resolve-block">' +
      '<span class="title-resolve-label">' + esc(label) + '</span>' +
      '<strong class="title-resolve-text" title="' + escAttr(copyWithYear || title || "") + '">' + esc(copyWithYear || title || "-") + '</strong>' +
      '<div class="title-resolve-actions">' +
        '<button class="mini-copy" type="button" data-copy="' + escAttr(cleanCopyTitle) + '">Copiar</button>' +
        '<button class="mini-copy" type="button" data-copy="' + escAttr(cleanCopyWithYear) + '">+A\u00f1o</button>' +
      '</div>' +
    '</section>';
}

function bindTitleResolveCopies(detailRow) {
  detailRow.querySelectorAll(".mini-copy").forEach(btn => {
    btn.onclick = () => copyText(btn.dataset.copy || "", btn, "Copiado");
  });
}

function renderTitleResolveResult(detailRow, data) {
  if (!data || !data.ok) {
    detailRow.innerHTML = '<div class="results-cell result-detail-cell"><div class="title-resolve-card"><span class="status-pill bad">Error</span></div></div>';
    return;
  }
  if (data.status !== "resolved" || !data.safe || !data.copy) {
    detailRow.innerHTML = '<div class="results-cell result-detail-cell"><div class="title-resolve-card"><span class="status-pill mid">No seguro</span></div></div>';
    return;
  }
  const copy = data.copy || {};
  const english = copy.en || copy.english || copy.original || "";
  const englishWithYear = copy.en_with_year || copy.english_with_year || copy.original_with_year || english;
  detailRow.innerHTML =
    '<div class="results-cell result-detail-cell">' +
      '<div class="title-resolve-card is-resolved">' +
        '<div class="title-resolve-grid">' +
          titleResolveBlock("ES", copy.es, copy.es, copy.es_with_year) +
          titleResolveBlock("EN", english, english, englishWithYear) +
        '</div>' +
      '</div>' +
    '</div>';
  bindTitleResolveCopies(detailRow);
}

async function toggleTitleResolveCard(item, detailRow, btn, key) {
  if (!item || !detailRow) return;
  if (!detailRow.classList.contains("is-hidden") && titleResolveOpenKey === key) {
    detailRow.classList.add("is-hidden");
    titleResolveOpenKey = "";
    return;
  }
  closeOtherTitleResolveRows(detailRow);
  titleResolveOpenKey = key;
  detailRow.classList.remove("is-hidden");
  if (titleResolveCache[key]) {
    renderTitleResolveResult(detailRow, titleResolveCache[key]);
    return;
  }
  renderTitleResolveLoading(detailRow);
  setActionButtonState(btn, "loading");
  try {
    const response = await fetch("/api/title-resolver/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: item.title || "",
        evidence: titleResolveEvidence(item),
        media_hint: "movie"
      })
    });
    const data = await response.json();
    titleResolveCache[key] = data;
    renderTitleResolveResult(detailRow, data);
    setStatus(data.status === "resolved" ? "Titulo resuelto" : "No seguro");
    setActionButtonState(btn, "done", "OK");
  } catch (e) {
    titleResolveCache[key] = { ok: false };
    renderTitleResolveResult(detailRow, titleResolveCache[key]);
    setStatus("Error titulo");
    setActionButtonState(btn, "error", "!");
  }
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
    const resolveKey = titleResolveKey(item, idx);
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
        '<button class="result-icon result-title-resolve" type="button" title="Resolver titulo" aria-label="Resolver titulo">Aa</button>' +
      "</div>";
    const dl = row.querySelector(".result-download");
    const cp = row.querySelector(".result-copy");
    const tr = row.querySelector(".result-title-resolve");
    const detailRow = document.createElement("div");
    detailRow.className = "result-detail-row is-hidden";
    dl.onclick = () => downloadItem(item.index, dl);
    cp.onclick = () => copyText(item.link || "", cp);
    tr.onclick = () => toggleTitleResolveCard(item, detailRow, tr, resolveKey);
    table.appendChild(row);
    table.appendChild(detailRow);
  });
  box.appendChild(table);
}

async function loadHistory(force = false) {
  const panel = document.getElementById("historyPanel");
  if (!panel) return;
  if (force) {
    historyOpenState = { days: {}, searches: {} };
    historyResultStore = {};
    markUiStateChanged();
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
      markUiStateChanged();
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
        markUiStateChanged();
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
        const sizeText = item.size || "-";
        const addedText = translateAddedLabel(item.added || "hoy");
        const resultKey = searchKey + "-" + originalIndex;
        historyResultStore[resultKey] = {
          item,
          historyId: search.id || "",
          historyResult: originalIndex + 1
        };
        result.className = "history-result";
        const resolveKey = "history-" + resultKey;
        result.innerHTML =
          '<div class="history-result-scroll">' +
            '<div class="history-result-main">' +
              '<strong>' + esc(item.title || "(sin t\u00edtulo)") + '</strong>' +
              '<span class="history-result-meta">' +
                '<span class="history-result-size">' + esc(sizeText) + '</span>' +
                '<span class="history-result-sep"> &middot; </span>' +
                '<span class="history-result-added">' + esc(addedText) + '</span>' +
              '</span>' +
            '</div>' +
          '</div>' +
          '<div class="history-result-actions">' +
            '<button class="result-icon result-download history-download history-route-btn history-route-' + escAttr(routeKind) + '" type="button" title="' + escAttr(routeTitle) + '" aria-label="' + escAttr(routeTitle) + '">' + esc(routeLabel) + '</button>' +
            '<button class="result-icon result-title-resolve history-title-resolve" type="button" title="Resolver titulo" aria-label="Resolver titulo">Aa</button>' +
          '</div>';
        const dl = result.querySelector(".history-download");
        const tr = result.querySelector(".history-title-resolve");
        const detailRow = document.createElement("div");
        detailRow.className = "result-detail-row history-detail-row is-hidden";
        if (dl) dl.onclick = () => downloadHistoryItem(resultKey, dl);
        if (tr) tr.onclick = () => toggleTitleResolveCard(item, detailRow, tr, resolveKey);
        results.appendChild(result);
        results.appendChild(detailRow);
      });
      searchCard.appendChild(results);
      searchesBox.appendChild(searchCard);
    });
    dayCard.appendChild(searchesBox);
    panel.appendChild(dayCard);
  });
}

async function copyText(text, btn = null, successMessage = "Enlace copiado") {
  if (!text) {
    setStatus("Sin texto");
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
    setStatus(successMessage || "Copiado");
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
  if (id === "bMode") value = normalizeSearchMode(value);
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

const SETTINGS_RESET_FALLBACK_VALUES = {
  default_mode: "0",
  default_pages: "1-3",
  safe_max_pages_when_zero: "30",
  max_results_to_show: "80",
  min_size_gb: "0",
  max_size_gb: "400",
  request_timeout_sec: "30",
  delay_between_btdigg_pages_sec: "3",
  pack_query_match_min_ratio: "0.55",
  verify_max_candidates: "60",
  verify_wait_sec: "0.25",
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
  qbit_probe_max_candidates: "40",
  qbit_probe_wait_sec: "35",
  qbit_same_file_min_ratio: "0.9",
  qbit_probe_parallel_workers: "5",
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

function settingsDefaultMap() {
  const out = { ...SETTINGS_RESET_FALLBACK_VALUES };
  const cfg = settingsCache && settingsCache.btdigg ? settingsCache.btdigg : {};
  (cfg.fields || []).forEach(field => {
    if (!field || !field.key || field.default === undefined || field.default === null) return;
    out[field.key] = field.default;
  });
  return out;
}

function applySettingsResetValues() {
  const resetValues = settingsDefaultMap();
  Object.keys(resetValues).forEach(key => {
    const el = document.querySelector('#settingsPanel [data-key="' + escAttr(key) + '"], #settingsRdPanel [data-key="' + escAttr(key) + '"]');
    if (!el) return;
    if (el.dataset.type === "bool") {
      el.checked = Boolean(resetValues[key]);
    } else {
      el.value = String(resetValues[key]);
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
  if (el) {
    el.addEventListener("input", () => saveFormState(true));
    el.addEventListener("change", () => saveFormState(true));
  }
});

["rdFollowQuery", "rdFollowPages"].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener("input", saveRdFollowTestState);
});

const queueTitleInput = document.getElementById("queueTitle");
if (queueTitleInput) {
  queueTitleInput.addEventListener("keydown", ev => {
    if (ev.key !== "Enter" || ev.isComposing) return;
    ev.preventDefault();
    addSearchQueueItem();
  });
}

async function initApp() {
  restoreFormState();
  restoreSearchQueueDraft();
  renderSearchQueue();
  restoreActivityState();
  restoreRdFollowState();
  const canAttemptVoice = !window.isSecureContext || (navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
  setVoiceButtonState(canAttemptVoice ? "idle" : "unsupported");
  const restoredShared = await loadSharedUiState(false);
  if (!restoredShared) restoreViewState();
  await loadQbitToggle();
  setQueueQbitState(qbitSearchEnabled);
  await loadSearchQueueStatus();
  loadSettings(true);
  updateStopButton();
  const connected = await reconnectActiveJob();
  if (!connected) await loadResults(true);
  startSharedRefresh();
}

initApp();

window.addEventListener("pageshow", () => {
  refreshSharedRuntime();
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshSharedRuntime();
});
