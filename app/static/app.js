// kafferepet-dl webUI - SSE + kor-nu + manuell import + avsnittslista.
(() => {
  const log = document.getElementById("log");
  if (!log) return;

  const autoscroll = document.getElementById("autoscroll");
  const clearBtn = document.getElementById("clear-btn");
  const runForm = document.getElementById("run-form");
  const runBtn = document.getElementById("run-btn");
  const runStatus = document.getElementById("status");
  const importForms = document.querySelectorAll("form[data-import]");

  function append(text, cls) {
    const el = document.createElement("span");
    if (cls) el.className = cls;
    el.textContent = text + "\n";
    log.appendChild(el);
    if (autoscroll && autoscroll.checked) log.scrollTop = log.scrollHeight;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  let busy = false;
  function setRunning(running) {
    busy = running;
    if (runBtn) runBtn.disabled = running;
    importForms.forEach(f => f.querySelectorAll("button")
                          .forEach(b => b.disabled = running));
    document.querySelectorAll(".track-row button, .ep-action")
            .forEach(b => b.disabled = running);
    if (runStatus) {
      runStatus.textContent = running ? "körning pågår..." : "";
      runStatus.className = running ? "status running" : "status";
    }
  }

  const es = new EventSource("/api/run/events");
  es.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.event === "log") append(msg.line);
    else if (msg.event === "start") {
      append(`---- start: ${msg.args.join(" ")} ----`, "start");
      setRunning(true);
    } else if (msg.event === "end") {
      append(`---- klar, exit ${msg.code} ----`, "end");
      setRunning(false);
      loadEpisodes();   // mutationer kan ha andrat listan
    } else if (msg.event === "error") {
      append(`FEL: ${msg.message}`, "err");
      setRunning(false);
    }
  };
  es.onerror = () => {
    if (runStatus) {
      runStatus.textContent = "SSE frånkopplad, försöker återansluta...";
      runStatus.className = "status error";
    }
  };

  fetch("/api/run/status").then(r => r.json()).then(s => setRunning(s.running));

  async function postJson(url, payload, defaultMsg) {
    setRunning(true);
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      append(`FEL: ${j.error || defaultMsg || r.statusText}`, "err");
      setRunning(false);
    }
  }

  if (runForm) {
    runForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(runForm));
      data.dry_run = runForm.dry_run.checked;
      postJson("/api/run", data, "kunde inte starta");
    });
  }

  const endpoints = {
    youtube: "/api/import/youtube",
    rss: "/api/import/rss",
    local: "/api/import/local",
  };
  importForms.forEach((form) => {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const kind = form.dataset.import;
      const payload = Object.fromEntries(new FormData(form));
      postJson(endpoints[kind], payload, "import misslyckades");
    });
  });

  if (clearBtn) clearBtn.addEventListener("click", () => { log.textContent = ""; });

  // ---- avsnittslista ----
  const epsContainer = document.getElementById("episodes-container");
  const epsMeta = document.getElementById("episodes-meta");
  const refreshBtn = document.getElementById("refresh-episodes");
  const delDialog = document.getElementById("delete-dialog");
  let pendingDelete = null;

  const STATUS_LABEL = {
    imported: "importerad",
    missing: "saknas",
    archived_no_file: "fil saknas",
    disabled: "inaktiv",
  };

  async function loadEpisodes(refresh = false) {
    if (!epsContainer) return;
    if (epsMeta) epsMeta.textContent = "laddar...";
    try {
      const r = await fetch("/api/episodes" + (refresh ? "?refresh=1" : ""));
      const data = await r.json();
      renderEpisodes(data);
    } catch (e) {
      epsContainer.innerHTML = `<p class="err">Kunde inte ladda: ${e}</p>`;
    }
  }

  function renderEpisodes(data) {
    epsContainer.innerHTML = "";
    for (const show of data.shows) {
      const sec = document.createElement("div");
      sec.className = "show-section";
      const h = document.createElement("h3");
      h.textContent = `${show.name}  (${show.episodes.length} avsnitt)`;
      sec.appendChild(h);
      const grid = document.createElement("div");
      grid.className = "episode-grid";
      for (const ep of show.episodes) grid.appendChild(buildCard(show.name, ep));
      sec.appendChild(grid);
      epsContainer.appendChild(sec);
    }
    if (epsMeta && data.fetched_at) {
      const ts = new Date(data.fetched_at * 1000).toLocaleString("sv-SE");
      epsMeta.textContent = `hämtad ${ts}`;
    }
    setRunning(busy);  // se till att nya knappar fattar nuvarande state
  }

  function formatDate(yyyymmdd) {
    if (!yyyymmdd || yyyymmdd.length !== 8) return null;
    return `${yyyymmdd.slice(0,4)}-${yyyymmdd.slice(4,6)}-${yyyymmdd.slice(6,8)}`;
  }
  function formatDuration(seconds) {
    if (!seconds) return null;
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h} t ${m} min`;
    return `${m} min`;
  }

  function buildCard(showName, ep) {
    const card = document.createElement("div");
    card.className = "episode-card" + (ep.in_playlist ? "" : " archive-only");
    card.dataset.id = ep.id;

    const img = document.createElement("img");
    img.src = ep.thumbnail;
    img.alt = "";
    img.loading = "lazy";
    img.onerror = () => { img.style.opacity = ".3"; };
    card.appendChild(img);

    const body = document.createElement("div");
    body.className = "card-body";

    const title = document.createElement("div");
    title.className = "card-title";
    title.textContent = ep.title || `(arkivpost ${ep.id})`;
    body.appendChild(title);

    // Datum + speltid pa en metarad
    const dateStr = formatDate(ep.upload_date);
    const durStr = formatDuration(ep.duration);
    if (dateStr || durStr) {
      const meta = document.createElement("div");
      meta.className = "card-meta";
      meta.textContent = [dateStr, durStr].filter(Boolean).join(" · ");
      body.appendChild(meta);
    }

    if (!ep.in_playlist) {
      const tag = document.createElement("span");
      tag.className = "archive-tag";
      tag.textContent = "Endast i arkiv";
      body.appendChild(tag);
    }
    const predicted = ep.predicted || {};
    body.appendChild(trackBlock(showName, ep, "audio", "Ljud", predicted.audio));
    body.appendChild(trackBlock(showName, ep, "video", "Video", predicted.video));
    card.appendChild(body);
    return card;
  }

  function trackBlock(showName, ep, kind, label, predictedFilename) {
    const wrap = document.createElement("div");
    wrap.className = "track-block";
    wrap.appendChild(trackRow(showName, ep, kind, label));
    if (predictedFilename && ep[kind].status !== "disabled") {
      const fn = document.createElement("div");
      fn.className = "predicted-filename";
      fn.textContent = predictedFilename;
      fn.title = predictedFilename;
      wrap.appendChild(fn);
    }
    return wrap;
  }

  function trackRow(showName, ep, kind, label) {
    const row = document.createElement("div");
    row.className = "track-row";
    const st = ep[kind].status;
    const badge = document.createElement("span");
    badge.className = `badge status-${st}`;
    badge.textContent = `${label}: ${STATUS_LABEL[st] || st}`;
    row.appendChild(badge);
    if (st === "disabled") return row;

    if (st === "missing" || st === "archived_no_file") {
      row.appendChild(actionBtn("Importera", () =>
        doReimport(ep.id, showName, kind)));
    } else if (st === "imported") {
      row.appendChild(actionBtn("Återimport", () =>
        doReimport(ep.id, showName, kind)));
      if (kind === "video") {
        row.appendChild(actionBtn("Radera",
          () => openDeleteDialog(ep, showName, kind), "danger"));
      } else {
        row.appendChild(actionBtn("Glöm arkiv",
          () => doDelete(ep.id, showName, kind, false), "danger",
          "Tar bort arkivposten. Ljudfilen lämnas (kan inte hittas via id)."));
      }
    }
    return row;
  }

  function actionBtn(text, onClick, extraClass, title) {
    const b = document.createElement("button");
    b.className = "ep-action" + (extraClass ? " " + extraClass : "");
    b.textContent = text;
    if (title) b.title = title;
    b.onclick = onClick;
    b.disabled = busy;
    return b;
  }

  async function doReimport(id, show, track) {
    const r = await fetch(`/api/episodes/${id}/reimport`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ show, track }),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      append(`FEL: ${j.error || r.statusText}`, "err");
    }
  }

  function openDeleteDialog(ep, show, track) {
    if (!delDialog) return;
    pendingDelete = { id: ep.id, show, track };
    const target = document.getElementById("delete-target");
    if (target) target.textContent = `${ep.title || ep.id}  (${track})`;
    delDialog.returnValue = "";
    delDialog.showModal();
  }

  if (delDialog) {
    delDialog.addEventListener("close", () => {
      if (!pendingDelete) return;
      const ret = delDialog.returnValue;
      if (ret === "keep" || ret === "remove") {
        doDelete(pendingDelete.id, pendingDelete.show, pendingDelete.track,
                 ret === "keep");
      }
      pendingDelete = null;
    });
    delDialog.querySelector(".dialog-cancel").addEventListener("click", e => {
      e.preventDefault();
      delDialog.close("cancel");
    });
  }

  async function doDelete(id, show, track, keepArchive) {
    const r = await fetch(`/api/episodes/${id}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ show, track, keep_archive: keepArchive }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      append(`FEL: ${j.error || r.statusText}`, "err");
      return;
    }
    append(`Raderat ${id}/${track}: fil=${j.file_deleted} arkiv=${j.archive_deleted}`,
           "start");
    loadEpisodes(true);
  }

  if (refreshBtn) refreshBtn.addEventListener("click", () => loadEpisodes(true));
  if (epsContainer) loadEpisodes();
})();
