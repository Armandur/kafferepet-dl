// kafferepet-dl webUI - SSE + kor-nu + manuell import.
(() => {
  const log = document.getElementById("log");
  if (!log) return;  // ingen logg-yta pa sidan

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

  function setRunning(running) {
    if (runBtn) runBtn.disabled = running;
    importForms.forEach(f => f.querySelectorAll("button").forEach(b => b.disabled = running));
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
})();
