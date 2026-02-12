const activeList = document.getElementById("active-list");
const doneList = document.getElementById("done-list");
const statusEl = document.getElementById("status");
const textarea = document.getElementById("urls");
const enqueueBtn = document.getElementById("enqueue");

const STEP_ORDER = ["Metadata", "Resolve", "Download", "Remux", "Tagging", "Saved"];
const STEP_WEIGHTS = {
  Metadata: 0.6,
  Resolve: 0.7,
  Download: 3.6,
  Remux: 1.4,
  Tagging: 1.0,
  Saved: 0.6,
};
const MIN_STEP_GAP = 6; // percent
const STEP_POSITIONS = computeStepPositions(STEP_ORDER, STEP_WEIGHTS, MIN_STEP_GAP);
const STEP_WEIGHT_TOTAL = STEP_ORDER.reduce(
  (sum, step) => sum + (STEP_WEIGHTS[step] ?? 1),
  0
);

const items = new Map();

function mapStep(label) {
  if (!label) return null;
  const lower = label.toLowerCase();
  if (lower.includes("write metadata")) return "Remux";
  if (lower.startsWith("metadata")) return "Metadata";
  if (lower.startsWith("resolve")) return "Resolve";
  if (lower.includes("video data")) return "Download";
  if (lower.includes("audio data")) return "Download";
  if (lower.includes("media data")) return "Download";
  if (lower.startsWith("download")) return "Download";
  if (lower.includes("post-process")) return "Remux";
  if (lower.includes("remux")) return "Remux";
  if (lower.includes("merge")) return "Remux";
  if (lower.includes("extract")) return "Remux";
  if (lower.includes("convert")) return "Remux";
  if (lower.includes("fixup")) return "Remux";
  if (lower.includes("embed artwork")) return "Remux";
  if (lower.includes("thumbnail")) return "Remux";
  if (lower.includes("tagging")) return "Tagging";
  if (lower.includes("saved")) return "Saved";
  return null;
}

function createItem(item) {
  const container = document.createElement("div");
  container.className = "item";
  container.dataset.id = item.id;

  const row = document.createElement("div");
  row.className = "row";

  const title = document.createElement("div");
  title.className = "title-line";
  title.textContent = item.title || item.url;

  row.appendChild(title);

  const progressRow = document.createElement("div");
  progressRow.className = "progress-row";

  const progress = document.createElement("div");
  progress.className = "progress";

  const barWrap = document.createElement("div");
  barWrap.className = "bar-wrap";
  const bar = document.createElement("div");
  bar.className = "bar";
  const fill = document.createElement("div");
  fill.className = "fill";
  bar.appendChild(fill);

  const stepDots = [];
  const stepsOverlay = document.createElement("div");
  stepsOverlay.className = "bar-steps";
  STEP_ORDER.forEach((step, index) => {
    const dot = document.createElement("div");
    dot.className = "step-dot";
    dot.dataset.step = step;
    const pos = STEP_POSITIONS[index] ?? 0;
    dot.style.left = `${pos}%`;
    dot.dataset.pos = String(pos);
    stepsOverlay.appendChild(dot);
    stepDots.push(dot);
  });
  barWrap.appendChild(bar);
  barWrap.appendChild(stepsOverlay);
  progress.appendChild(barWrap);

  const stepMeta = document.createElement("div");
  stepMeta.className = "step-meta";
  const stepText = document.createElement("div");
  stepText.className = "step-text";
  stepText.textContent = "metadata";
  const progressText = document.createElement("div");
  progressText.className = "progress-text";
  stepMeta.appendChild(stepText);
  stepMeta.appendChild(progressText);

  progressRow.appendChild(progress);
  progressRow.appendChild(stepMeta);

  const paths = document.createElement("div");
  paths.className = "paths";

  container.appendChild(row);
  container.appendChild(progressRow);
  container.appendChild(paths);

  container._els = {
    title,
    fill,
    bar,
    barWrap,
    stepDots,
    stepText,
    progressText,
    paths,
  };
  container._state = {
    currentIndex: null,
    completedIndex: -1,
    downloadPercent: 0,
    speedText: "",
    etaSeconds: null,
    lastSpeedAt: 0,
    lastEtaUpdateAt: 0,
    etaOverall: null,
    etaOverallAt: 0,
    stepDurations: {},
    overallPercent: 0,
  };
  return container;
}

function upsertItem(item) {
  let node = items.get(item.id);
  if (!node) {
    node = createItem(item);
    items.set(item.id, node);
    activeList.appendChild(node);
  }
  updateItem(node, item);
}

function updateItem(node, item) {
  const { title } = node._els;
  title.textContent = item.title || item.url || "";
  if (item.current) {
    setActiveStep(node, item.current);
    if (!item.progress) {
      node._els.stepText.textContent = item.current.toLowerCase();
    }
  }
  if (item.progress) {
    updateProgress(node, item.progress);
  }
  if (item.steps) {
    Object.entries(item.steps).forEach(([label, payload]) => {
      setStepState(node, label, payload);
    });
  }
  if (item.paths && item.paths.length) {
    setPaths(node, item.paths);
  }
  if (item.error) {
    const { paths: container } = node._els;
    container.innerHTML = "";
    const line = document.createElement("div");
    line.className = "path error";
    line.textContent = item.error;
    container.appendChild(line);
  }
  if (item.status === "done" || item.status === "error") {
    moveToDone(node, item.status);
  }
}

function setActiveStep(node, label) {
  const step = mapStep(label);
  if (!step) return;
  updateStepBar(node, step);
}

function setStepState(node, label, payload) {
  const step = mapStep(label);
  if (!step) return;
  const ok = payload?.ok;
  const duration = Number.isFinite(payload?.duration) ? Number(payload.duration) : null;
  const index = STEP_ORDER.indexOf(step);
  if (ok === true && index >= 0) {
    markCompleted(node, index);
    if (duration != null) {
      node._state.stepDurations[step] = duration;
    }
  }
  if (ok === false) {
    node._els.bar.classList.add("error");
  }
  const state = node._state || { currentIndex: null };
  if (state.currentIndex == null || index > state.currentIndex) {
    updateStepBar(node, step);
  } else {
    updateOverallBar(node);
  }
}

function updateProgress(node, progress) {
  const total = progress.total;
  const downloaded = progress.downloaded;
  const speed = progress.speed_display || "";
  const eta = Number.isFinite(progress.eta) ? Number(progress.eta) : null;
  if (total && downloaded) {
    node._state.downloadPercent = Math.min(1, downloaded / total);
  }
  const now = Date.now();
  if (speed) {
    node._state.speedText = speed;
    node._state.lastSpeedAt = now;
  }
  if (eta != null) {
    const last = node._state.lastEtaUpdateAt || 0;
    if (!last || now - last > 3000) {
      node._state.etaSeconds = eta;
      node._state.lastEtaUpdateAt = now;
    }
  }
  updateOverallBar(node);
}

function updateStepBar(node, step) {
  const index = STEP_ORDER.indexOf(step);
  if (index < 0) return;
  const state = node._state || { currentIndex: null, completedIndex: -1 };
  const prevIndex = state.currentIndex;
  if (state.completedIndex == null) {
    state.completedIndex = -1;
  }
  if (index > 0 && state.completedIndex < index - 1) {
    state.completedIndex = index - 1;
  }

  const stepText = node._els.stepText;
  state.currentIndex = index;

  if (prevIndex !== index) {
    stepText.classList.add("step-change");
    updateOverallBar(node);
    window.setTimeout(() => {
      stepText.textContent = step.toLowerCase();
      stepText.classList.remove("step-change");
    }, 200);
  } else {
    updateOverallBar(node);
  }
}

function markCompleted(node, stepIndex) {
  const cap = Math.max(0, STEP_ORDER.length - 1);
  const target = Math.min(stepIndex, cap);
  if (node._state.completedIndex == null || target > node._state.completedIndex) {
    node._state.completedIndex = target;
  }
}

function refreshDots(node) {
  const dots = node._els.stepDots;
  const state = node._state || { currentIndex: 0, completedIndex: -1 };
  const currentIndex = Math.max(0, state.currentIndex ?? 0);
  const overallPercent = Math.max(0, Math.min(1, state.overallPercent ?? 0)) * 100;
  dots.forEach((dot, i) => {
    const pos = Number(dot.dataset.pos || 0);
    dot.classList.toggle("done", overallPercent >= pos - 0.5);
    dot.classList.toggle("active", i === currentIndex);
    dot.classList.toggle("next", i === currentIndex + 1);
    dot.classList.toggle("future", i > currentIndex + 1);
  });
}

function updateOverallBar(node) {
  const { fill, bar, progressText } = node._els;
  const state = node._state || { currentIndex: 0, completedIndex: 0, downloadPercent: 0 };
  const currentIndex = Math.max(0, state.currentIndex ?? 0);
  const downloadIndex = STEP_ORDER.indexOf("Download");
  let completedIndex = state.completedIndex ?? -1;
  if (completedIndex < currentIndex - 1) {
    completedIndex = currentIndex - 1;
  }
  let baseWeight = 0;
  for (let i = 0; i <= completedIndex; i += 1) {
    baseWeight += STEP_WEIGHTS[STEP_ORDER[i]] ?? 1;
  }
  let stepWeight = STEP_WEIGHTS[STEP_ORDER[currentIndex]] ?? 1;
  let stepFrac = 0;
  if (completedIndex < currentIndex) {
    if (currentIndex === downloadIndex && state.downloadPercent != null) {
      stepFrac = state.downloadPercent;
    }
  } else {
    stepWeight = 0;
  }
  const progressWeight = baseWeight + stepFrac * stepWeight;
  let overall = STEP_WEIGHT_TOTAL > 0 ? progressWeight / STEP_WEIGHT_TOTAL : 0;
  overall = Math.max(0, Math.min(1, overall));
  state.overallPercent = overall;
  fill.style.width = `${(overall * 100).toFixed(1)}%`;
  bar.classList.toggle("indeterminate", overall === 0 && !state.downloadPercent);
  refreshDots(node);
  const percentText = `${Math.round(overall * 100)}%`;
  const now = Date.now();
  let speed = state.speedText || "";
  if (speed && now - (state.lastSpeedAt || 0) > 8000) {
    speed = "";
  }
  let etaText = "";
  const etaSource = estimateEtaSeconds({
    state,
    currentIndex,
    stepWeight,
    stepFrac,
    progressWeight,
    downloadIndex,
  });
  if (etaSource != null) {
    if (!state.etaOverallAt || now - state.etaOverallAt > 3000) {
      state.etaOverall = etaSource;
      state.etaOverallAt = now;
    }
  }
  if (state.etaOverallAt && now - state.etaOverallAt > 15000) {
    state.etaOverall = null;
    state.etaOverallAt = 0;
  }
  if (state.etaOverall != null && state.etaOverallAt) {
    const elapsed = (now - state.etaOverallAt) / 1000;
    const remaining = Math.max(0, Math.round(state.etaOverall - elapsed));
    etaText = formatEta(remaining);
  }
  const parts = [percentText];
  if (speed) parts.push(speed);
  if (etaText) parts.push(etaText);
  progressText.textContent = parts.join(" · ");
}

function setPaths(node, paths) {
  const { paths: container } = node._els;
  container.innerHTML = "";
  paths.forEach((p) => {
    const line = document.createElement("button");
    line.className = "path";
    line.type = "button";
    line.textContent = p;
    line.addEventListener("click", () => openPath(p));
    container.appendChild(line);
  });
}

function moveToDone(node, status) {
  if (node.parentElement === doneList) return;
  node.classList.toggle("done", status === "done");
  doneList.prepend(node);
}

function handleMessage(msg) {
  if (msg.type === "queued") {
    upsertItem(msg.item);
    return;
  }
  const node = items.get(msg.id);
  if (!node) {
    upsertItem({ id: msg.id, url: msg.url || "", status: "queued" });
  }
  const current = items.get(msg.id);
  if (!current) return;

  if (msg.type === "meta") {
    updateItem(current, {
      id: msg.id,
      title: msg.title,
      status: "running",
      provider: msg.provider,
      kind: msg.kind,
    });
  } else if (msg.type === "status") {
    updateItem(current, { id: msg.id, current: msg.label, status: "running" });
  } else if (msg.type === "progress") {
    updateItem(current, { id: msg.id, progress: msg });
  } else if (msg.type === "step") {
    updateItem(current, {
      id: msg.id,
      steps: { [msg.step]: { ok: msg.ok, detail: msg.detail, duration: msg.duration } },
    });
  } else if (msg.type === "done") {
    updateItem(current, {
      id: msg.id,
      status: "done",
      paths: msg.paths || [],
    });
  } else if (msg.type === "error") {
    updateItem(current, { id: msg.id, status: "error", error: msg.message });
  }
}

function connectEvents() {
  const es = new EventSource("/events");
  es.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleMessage(msg);
    } catch (err) {
      console.warn("bad message", err);
    }
  };
  es.onerror = () => {
    setStatus("disconnected", "reconnecting");
  };
  es.onopen = () => {
    setStatus("connected", "connected");
  };
}

async function loadState() {
  const res = await fetch("/state");
  if (!res.ok) return;
  const payload = await res.json();
  (payload.items || []).forEach((item) => upsertItem(item));
}

async function enqueueUrls() {
  const text = textarea.value.trim();
  if (!text) return;
  const urls = text
    .split(/\r?\n/)
    .map((u) => u.trim())
    .filter(Boolean);
  if (!urls.length) return;
  textarea.value = "";
  await fetch("/enqueue", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls }),
  });
}

async function openPath(path) {
  await fetch("/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
}

enqueueBtn.addEventListener("click", enqueueUrls);
textarea.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    enqueueUrls();
  }
});
textarea.addEventListener("input", () => {
  autosizeTextarea(textarea);
});

loadState();
connectEvents();
autosizeTextarea(textarea);

function computeStepPositions(steps, weightsMap, minGap) {
  const weights = steps.map((step) => weightsMap[step] ?? 1);
  const total = weights.reduce((sum, v) => sum + v, 0) || 1;
  const positions = [];
  let acc = 0;
  for (let i = 0; i < steps.length; i += 1) {
    positions.push((acc / total) * 100);
    acc += weights[i];
  }
  positions[positions.length - 1] = 100;
  if (!minGap || positions.length <= 1) return positions;
  const minGapValue = Math.max(2, minGap);
  for (let i = 1; i < positions.length; i += 1) {
    const gap = positions[i] - positions[i - 1];
    if (gap < minGapValue) {
      positions[i] = positions[i - 1] + minGapValue;
    }
  }
  for (let i = positions.length - 2; i >= 0; i -= 1) {
    if (positions[i + 1] > 100) {
      positions[i + 1] = 100;
    }
    const gap = positions[i + 1] - positions[i];
    if (gap < minGapValue) {
      positions[i] = positions[i + 1] - minGapValue;
    }
  }
  positions[0] = 0;
  positions[positions.length - 1] = 100;
  return positions.map((v) => Math.max(0, Math.min(100, v)));
}

function estimateEtaSeconds({
  state,
  currentIndex,
  stepWeight,
  stepFrac,
  progressWeight,
  downloadIndex,
}) {
  const total = STEP_WEIGHT_TOTAL || 1;
  const remainingWeight = Math.max(0, total - progressWeight);
  if (remainingWeight <= 0) return 0;
  if (currentIndex === downloadIndex && state.etaSeconds != null) {
    const remainingDownloadWeight = Math.max(0.01, (1 - stepFrac) * stepWeight);
    const perWeight = state.etaSeconds / remainingDownloadWeight;
    return perWeight * remainingWeight;
  }
  const durations = state.stepDurations || {};
  let doneWeight = 0;
  let doneSeconds = 0;
  Object.entries(durations).forEach(([step, duration]) => {
    const weight = STEP_WEIGHTS[step] ?? 1;
    if (Number.isFinite(duration) && duration > 0) {
      doneWeight += weight;
      doneSeconds += duration;
    }
  });
  if (doneWeight > 0 && doneSeconds > 0) {
    const perWeight = doneSeconds / doneWeight;
    return perWeight * remainingWeight;
  }
  return null;
}

function formatEta(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  }
  return `${m}:${String(sec).padStart(2, "0")}`;
}

function setStatus(state, label) {
  if (!statusEl) return;
  statusEl.classList.remove("status-connected", "status-disconnected");
  if (state === "connected") {
    statusEl.classList.add("status-connected");
  } else {
    statusEl.classList.add("status-disconnected");
  }
  const text = statusEl.querySelector(".status-text");
  if (text) {
    text.textContent = label;
  } else {
    statusEl.textContent = label;
  }
}

function autosizeTextarea(el) {
  if (!el) return;
  el.style.height = "auto";
  const maxHeight = 120;
  const next = Math.min(maxHeight, el.scrollHeight);
  el.style.height = `${next}px`;
}
