// kafferepet-dl webUI - SSE-anslutning + kor-nu-form.
(() => {
  const log = document.getElementById("log");
  const form = document.getElementById("run-form");
  const btn = document.getElementById("run-btn");
  const status = document.getElementById("status");
  const clearBtn = document.getElementById("clear-btn");
  const autoscroll = document.getElementById("autoscroll");
  if (!log) return;  // ej pa dashboard-sidan

  function append(text, cls) {
    const el = document.createElement("span");
    if (cls) el.className = cls;
    el.textContent = text + "\n";
    log.appendChild(el);
    if (autoscroll && autoscroll.checked) log.scrollTop = log.scrollHeight;
  }

  function setRunning(running) {
    btn.disabled = running;
    status.textContent = running ? "körning pågår..." : "";
    status.className = running ? "status running" : "status";
  }

  const es = new EventSource("/api/run/events");
  es.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.event === "log") append(msg.line);
    else if (msg.event === "start") {
      append(`---- start: run.py ${msg.args.join(" ")} ----`, "start");
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
    // EventSource forsoker reconnecta sjalv; visa bara mjukt status
    status.textContent = "SSE frånkopplad, försöker återansluta...";
    status.className = "status error";
  };

  // initial status
  fetch("/api/run/status").then(r => r.json()).then(s => setRunning(s.running));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    data.dry_run = form.dry_run.checked;
    setRunning(true);
    const r = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      append(`FEL: ${j.error || r.statusText}`, "err");
      setRunning(false);
    }
  });

  clearBtn.addEventListener("click", () => { log.textContent = ""; });
})();
