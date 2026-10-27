(() => {
  const $ = (s) => document.querySelector(s);
  const panel = $("#wingman"), log = $("#log"), form = $("#chat-form");
  const promptEl = $("#prompt"), sendBtn = $("#send"), modelSel = $("#model");
  let history = [];   // [{role, content}]
  let busy = false;

  const open = () => { panel.classList.add("open"); panel.setAttribute("aria-hidden", "false"); promptEl.focus(); };
  const close = () => { panel.classList.remove("open"); panel.setAttribute("aria-hidden", "true"); };
  document.querySelectorAll("[data-open-wingman]").forEach((el) =>
    el.addEventListener("click", (e) => { e.preventDefault(); open(); }));
  $("#close").onclick = close;
  $("#clear").onclick = () => {
    history = [];
    log.innerHTML = '<div class="msg assistant">New conversation started.</div>';
  };

  // Minimal, safe formatting: escape HTML, then **bold** and `code`.
  const fmt = (t) => t
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");

  function add(role, text) {
    const el = document.createElement("div");
    el.className = "msg " + role;
    el.innerHTML = fmt(text);
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  async function loadConfig() {
    try {
      const [cfg, m] = await Promise.all([
        fetch("/api/config").then((r) => r.json()),
        fetch("/api/models").then((r) => r.json()),
      ]);
      $("#version").textContent = cfg.version;
      if (cfg.mode === "mock" || cfg.mode === "none") {
        const b = $("#mode-banner");
        b.hidden = false;
        b.textContent = cfg.mode === "mock"
          ? "Wingman is in mock mode: replies are canned. Set DATABRICKS_HOST and credentials to use real models."
          : "Wingman has no Databricks credentials configured.";
      }
      let saved = null;
      try { saved = localStorage.getItem("wingman.model"); } catch {}
      modelSel.innerHTML = "";
      for (const { id, ready } of m.models) {
        const o = document.createElement("option");
        o.value = id;
        o.textContent = id + (ready === false ? " (not ready)" : "");
        o.disabled = ready === false;
        modelSel.appendChild(o);
      }
      const ids = m.models.map((x) => x.id);
      modelSel.value = ids.includes(saved) ? saved : cfg.defaultModel;
    } catch (e) {
      add("error", "Couldn't load Wingman settings: " + e.message);
    }
  }
  modelSel.onchange = () => { try { localStorage.setItem("wingman.model", modelSel.value); } catch {} };

  async function send(text) {
    text = text.trim();
    if (!text || busy) return;
    busy = true; sendBtn.disabled = true;
    open();
    add("user", text);
    history.push({ role: "user", content: text });
    const out = add("assistant", "");
    out.classList.add("typing");
    let reply = "";
    const model = modelSel.value;
    const started = performance.now();

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model, messages: history.slice(-20) }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || res.statusText);
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, i); buf = buf.slice(i + 2);
          const ev = /event: (\w+)/.exec(block)?.[1];
          const data = JSON.parse(/data: (.*)/.exec(block)?.[1] || "{}");
          if (ev === "delta") { reply += data.text; out.innerHTML = fmt(reply); log.scrollTop = log.scrollHeight; }
          if (ev === "error") throw new Error(data.message);
        }
      }
      out.classList.remove("typing");
      const secs = ((performance.now() - started) / 1000).toFixed(1);
      out.insertAdjacentHTML("beforeend", `<span class="meta">${model} · ${secs}s</span>`);
      history.push({ role: "assistant", content: reply });
    } catch (e) {
      out.remove();
      history.pop();
      add("error", "Wingman couldn't answer: " + e.message);
    } finally {
      busy = false; sendBtn.disabled = false; promptEl.focus();
    }
  }

  form.onsubmit = (e) => { e.preventDefault(); const t = promptEl.value; promptEl.value = ""; send(t); };
  promptEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
  $("#search-form").onsubmit = (e) => { e.preventDefault(); const s = $("#search"); send(s.value); s.value = ""; };
  document.querySelectorAll("[data-prompt]").forEach((b) => b.onclick = () => send(b.dataset.prompt));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });

  loadConfig();
})();
