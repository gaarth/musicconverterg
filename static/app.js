const form = document.getElementById("convert-form");
const urlInput = document.getElementById("url-input");
const submitBtn = document.getElementById("submit-btn");
const formError = document.getElementById("form-error");
const playlistPanel = document.getElementById("playlist-panel");
const playlistTitle = document.getElementById("playlist-title");
const playlistMeta = document.getElementById("playlist-meta");
const trackList = document.getElementById("track-list");
const selectionCount = document.getElementById("selection-count");
const selectAllBtn = document.getElementById("select-all-btn");
const selectNoneBtn = document.getElementById("select-none-btn");
const downloadSelectedBtn = document.getElementById("download-selected-btn");
const downloadAllBtn = document.getElementById("download-all-btn");

const trimForm = document.getElementById("trim-form");
const trimUrl = document.getElementById("trim-url");
const trimSubmit = document.getElementById("trim-submit");
const trimError = document.getElementById("trim-error");
const trimPanel = document.getElementById("trim-panel");
const trimTitle = document.getElementById("trim-title");
const trimMeta = document.getElementById("trim-meta");
const trimTrackList = document.getElementById("trim-track-list");
const trimStart = document.getElementById("trim-start");
const trimEnd = document.getElementById("trim-end");
const trimFrom = document.getElementById("trim-from");
const trimTo = document.getElementById("trim-to");
const trimFill = document.getElementById("trim-fill");
const trimSpan = document.getElementById("trim-span");
const trimDownload = document.getElementById("trim-download");

const queuePanel = document.getElementById("queue-panel");
const queueList = document.getElementById("queue-list");
const clearQueueBtn = document.getElementById("clear-queue");

let resolved = null;
let selectedIds = new Set();
let trimCollection = null;
let trimTrack = null;
let queueTimer = null;

function selectedFormat() {
  const checked = form.querySelector('input[name="format"]:checked');
  return checked ? checked.value : "mp3";
}

function trimFormat() {
  const checked = trimForm.querySelector('input[name="trim-format"]:checked');
  return checked ? checked.value : "mp3";
}

function formatClock(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || seconds === "") return "";
  const total = Math.round(Number(seconds));
  if (!Number.isFinite(total) || total <= 0) return "";
  return formatClock(total);
}

function parseTime(value) {
  const raw = String(value || "").trim();
  if (!raw) return null;
  if (/^\d+(\.\d+)?$/.test(raw)) return Number(raw);
  const parts = raw.split(":").map((part) => Number(part));
  if (parts.some((n) => !Number.isFinite(n) || n < 0) || parts.length < 2 || parts.length > 3) {
    return null;
  }
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return parts[0] * 3600 + parts[1] * 60 + parts[2];
}

function showError(el, message) {
  el.hidden = !message;
  el.textContent = message || "";
}

function apiError(data, fallback) {
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg).join(", ");
  return fallback;
}

function setResolving(busy) {
  submitBtn.disabled = busy;
  submitBtn.textContent = busy ? "Resolving…" : "Resolve link";
}

function hidePlaylist() {
  playlistPanel.hidden = true;
  trackList.innerHTML = "";
  resolved = null;
  selectedIds = new Set();
}

function updateSelectionUi() {
  const count = selectedIds.size;
  selectionCount.textContent = count === 1 ? "1 selected" : `${count} selected`;
  downloadSelectedBtn.disabled = count === 0;
  downloadSelectedBtn.textContent =
    count > 1 ? `Add selected to queue (${count}) · zip` : "Add selected to queue";
}

function renderTracks(collection) {
  resolved = collection;
  selectedIds = new Set(collection.tracks.map((t) => t.id));
  playlistPanel.hidden = false;
  playlistTitle.textContent = collection.title || "Playlist";
  playlistMeta.textContent = [collection.source, collection.kind, `${collection.track_count} tracks`]
    .filter(Boolean)
    .join(" · ");

  trackList.innerHTML = "";
  collection.tracks.forEach((track, index) => {
    const row = document.createElement("label");
    row.className = "track-row is-selected";
    row.dataset.id = track.id;
    row.setAttribute("role", "listitem");

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) selectedIds.add(track.id);
      else selectedIds.delete(track.id);
      row.classList.toggle("is-selected", checkbox.checked);
      updateSelectionUi();
    });

    const copy = document.createElement("div");
    copy.className = "track-copy";
    const nameEl = document.createElement("p");
    nameEl.className = "track-name";
    nameEl.textContent = track.title || `Track ${index + 1}`;
    const artistEl = document.createElement("p");
    artistEl.className = "track-artist";
    artistEl.textContent = track.artists || "Unknown artist";
    copy.append(nameEl, artistEl);

    const side = document.createElement("div");
    side.className = "track-side";
    const duration = formatDuration(track.duration);
    if (duration) {
      const dur = document.createElement("span");
      dur.className = "track-duration";
      dur.textContent = duration;
      side.appendChild(dur);
    }

    const oneBtn = document.createElement("button");
    oneBtn.type = "button";
    oneBtn.className = "track-one";
    oneBtn.textContent = "Queue";
    oneBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      queueDownload([track], { title: track.title, source: collection.source });
    });
    side.appendChild(oneBtn);

    row.append(checkbox, copy, side);
    trackList.appendChild(row);
  });

  updateSelectionUi();
}

function ensureQueuePolling() {
  if (queueTimer) return;
  queueTimer = setInterval(refreshQueue, 1000);
}

async function refreshQueue() {
  try {
    const res = await fetch("/api/jobs");
    const data = await res.json();
    if (!res.ok) return;
    renderQueue(data.jobs || []);
    const active = (data.jobs || []).some((job) => job.status === "queued" || job.status === "running");
    if (!active && queueTimer) {
      clearInterval(queueTimer);
      queueTimer = null;
    }
  } catch {
    /* keep the last queue paint if a poll fails */
  }
}

function renderQueue(jobs) {
  if (!jobs.length) {
    queuePanel.hidden = true;
    queueList.innerHTML = "";
    return;
  }
  queuePanel.hidden = false;
  queueList.innerHTML = "";
  jobs.forEach((job) => {
    const card = document.createElement("article");
    card.className = `queue-card${job.status === "done" ? " is-done" : ""}${job.status === "error" ? " is-error" : ""}`;

    const top = document.createElement("div");
    top.className = "queue-top";
    const title = document.createElement("p");
    title.className = "queue-title";
    title.textContent = job.title || "Download";
    const meta = document.createElement("p");
    meta.className = "queue-meta";
    const range =
      job.start != null && job.end != null
        ? `${formatClock(job.start)}–${formatClock(job.end)}`
        : null;
    meta.textContent = [job.status, job.format?.toUpperCase(), job.source, range, job.total_items > 1 ? `${job.completed_items}/${job.total_items}` : null]
      .filter(Boolean)
      .join(" · ");
    top.append(title, meta);

    const message = document.createElement("p");
    message.className = "queue-message";
    message.textContent = job.error || job.message || "";

    const track = document.createElement("div");
    track.className = "progress-track";
    const bar = document.createElement("div");
    bar.className = "progress-bar";
    bar.style.width = `${Math.max(0, Math.min(100, job.progress || 0))}%`;
    track.appendChild(bar);

    card.append(top, message, track);

    if (job.status === "done" && job.download_ready) {
      const link = document.createElement("a");
      link.className = "download-link";
      link.href = `/api/jobs/${job.id}/download`;
      link.download = job.result_name || "download";
      const isZip = (job.result_name || "").toLowerCase().endsWith(".zip");
      link.textContent = isZip ? `Download zip · ${job.result_name}` : `Download ${job.result_name || "file"}`;
      card.appendChild(link);
    }

    queueList.appendChild(card);
  });
}

clearQueueBtn.addEventListener("click", async () => {
  clearQueueBtn.disabled = true;
  try {
    const res = await fetch("/api/jobs", { method: "DELETE" });
    const data = await res.json();
    if (!res.ok) throw new Error(apiError(data, "Could not clear the queue"));
    renderQueue(data.jobs || []);
  } catch (err) {
    showError(formError, err.message || "Could not clear the queue");
  } finally {
    clearQueueBtn.disabled = false;
  }
});

async function queueDownload(tracks, extra = {}) {
  if (!tracks.length) return;
  showError(formError, "");
  try {
    const body = {
      format: extra.format || selectedFormat(),
      title: extra.title || resolved?.title || tracks[0].title || "Selected tracks",
      source: extra.source || resolved?.source || trimCollection?.source || "",
      url: extra.url || urlInput.value.trim() || trimUrl.value.trim() || null,
      tracks,
    };
    if (extra.start != null && extra.end != null) {
      body.start = extra.start;
      body.end = extra.end;
      body.title = `${body.title} (${formatClock(extra.start)}–${formatClock(extra.end)})`;
    }
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiError(data, "Could not queue download"));
    ensureQueuePolling();
    await refreshQueue();
    queuePanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    showError(extra.errorEl || formError, err.message || "Request failed");
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  showError(formError, "");
  hidePlaylist();
  setResolving(true);

  try {
    const res = await fetch("/api/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: urlInput.value.trim() }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiError(data, "Could not resolve link"));
    if (!data.is_playlist || data.tracks.length === 1) {
      resolved = data;
      await queueDownload(data.tracks, { title: data.title, source: data.source });
      return;
    }
    renderTracks(data);
  } catch (err) {
    showError(formError, err.message || "Request failed");
  } finally {
    setResolving(false);
  }
});

selectAllBtn.addEventListener("click", () => {
  if (!resolved) return;
  selectedIds = new Set(resolved.tracks.map((t) => t.id));
  trackList.querySelectorAll(".track-row").forEach((row) => {
    row.classList.add("is-selected");
    const input = row.querySelector('input[type="checkbox"]');
    if (input) input.checked = true;
  });
  updateSelectionUi();
});

selectNoneBtn.addEventListener("click", () => {
  selectedIds = new Set();
  trackList.querySelectorAll(".track-row").forEach((row) => {
    row.classList.remove("is-selected");
    const input = row.querySelector('input[type="checkbox"]');
    if (input) input.checked = false;
  });
  updateSelectionUi();
});

downloadSelectedBtn.addEventListener("click", () => {
  if (!resolved) return;
  queueDownload(resolved.tracks.filter((t) => selectedIds.has(t.id)));
});

downloadAllBtn.addEventListener("click", () => {
  if (!resolved) return;
  queueDownload(resolved.tracks);
});

function sliderMax() {
  const duration = Number(trimTrack?.duration) || 0;
  return duration > 0 ? Math.floor(duration) : 3 * 60 * 60;
}

function readRange() {
  return {
    start: Number(trimStart.value),
    end: Number(trimEnd.value),
  };
}

function paintTrim() {
  const max = Number(trimStart.max) || 1;
  const start = Number(trimStart.value);
  const end = Number(trimEnd.value);
  const left = (start / max) * 100;
  const width = ((end - start) / max) * 100;
  trimFill.style.left = `${left}%`;
  trimFill.style.width = `${Math.max(width, 0)}%`;
  trimFrom.value = formatClock(start);
  trimTo.value = formatClock(end);
  const total = trimTrack?.duration ? ` of ${formatClock(trimTrack.duration)}` : "";
  trimSpan.textContent = `${formatClock(Math.max(0, end - start))} selected${total}`;
}

function setRange(start, end) {
  const max = sliderMax();
  const safeStart = Math.max(0, Math.min(start, max - 1));
  const safeEnd = Math.max(safeStart + 1, Math.min(end, max));
  trimStart.max = String(max);
  trimEnd.max = String(max);
  trimStart.value = String(Math.round(safeStart));
  trimEnd.value = String(Math.round(safeEnd));
  paintTrim();
}

function applyPreset(seconds) {
  setRange(0, seconds);
}

function selectTrimTrack(track) {
  trimTrack = track;
  trimTrackList.querySelectorAll(".track-row").forEach((row) => {
    row.classList.toggle("is-selected", row.dataset.id === String(track.id));
  });
  const duration = Number(track.duration) || 0;
  const end = duration > 0 ? Math.min(120, duration) : 120;
  setRange(0, end);
  trimMeta.textContent = [
    trimCollection?.source,
    track.artists,
    track.duration ? formatClock(track.duration) : "length unknown — type a range",
  ]
    .filter(Boolean)
    .join(" · ");
}

function renderTrimTracks(collection) {
  trimTrackList.innerHTML = "";
  if (collection.tracks.length <= 1) {
    trimTrackList.hidden = true;
    return;
  }
  trimTrackList.hidden = false;
  collection.tracks.forEach((track, index) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "track-row";
    row.dataset.id = track.id;
    row.innerHTML = "";
    const copy = document.createElement("div");
    copy.className = "track-copy";
    const nameEl = document.createElement("p");
    nameEl.className = "track-name";
    nameEl.textContent = track.title || `Track ${index + 1}`;
    const artistEl = document.createElement("p");
    artistEl.className = "track-artist";
    artistEl.textContent = track.artists || "Unknown artist";
    copy.append(nameEl, artistEl);
    const side = document.createElement("div");
    side.className = "track-side";
    const duration = formatDuration(track.duration);
    if (duration) {
      const dur = document.createElement("span");
      dur.className = "track-duration";
      dur.textContent = duration;
      side.appendChild(dur);
    }
    row.append(copy, side);
    row.addEventListener("click", () => selectTrimTrack(track));
    trimTrackList.appendChild(row);
  });
}

trimStart.addEventListener("input", () => {
  if (Number(trimStart.value) >= Number(trimEnd.value)) {
    trimStart.value = String(Math.max(0, Number(trimEnd.value) - 1));
  }
  paintTrim();
});

trimEnd.addEventListener("input", () => {
  if (Number(trimEnd.value) <= Number(trimStart.value)) {
    trimEnd.value = String(Number(trimStart.value) + 1);
  }
  paintTrim();
});

function commitTypedRange() {
  const start = parseTime(trimFrom.value);
  const end = parseTime(trimTo.value);
  if (start == null || end == null) {
    paintTrim();
    return;
  }
  setRange(start, end);
}

trimFrom.addEventListener("change", commitTypedRange);
trimTo.addEventListener("change", commitTypedRange);

document.querySelectorAll("[data-preset]").forEach((button) => {
  button.addEventListener("click", () => applyPreset(Number(button.dataset.preset)));
});

trimForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  showError(trimError, "");
  trimSubmit.disabled = true;
  trimSubmit.textContent = "Loading set…";
  try {
    const res = await fetch("/api/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: trimUrl.value.trim() }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(apiError(data, "Could not load that set"));
    if (!data.tracks?.length) throw new Error("No audio found in that link.");
    trimCollection = data;
    trimPanel.hidden = false;
    trimTitle.textContent = data.title || "Set";
    renderTrimTracks(data);
    selectTrimTrack(data.tracks[0]);
  } catch (err) {
    showError(trimError, err.message || "Could not load that set");
  } finally {
    trimSubmit.disabled = false;
    trimSubmit.textContent = "Load set";
  }
});

trimDownload.addEventListener("click", async () => {
  if (!trimTrack) return;
  commitTypedRange();
  const { start, end } = readRange();
  if (!(end > start)) {
    showError(trimError, "End time has to be after the start.");
    return;
  }
  showError(trimError, "");
  trimDownload.disabled = true;
  await queueDownload([trimTrack], {
    title: trimTrack.title || trimCollection?.title || "Set",
    source: trimCollection?.source || "",
    url: trimUrl.value.trim(),
    start,
    end,
    format: trimFormat(),
    errorEl: trimError,
  });
  trimDownload.disabled = false;
});
