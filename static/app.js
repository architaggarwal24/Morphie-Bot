/*
 * Morphie app shell.
 *
 * One conversation lives in `transcript` (a flat array) regardless of whether
 * the Documents side panel is open.
 *
 * Chat turns stream over POST /chat/stream (see app.py for the exact SSE
 * event vocabulary: step / token / message / error). Model/user text is
 * only ever set with textContent - no innerHTML assignment of anything
 * that came from the network exists in this file.
 */
(function () {
  "use strict";

  // ---- tiny DOM helper ----
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function safeStorage() {
    try {
      var key = "__mp_probe__";
      window.localStorage.setItem(key, "1");
      window.localStorage.removeItem(key);
      return window.localStorage;
    } catch (err) {
      return null; // private browsing / storage disabled: theme choice just won't persist
    }
  }
  var storage = safeStorage();

  // ---------------------------------------------------------------- //
  // Theme (dark default, light optional, persisted)
  // ---------------------------------------------------------------- //

  var THEME_KEY = "morphie-theme";

  function storedTheme() {
    return storage ? storage.getItem(THEME_KEY) : null;
  }

  function effectiveTheme() {
    // Always explicit after boot ("dark" by default); this fallback only
    // matters if applyTheme() is ever called with theme=null again.
    return document.documentElement.getAttribute("data-theme") || "dark";
  }

  function applyTheme(theme) {
    if (theme) document.documentElement.setAttribute("data-theme", theme);
    else document.documentElement.removeAttribute("data-theme");
    var toggle = document.getElementById("themeToggleBtn");
    if (toggle) toggle.setAttribute("data-theme-now", effectiveTheme());
  }

  function toggleTheme() {
    var next = effectiveTheme() === "dark" ? "light" : "dark";
    if (storage) storage.setItem(THEME_KEY, next);
    applyTheme(next);
  }

  // Dark unless the person has explicitly chosen light (persisted). No
  // prefers-color-scheme fallback - the default was asked for explicitly.
  applyTheme(storedTheme() || "dark");

  // ---------------------------------------------------------------- //
  // Shared helpers: API calls, toasts, escaping
  // ---------------------------------------------------------------- //

  var JSON_HEADERS = { "Content-Type": "application/json" };

  // The only place non-streaming calls go through. Never throws: any failure
  // (network down, non-JSON error page, etc.) becomes {ok:false, message}.
  async function callApi(path, options) {
    var res;
    try {
      res = await fetch(path, options);
    } catch (err) {
      return { ok: false, status: 0, data: null, message: "Could not reach Morphie. Check your connection and try again." };
    }
    var data = null;
    try { data = await res.json(); } catch (err) { /* not JSON */ }
    var message = res.ok ? null : ((data && (data.error || data.content)) || "Something went wrong. Please try again.");
    return { ok: res.ok, status: res.status, data: data, message: message };
  }

  function showToast(message) {
    var toast = el("div", "toast", message);
    toast.setAttribute("role", "status");
    document.body.appendChild(toast);
    setTimeout(function () { toast.remove(); }, 4500);
  }

  // ---------------------------------------------------------------- //
  // Sidebar (mobile drawer) + nav + panels
  // ---------------------------------------------------------------- //

  var sidebar = document.getElementById("sidebar");
  var sidebarScrim = document.getElementById("sidebarScrim");
  var workspace = document.getElementById("workspace");

  function openSidebar() { sidebar.classList.add("is-open"); sidebarScrim.classList.add("is-open"); }
  function closeSidebar() { sidebar.classList.remove("is-open"); sidebarScrim.classList.remove("is-open"); }

  var sidebarToggleBtn = document.getElementById("sidebarToggleBtn");
  if (sidebarToggleBtn) {
    sidebarToggleBtn.addEventListener("click", function () {
      if (sidebar.classList.contains("is-open")) closeSidebar(); else openSidebar();
    });
  }
  if (sidebarScrim) sidebarScrim.addEventListener("click", closeSidebar);

  var PANELS = {
    documents: { panel: "docsPanel", nav: "docsBtn", load: loadDocuments },
  };
  var chatBtn = document.getElementById("chatBtn");
  var activePanel = null;

  function setActiveNav(name) {
    chatBtn.setAttribute("aria-pressed", String(!name));
    Object.keys(PANELS).forEach(function (key) {
      document.getElementById(PANELS[key].nav).setAttribute("aria-pressed", String(key === name));
    });
  }

  function openPanel(name) {
    var entry = PANELS[name];
    if (!entry) return;
    activePanel = name;
    Object.keys(PANELS).forEach(function (key) {
      document.getElementById(PANELS[key].panel).classList.toggle("is-active", key === name);
    });
    setActiveNav(name);
    workspace.classList.add("panel-open");
    closeSidebar();
    entry.load();
  }

  function closePanel() {
    activePanel = null;
    workspace.classList.remove("panel-open");
    setActiveNav(null);
  }

  function handleNavClick(name) {
    if (activePanel === name) closePanel();
    else openPanel(name);
  }

  chatBtn.addEventListener("click", closePanel);
  Object.keys(PANELS).forEach(function (key) {
    document.getElementById(PANELS[key].nav).addEventListener("click", function () { handleNavClick(key); });
  });
  document.querySelectorAll(".mp-panel-close").forEach(function (button) {
    button.addEventListener("click", closePanel);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && activePanel) closePanel();
  });

  var themeToggleBtn = document.getElementById("themeToggleBtn");
  if (themeToggleBtn) themeToggleBtn.addEventListener("click", toggleTheme);

  // The provider badge is read-only: the provider comes from .env (see GET /status).
  async function loadStatus() {
    var badge = document.getElementById("providerBadge");
    var name = document.getElementById("providerBadgeName");
    var result = await callApi("/status");
    if (!result.ok) { name.textContent = "Offline"; badge.classList.add("is-unconfigured"); return; }
    var info = result.data;
    name.textContent = info.provider + " · " + info.model;
    badge.classList.toggle("is-unconfigured", !info.configured);
    badge.title = info.configured ? "Set LLM_PROVIDER in .env to change the model provider"
      : info.provider + " is not configured yet - add its API key to your .env file and restart.";
    if (!info.configured) showToast(info.provider + " isn't configured yet. Add its API key to .env and restart.");
  }

  // ---------------------------------------------------------------- //
  // Chat: one conversation, streamed
  // ---------------------------------------------------------------- //

  var chat = document.getElementById("chat");
  var input = document.getElementById("input");
  var sendBtn = document.getElementById("sendBtn");
  var transcript = []; // {content, sender, variant} - rendered top to bottom

  var SUGGESTIONS = [
    "What's 20% of 500?",
    "What does my resume say about Python?",
    "What time is it in Tokyo?",
    "Search the web for today's top tech news.",
  ];

  function buildEmptyChat() {
    var wrap = el("div", "mp-empty-chat");
    wrap.appendChild(el("div", "mp-empty-chat__mark", "✨"));
    wrap.appendChild(el("h2", "", "Ask Morphie anything"));
    wrap.appendChild(el("p", "", "It picks the right tool itself: a calculator, the clock, web search, or your uploaded documents - no need to choose."));
    var chips = el("div", "mp-suggestions");
    SUGGESTIONS.forEach(function (text) {
      var chip = el("button", "mp-suggestion", text);
      chip.type = "button";
      chip.addEventListener("click", function () { input.value = text; input.focus(); autosizeInput(); });
      chips.appendChild(chip);
    });
    wrap.appendChild(chips);
    return wrap;
  }

  function renderMessages() {
    chat.replaceChildren();
    if (transcript.length === 0) {
      chat.appendChild(buildEmptyChat());
      return;
    }
    var thread = el("div", "mp-thread");
    transcript.forEach(function (m) { thread.appendChild(buildStaticRow(m)); });
    chat.appendChild(thread);
    chat.scrollTop = chat.scrollHeight;
  }

  function buildStaticRow(m) {
    if (m.variant === "meta") {
      var meta = el("div", "mp-meta-row");
      meta.appendChild(el("span", "mp-chip", m.content));
      return meta;
    }
    var row = el("div", "mp-row" + (m.sender === "user" ? " mp-row--user" : ""));
    row.appendChild(el("div", "mp-avatar mp-avatar--" + m.sender, m.sender === "user" ? "You" : "M"));
    var col = el("div", "mp-bubble-col");
    col.appendChild(el("div", "mp-bubble mp-bubble--" + (m.error ? "error" : m.sender), m.content));
    row.appendChild(col);
    return row;
  }

  function addMessage(content, sender, variant) {
    transcript.push({ content: content, sender: sender || "bot", variant: variant || null });
    renderMessages();
  }

  function autosizeInput() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 200) + "px";
  }
  input.addEventListener("input", autosizeInput);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // ---- live step trail + streamed bubble ----

  var TOOL_ACTIVE = {
    calculator: "🧮 Using the calculator", get_current_time: "🕒 Checking the time",
    web_search: "🔎 Searching the web", search_documents: "📄 Searching your documents",
  };
  var TOOL_DONE = {
    calculator: "🧮 Used the calculator", get_current_time: "🕒 Checked the time",
    web_search: "🔎 Searched the web", search_documents: "📄 Searched your documents",
  };

  // One in-progress assistant turn: the row/bubble/step DOM plus the methods
  // that respond to each SSE event. Returned by beginAssistantTurn().
  function beginAssistantTurn() {
    if (transcript.length === 0) chat.replaceChildren(el("div", "mp-thread"));
    var thread = chat.querySelector(".mp-thread") || chat.appendChild(el("div", "mp-thread"));

    var row = el("div", "mp-row");
    row.appendChild(el("div", "mp-avatar mp-avatar--assistant", "M"));
    var col = el("div", "mp-bubble-col");
    var steps = el("div", "mp-steps");
    var bubble = el("div", "mp-bubble mp-bubble--assistant");
    var cursor = el("span", "mp-cursor");
    bubble.appendChild(cursor);
    var extras = el("div", "mp-bubble-col"); // sources render here, appended after the bubble
    col.appendChild(steps);
    col.appendChild(bubble);
    row.appendChild(col);
    thread.appendChild(row);
    chat.scrollTop = chat.scrollHeight;

    var thinkingLine = null;
    var activeStepPill = null;
    var text = "";

    function setThinking(label) {
      clearThinking();
      thinkingLine = el("div", "mp-step", label);
      thinkingLine.setAttribute("data-state", "active");
      var spinner = el("span", "mp-step__spinner");
      thinkingLine.prepend(spinner);
      steps.appendChild(thinkingLine);
    }
    function clearThinking() {
      if (thinkingLine) { thinkingLine.remove(); thinkingLine = null; }
    }

    function addPermanentStep(label) {
      clearThinking();
      var pill = el("span", "mp-step", label);
      pill.setAttribute("data-state", "active");
      pill.prepend(el("span", "mp-step__spinner"));
      pill.appendChild(el("span", "mp-step__check", "✓"));
      steps.appendChild(pill);
      return pill;
    }

    function step(data) {
      if (data.type === "thinking") { setThinking("💭 Thinking"); return; }
      if (data.type === "tool_call") {
        activeStepPill = addPermanentStep(TOOL_ACTIVE[data.tool] || "🔧 Using " + data.tool);
        activeStepPill.dataset.tool = data.tool;
        return;
      }
      if (data.type === "tool_result" && activeStepPill) {
        activeStepPill.setAttribute("data-state", data.success ? "done" : "error");
        var label = data.success ? (TOOL_DONE[data.tool] || "🔧 Used " + data.tool) : "⚠️ " + data.tool + " failed";
        activeStepPill.childNodes[1].textContent = label; // index 1: the text node after the spinner span
        activeStepPill = null;
      }
    }

    function appendToken(piece) {
      text += piece;
      bubble.textContent = text;
      bubble.appendChild(cursor);
      chat.scrollTop = chat.scrollHeight;
    }

    function finish(data) {
      clearThinking();
      cursor.remove();

      transcript.push({ content: data.content, sender: "bot" });
      if (Array.isArray(data.sources) && data.sources.length) {
        col.appendChild(el("div", "mp-hint", "Sources"));
        var sourceRow = el("div", "mp-meta-row");
        data.sources.forEach(function (s) {
          var label = s.page != null ? s.document + " · p." + s.page : s.document;
          sourceRow.appendChild(el("span", "mp-chip mp-chip--source", "📄 " + label));
        });
        col.appendChild(sourceRow);
      }
    }

    function fail(message) {
      clearThinking();
      cursor.remove();
      if (!text) bubble.remove();
      var errorBubble = el("div", "mp-bubble mp-bubble--error", message);
      col.appendChild(errorBubble);
      transcript.push({ content: message, sender: "bot", error: true });
    }

    function stopped() {
      clearThinking();
      cursor.remove();
      transcript.push({ content: text, sender: "bot" });
      col.appendChild(el("div", "mp-meta-row")).appendChild(el("span", "mp-chip", "Stopped"));
    }

    return { step: step, appendToken: appendToken, finish: finish, fail: fail, stopped: stopped };
  }

  // ---- SSE parsing + the request itself ----

  function parseFrame(frame) {
    var eventName = "message", data = null;
    frame.split("\n").forEach(function (line) {
      if (line.indexOf("event: ") === 0) eventName = line.slice(7);
      else if (line.indexOf("data: ") === 0) {
        try { data = JSON.parse(line.slice(6)); } catch (err) { data = null; }
      }
    });
    return { event: eventName, data: data };
  }

  var inFlight = null; // the AbortController for the request currently streaming, or null

  function setComposerBusy(busy) {
    sendBtn.classList.toggle("mp-composer-btn--stop", busy);
    sendBtn.setAttribute("aria-label", busy ? "Stop" : "Send");
    sendBtn.innerHTML = "";
    sendBtn.appendChild(busy ? stopIcon() : sendIcon());
  }

  async function sendMessage() {
    if (inFlight) { inFlight.abort(); return; }
    var text = input.value.trim();
    if (!text) return;

    addMessage(text, "user");
    input.value = "";
    autosizeInput();

    var controller = new AbortController();
    inFlight = controller;
    setComposerBusy(true);
    var turn = beginAssistantTurn();

    try {
      var res = await fetch("/chat/stream", {
        method: "POST", headers: JSON_HEADERS, signal: controller.signal,
        body: JSON.stringify({ message: text, document_ids: getSelectedDocumentIds() }),
      });
      if (!res.ok || !res.body) {
        var data = null;
        try { data = await res.json(); } catch (err) { /* not JSON */ }
        turn.fail((data && (data.content || data.error)) || "Morphie couldn't process that. Please try again.");
      } else {
        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";
        while (true) {
          var chunk = await reader.read();
          if (chunk.done) break;
          buffer += decoder.decode(chunk.value, { stream: true });
          var sep;
          while ((sep = buffer.indexOf("\n\n")) !== -1) {
            var frame = buffer.slice(0, sep);
            buffer = buffer.slice(sep + 2);
            if (!frame.trim()) continue;
            var parsed = parseFrame(frame);
            if (parsed.event === "step") turn.step(parsed.data);
            else if (parsed.event === "token") turn.appendToken(parsed.data.text);
            else if (parsed.event === "message") turn.finish(parsed.data);
            else if (parsed.event === "error") turn.fail("⚠️ " + parsed.data.message);
          }
        }
      }
    } catch (err) {
      if (err && err.name === "AbortError") turn.stopped();
      else turn.fail("Could not reach Morphie. Check your connection and try again.");
    } finally {
      inFlight = null;
      setComposerBusy(false);
      input.focus();
    }
  }

  sendBtn.addEventListener("click", sendMessage);

  document.getElementById("newChatBtn").addEventListener("click", async function () {
    if (inFlight) inFlight.abort();
    var result = await callApi("/chat/reset", { method: "POST", headers: JSON_HEADERS, body: "{}" });
    if (!result.ok) { showToast("Couldn't start a new chat. " + result.message); return; }
    transcript = [];
    closePanel();
    renderMessages();
    input.focus();
  });

  // ---- small inline icons (send / stop / sidebar / new chat) ----
  function svg(paths) {
    var wrap = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    wrap.setAttribute("viewBox", "0 0 24 24");
    wrap.setAttribute("width", "16"); wrap.setAttribute("height", "16");
    wrap.setAttribute("fill", "none"); wrap.setAttribute("stroke", "currentColor");
    wrap.setAttribute("stroke-width", "2"); wrap.setAttribute("stroke-linecap", "round"); wrap.setAttribute("stroke-linejoin", "round");
    paths.forEach(function (d) {
      var p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", d);
      wrap.appendChild(p);
    });
    return wrap;
  }
  function sendIcon() { return svg(["M5 12h14", "M13 5l7 7-7 7"]); }
  function stopIcon() { var r = document.createElementNS("http://www.w3.org/2000/svg", "rect"); r.setAttribute("x", "7"); r.setAttribute("y", "7"); r.setAttribute("width", "10"); r.setAttribute("height", "10"); r.setAttribute("rx", "2"); r.setAttribute("fill", "currentColor"); var w = svg([]); w.appendChild(r); return w; }
  setComposerBusy(false);

  // ---------------------------------------------------------------- //
  // Documents panel
  // ---------------------------------------------------------------- //

  var DOC_ICONS = { pdf: "📄", txt: "📄", docx: "📄", csv: "📊", json: "🧾" };
  var allDocuments = [];
  var selectedDocumentIds = new Set();
  var allDocsToggle = document.getElementById("allDocsToggle");

  function getSelectedDocumentIds() {
    if (!allDocsToggle || allDocsToggle.checked) return null; // null = ask about every document
    return Array.from(selectedDocumentIds);
  }

  async function loadDocuments() {
    var list = document.getElementById("docsList");
    list.replaceChildren(el("div", "mp-list-empty", "Loading…"));
    var result = await callApi("/documents");
    if (!result.ok) { list.replaceChildren(el("div", "mp-list-empty", "Could not load documents.")); return; }

    allDocuments = result.data.documents || [];
    var currentIds = new Set(allDocuments.map(function (d) { return d.id; }));
    selectedDocumentIds = new Set(Array.from(selectedDocumentIds).filter(function (id) { return currentIds.has(id); }));
    allDocuments.forEach(function (d) { selectedDocumentIds.add(d.id); });
    renderDocsList();
  }

  function renderDocsList() {
    var list = document.getElementById("docsList");
    if (allDocuments.length === 0) { list.replaceChildren(el("div", "mp-list-empty", "No documents uploaded yet.")); return; }

    var askAll = allDocsToggle.checked;
    list.replaceChildren.apply(list, allDocuments.map(function (d) {
      var row = el("div", "mp-list-item");
      var checkbox = document.createElement("input");
      checkbox.type = "checkbox"; checkbox.className = "doc-checkbox";
      checkbox.checked = askAll || selectedDocumentIds.has(d.id);
      checkbox.disabled = askAll;
      checkbox.addEventListener("change", function () {
        if (checkbox.checked) selectedDocumentIds.add(d.id); else selectedDocumentIds.delete(d.id);
      });
      var body = el("div", "mp-list-item__body");
      body.appendChild(el("div", "mp-list-item__title", (DOC_ICONS[d.type] || "📄") + " " + d.name));
      var del = el("button", "mp-btn mp-btn--ghost mp-btn--sm", "🗑");
      del.type = "button"; del.title = "Delete";
      del.addEventListener("click", function () { deleteDocument(d.id); });
      row.appendChild(checkbox); row.appendChild(body); row.appendChild(del);
      return row;
    }));
  }

  if (allDocsToggle) allDocsToggle.addEventListener("change", renderDocsList);

  var fileInput = document.getElementById("fileInput");
  document.getElementById("uploadBtn").addEventListener("click", function () { fileInput.click(); });
  document.getElementById("dropzone").addEventListener("click", function () { fileInput.click(); });
  ["dragover", "dragleave", "drop"].forEach(function (type) {
    document.getElementById("dropzone").addEventListener(type, function (e) {
      e.preventDefault();
      document.getElementById("dropzone").classList.toggle("is-dragover", type === "dragover");
      if (type === "drop" && e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
    });
  });
  fileInput.addEventListener("change", function () {
    if (fileInput.files[0]) uploadFile(fileInput.files[0]);
  });

  async function uploadFile(file) {
    var status = document.getElementById("uploadStatus");
    status.textContent = "Uploading " + file.name + "…";
    var formData = new FormData();
    formData.append("file", file);
    var result = await callApi("/documents/upload", { method: "POST", body: formData });
    fileInput.value = "";
    if (!result.ok) { status.textContent = "⚠️ " + result.message; return; }
    var name = result.data.document.name;
    status.textContent = result.data.duplicate ? "ℹ️ " + name + " was already uploaded." : "✅ " + name + " uploaded.";
    await loadDocuments();
  }

  async function deleteDocument(id) {
    var result = await callApi("/documents/" + encodeURIComponent(id), { method: "DELETE" });
    if (!result.ok && result.status !== 404) showToast("Couldn't delete that document. " + result.message);
    loadDocuments();
  }

  // ---------------------------------------------------------------- //
  // Boot
  // ---------------------------------------------------------------- //

  renderMessages();
  loadStatus(); // fills the sidebar's provider badge and warns early if no API key is set
})();
