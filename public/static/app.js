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

  // Runs a same-page DOM change inside a view transition (a short cross-fade; rows that kept their
  // view-transition-name slide to their new place). Unsupported browsers and reduced-motion just apply the change.
  function withTransition(update) {
    var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!document.startViewTransition || reduced) { update(); return; }
    document.startViewTransition(update);
  }

  function toggleTheme() {
    var next = effectiveTheme() === "dark" ? "light" : "dark";
    if (storage) storage.setItem(THEME_KEY, next);
    withTransition(function () { applyTheme(next); });
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

  var UNDO_MS = 6000; // how long an Undo toast (and the delayed request behind it) lasts
  var toastStack = null;

  // showToast(text) or showToast(text, { action: { label, onClick }, duration }). Returns { dismiss }.
  // role="status": screen readers announce it politely, without stealing focus.
  function showToast(message, options) {
    options = options || {};
    if (!toastStack) { toastStack = el("div", "toast-stack"); document.body.appendChild(toastStack); }
    var toast = el("div", "toast");
    toast.setAttribute("role", "status");
    toastStack.appendChild(toast); // in the page first, content second: live regions announce what is added to them
    var timer = null;

    function dismiss() {
      clearTimeout(timer);
      toast.classList.remove("is-visible");
      setTimeout(function () { toast.remove(); }, 220);
    }

    setTimeout(function () {
      toast.appendChild(el("span", "toast__text", message));
      if (options.action) {
        var button = el("button", "toast__action", options.action.label);
        button.type = "button";
        button.addEventListener("click", function () { dismiss(); options.action.onClick(); });
        toast.appendChild(button);
      }
      toast.classList.add("is-visible");
    }, 30);
    timer = setTimeout(dismiss, options.duration || 4500);
    return { dismiss: dismiss };
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

  // ---------------------------------------------------------------- //
  // Bring your own key: provider, model and API key live in THIS browser
  // ---------------------------------------------------------------- //
  //
  // The choice is saved in localStorage ("Remember on this device") or sessionStorage (until the tab closes)
  // and sent as X-LLM-* headers with each request. The server uses it for that request only; it never stores
  // or logs it. The key is only ever read into a password input and these headers, never rendered as HTML.

  var LLM_KEY = "morphie-llm";

  function sessionStore() {
    try { return window.sessionStorage; } catch (err) { return null; }
  }

  function loadLlm() {
    var stores = [storage, sessionStore()];
    for (var i = 0; i < stores.length; i++) {
      try {
        var raw = stores[i] && stores[i].getItem(LLM_KEY);
        if (raw) {
          var cfg = JSON.parse(raw);
          if (cfg && typeof cfg.provider === "string") return cfg;
        }
      } catch (err) { /* unreadable: treat as not set */ }
    }
    return null;
  }

  function saveLlm(cfg, remember) {
    clearLlm();
    var target = (remember && storage) ? storage : sessionStore();
    if (target) target.setItem(LLM_KEY, JSON.stringify(cfg));
  }

  function clearLlm() {
    var stores = [storage, sessionStore()];
    for (var i = 0; i < stores.length; i++) { try { if (stores[i]) stores[i].removeItem(LLM_KEY); } catch (err) { /* ignore */ } }
  }

  // Headers that carry the saved choice. Empty when nothing is saved (the server then uses its own provider).
  function llmHeaders() {
    var cfg = loadLlm();
    var headers = {};
    if (!cfg || !cfg.provider) return headers;
    headers["X-LLM-Provider"] = cfg.provider;
    if (cfg.model) headers["X-LLM-Model"] = cfg.model;
    if (cfg.key) headers["X-LLM-Key"] = cfg.key;
    return headers;
  }

  function withLlmHeaders(base) {
    var merged = {};
    var extra = llmHeaders();
    Object.keys(base || {}).forEach(function (k) { merged[k] = base[k]; });
    Object.keys(extra).forEach(function (k) { merged[k] = extra[k]; });
    return merged;
  }

  var providerList = [];
  var providerBadge = document.getElementById("providerBadge");
  var settingsModal = document.getElementById("settingsModal");
  var llmProvider = document.getElementById("llmProvider");
  var llmModel = document.getElementById("llmModel");
  var llmModelList = document.getElementById("llmModelList");
  var llmKey = document.getElementById("llmKey");
  var llmKeyField = document.getElementById("llmKeyField");
  var llmKeyHint = document.getElementById("llmKeyHint");
  var llmRemember = document.getElementById("llmRemember");
  var settingsError = document.getElementById("settingsError");

  function providerInfo(id) {
    for (var i = 0; i < providerList.length; i++) if (providerList[i].id === id) return providerList[i];
    return null;
  }

  // Fills the model suggestions and shows/hides the key field for the selected provider.
  function syncProviderFields() {
    var info = providerInfo(llmProvider.value);
    llmModelList.innerHTML = "";
    if (!info) return;
    (info.models || []).forEach(function (m) {
      var option = document.createElement("option");
      option.value = m;
      llmModelList.appendChild(option);
    });
    llmModel.placeholder = info.default_model;
    llmKeyField.hidden = !info.requires_key;
    var saved = loadLlm();
    var hasSavedKey = !!(saved && saved.provider === info.id && saved.key);
    llmKeyHint.textContent = hasSavedKey
      ? "A key is saved. Leave this empty to keep it, or paste a new one."
      : "Create one in your " + info.name + " dashboard. It is only sent with your messages.";
  }

  async function loadProviders() {
    if (providerList.length) return;
    var result = await callApi("/providers");
    providerList = (result.ok && result.data && result.data.providers) || [];
    llmProvider.innerHTML = "";
    providerList.forEach(function (p) {
      var option = document.createElement("option");
      option.value = p.id;
      option.textContent = p.name;
      llmProvider.appendChild(option);
    });
  }

  async function openSettings() {
    await loadProviders();
    var saved = loadLlm();
    if (saved && providerInfo(saved.provider)) llmProvider.value = saved.provider;
    llmModel.value = (saved && saved.model) || "";
    llmKey.value = ""; // the saved key is never put back into the page
    llmRemember.checked = saved ? !!(storage && storage.getItem(LLM_KEY)) : true;
    settingsError.textContent = "";
    syncProviderFields();
    settingsModal.hidden = false;
    (llmKeyField.hidden ? llmModel : llmKey).focus();
  }

  function closeSettings() { settingsModal.hidden = true; }

  llmProvider.addEventListener("change", syncProviderFields);
  document.getElementById("settingsCloseBtn").addEventListener("click", closeSettings);
  settingsModal.addEventListener("click", function (e) { if (e.target === settingsModal) closeSettings(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !settingsModal.hidden) closeSettings(); });
  if (providerBadge) providerBadge.addEventListener("click", openSettings);

  document.getElementById("settingsForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var info = providerInfo(llmProvider.value);
    if (!info) { settingsError.textContent = "Choose a provider."; return; }
    var model = llmModel.value.trim();
    if (model && !/^[A-Za-z0-9][A-Za-z0-9._:\/-]{0,79}$/.test(model)) {
      settingsError.textContent = "That model name has characters a model id never contains."; return;
    }
    var saved = loadLlm();
    var key = llmKey.value.trim();
    if (!key && saved && saved.provider === info.id && saved.key) key = saved.key; // keep the saved key
    if (info.requires_key) {
      if (!key) { settingsError.textContent = "Paste your " + info.name + " API key."; return; }
      if (!/^[\x21-\x7e]{8,400}$/.test(key)) { settingsError.textContent = "That doesn't look like an API key (no spaces, 8+ characters)."; return; }
    }
    saveLlm({ provider: info.id, model: model, key: info.requires_key ? key : "" }, llmRemember.checked);
    llmKey.value = "";
    closeSettings();
    showToast("Saved. Morphie will use " + info.name + (model ? " · " + model : "") + ".");
    loadStatus();
  });

  document.getElementById("settingsClearBtn").addEventListener("click", function () {
    var previous = loadLlm();                                       // kept in memory only for the length of the Undo toast
    var wasRemembered = !!(storage && storage.getItem(LLM_KEY));
    clearLlm();
    llmKey.value = "";
    closeSettings();
    showToast("Your key was removed from this browser.", previous ? {
      duration: UNDO_MS,
      action: { label: "Undo", onClick: function () { saveLlm(previous, wasRemembered); showToast("Your key is back."); loadStatus(); } },
    } : undefined);
    loadStatus();
  });

  // The badge shows what will answer (GET /status, with your saved choice) and opens Settings when clicked.
  async function loadStatus(autoOpen) {
    lastStatusFetch = Date.now();
    var name = document.getElementById("providerBadgeName");
    var result = await callApi("/status", { headers: withLlmHeaders({}) });
    if (!result.ok) {
      name.textContent = "Offline";
      providerBadge.classList.add("is-unconfigured");
      if (result.status === 400) { // e.g. a saved choice the server no longer accepts
        clearLlm();
        showToast(result.message);
      }
      return;
    }
    var info = result.data;
    providerBadge.classList.toggle("is-unconfigured", !info.configured);
    if (info.configured) {
      name.textContent = info.provider + " · " + info.model;
      setTip(providerBadge, "Change your model or API key");
    } else {
      name.textContent = "Add your API key";
      setTip(providerBadge, info.provider + " needs an API key. Click to add yours.");
      if (autoOpen) openSettings();
    }
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
        method: "POST", headers: withLlmHeaders(JSON_HEADERS), signal: controller.signal,
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
    closePanel();
    withTransition(function () { transcript = []; renderMessages(); });
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
  var SKELETON_DELAY_MS = 300; // loads faster than this never flash a placeholder
  var SKELETON_ROWS = 3;
  var docsLoaded = false;      // true once a list (even an empty one) has been shown
  var docsRequestId = 0;       // newest request wins; older responses are dropped
  var lastDocsFetch = 0;
  var lastStatusFetch = 0;
  var allDocuments = [];
  var selectedDocumentIds = new Set();
  var allDocsToggle = document.getElementById("allDocsToggle");

  var pendingDeleteIds = new Set(); // documents already gone from the screen whose DELETE has not finished

  function getSelectedDocumentIds() {
    if (pendingDeleteIds.size) {
      // A document is on its way out: name the ones that stay instead of "all", so the model can't cite it.
      var keep = (allDocsToggle && !allDocsToggle.checked) ? Array.from(selectedDocumentIds) : allDocuments.map(function (d) { return d.id; });
      return keep.filter(function (id) { return !pendingDeleteIds.has(id); });
    }
    if (!allDocsToggle || allDocsToggle.checked) return null; // null = ask about every document
    return Array.from(selectedDocumentIds);
  }

  // Stale-while-revalidate: whatever list we already have is painted first; the request then refreshes it in the
  // background (and again from revalidate() when the window regains focus or the network returns).
  async function loadDocuments() {
    var list = document.getElementById("docsList");
    var requestId = ++docsRequestId;
    lastDocsFetch = Date.now();
    if (docsLoaded) renderDocsList();
    list.setAttribute("aria-busy", "true");
    // Gray rows in the shape of the real ones, but only if the answer is slow (and there is nothing to show yet).
    var skeletonTimer = docsLoaded ? null : setTimeout(function () {
      var rows = [];
      for (var i = 0; i < SKELETON_ROWS; i++) rows.push(buildDocRow(null));
      list.replaceChildren.apply(list, rows);
    }, SKELETON_DELAY_MS);
    var result = await callApi("/documents");
    clearTimeout(skeletonTimer);
    if (requestId !== docsRequestId) return; // a newer request owns the screen now
    list.removeAttribute("aria-busy");
    if (!result.ok) {
      if (!docsLoaded) list.replaceChildren(el("div", "mp-list-empty", "Could not load documents."));
      return; // a failed background refresh keeps showing the cached list
    }

    var known = new Set(allDocuments.map(function (d) { return d.id; }));
    docsLoaded = true;
    allDocuments = (result.data.documents || []).filter(function (d) { return !pendingDeleteIds.has(d.id); });
    var currentIds = new Set(allDocuments.map(function (d) { return d.id; }));
    selectedDocumentIds = new Set(Array.from(selectedDocumentIds).filter(function (id) { return currentIds.has(id); }));
    // Only documents we hadn't seen yet start ticked, so a refresh never undoes someone's own choices.
    allDocuments.forEach(function (d) { if (!known.has(d.id)) selectedDocumentIds.add(d.id); });
    renderDocsList();
  }

  // A view-transition-name must be a valid, unique identifier; document ids are server-made strings.
  function docTransitionName(id) { return "doc-" + String(id).replace(/[^A-Za-z0-9_-]/g, "_"); }

  function renderDocsListAnimated() { withTransition(renderDocsList); }

  function renderDocsList() {
    var list = document.getElementById("docsList");
    if (allDocuments.length === 0) { list.replaceChildren(el("div", "mp-list-empty", "No documents uploaded yet.")); return; }

    var askAll = allDocsToggle.checked;
    list.replaceChildren.apply(list, allDocuments.map(function (d) { return buildDocRow(d, askAll); }));
  }

  // One row builder for both states. `d === null` builds the loading skeleton: the very same elements and
  // classes, filled with placeholder text and painted as gray blocks, so the real rows land without a jump.
  function buildDocRow(d, askAll) {
    var skeleton = d === null;
    var row = el("div", "mp-list-item" + (skeleton ? " is-skeleton" : ""));
    var checkbox = document.createElement("input");
    checkbox.type = "checkbox"; checkbox.className = "doc-checkbox";
    if (!skeleton) checkbox.setAttribute("aria-label", "Ask about " + d.name);
    var checkCell = el("label", "mp-list-item__check"); // the label is the (large) tap target; the checkbox stays small
    checkCell.appendChild(checkbox);
    var body = el("div", "mp-list-item__body");
    var title = el("div", "mp-list-item__title", skeleton ? "Loading document name" : (DOC_ICONS[d.type] || "📄") + " " + d.name);
    body.appendChild(title);
    var del = el("button", "mp-btn mp-btn--ghost mp-btn--sm", "🗑");
    del.type = "button";
    row.appendChild(checkCell); row.appendChild(body); row.appendChild(del);

    if (skeleton) {
      row.setAttribute("aria-hidden", "true");
      checkbox.disabled = true; checkbox.tabIndex = -1;
      del.disabled = true; del.tabIndex = -1;
      return row;
    }
    row.style.viewTransitionName = docTransitionName(d.id); // so the other rows glide up when this one goes
    checkbox.checked = askAll || selectedDocumentIds.has(d.id);
    checkbox.disabled = askAll;
    checkbox.addEventListener("change", function () {
      if (checkbox.checked) selectedDocumentIds.add(d.id); else selectedDocumentIds.delete(d.id);
    });
    del.title = "Delete";
    del.addEventListener("click", function () { deleteDocument(d.id); });
    return row;
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

  var uploading = false;

  async function uploadFile(file) {
    if (uploading) return; // a second click, drop or Enter while one is running would just send the same file twice
    uploading = true;
    var uploadBtn = document.getElementById("uploadBtn");
    var dropzone = document.getElementById("dropzone");
    uploadBtn.disabled = true;
    dropzone.classList.add("is-busy");
    try {
      await flushPendingDeletes(); // a document deleted a moment ago must be really gone before the same file is added again
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
    } finally {
      uploading = false;
      uploadBtn.disabled = false;
      dropzone.classList.remove("is-busy");
    }
  }

  var pendingDeletes = {}; // document id -> function that sends its DELETE right now

  // No confirm dialog. The row leaves the list at once (optimistic) and an Undo toast opens; the DELETE is only
  // sent when the toast runs out, so Undo is a pure client-side step. If the server then refuses, the row returns.
  async function deleteDocument(id) {
    var index = allDocuments.findIndex(function (d) { return d.id === id; });
    if (index === -1) return;
    var doc = allDocuments.splice(index, 1)[0];
    pendingDeleteIds.add(id);
    renderDocsListAnimated();

    var timer = null;
    var toast = null;

    function undo() {
      clearTimeout(timer);
      delete pendingDeletes[id];
      pendingDeleteIds.delete(id);
      index = Math.min(index, allDocuments.length);
      allDocuments.splice(index, 0, doc);
      renderDocsListAnimated();
    }

    async function send() {
      delete pendingDeletes[id];
      // keepalive lets the request finish even if the tab is closing
      var result = await callApi("/documents/" + encodeURIComponent(id), { method: "DELETE", keepalive: true });
      pendingDeleteIds.delete(id);
      if (!result.ok && result.status !== 404) {
        index = Math.min(index, allDocuments.length);
        allDocuments.splice(index, 0, doc);
        renderDocsListAnimated();
        showToast("Couldn't delete " + doc.name + ". " + result.message);
      }
    }

    pendingDeletes[id] = function () { clearTimeout(timer); if (toast) toast.dismiss(); return send(); };
    timer = setTimeout(send, UNDO_MS);
    toast = showToast("Deleted " + doc.name, { duration: UNDO_MS, action: { label: "Undo", onClick: undo } });
  }

  // Send every delete that is still waiting out its Undo window (before an upload, or when the page goes away).
  function flushPendingDeletes() {
    return Promise.all(Object.keys(pendingDeletes).map(function (id) { return pendingDeletes[id](); }));
  }
  window.addEventListener("pagehide", function () { flushPendingDeletes(); });

  // ---------------------------------------------------------------- //
  // Command menu (Cmd/Ctrl+K): search every page and action, keyboard only
  // ---------------------------------------------------------------- //

  // ---- keyboard shortcuts: one registry, shown wherever the action appears ----

  var IS_MAC = /Mac|iPhone|iPad|iPod/i.test((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "");

  // `mod` = Cmd on Mac, Ctrl elsewhere. Chords with `mod` work even inside the message box (they can't type a
  // character); plain keys never fire while someone is typing in a field.
  var SHORTCUTS = {
    commandMenu: { key: "k", mod: true, run: function () { if (commandMenu.hidden) openCommandMenu(); else closeCommandMenu(); } },
    newChat: { key: "o", mod: true, shift: true, run: function () { document.getElementById("newChatBtn").click(); } },
    focusInput: { key: "/", run: function () { input.focus(); } },
  };

  function formatShortcut(def) {
    var key = def.key.length === 1 ? def.key.toUpperCase() : def.key;
    if (IS_MAC) return (def.mod ? "⌘" : "") + (def.shift ? "⇧" : "") + key;
    return (def.mod ? "Ctrl+" : "") + (def.shift ? "Shift+" : "") + key;
  }

  function shortcutLabel(id) { return SHORTCUTS[id] ? formatShortcut(SHORTCUTS[id]) : ""; }

  function makeKbd(id) { return el("kbd", "mp-kbd", shortcutLabel(id)); }

  function isTypingTarget(node) {
    if (!node || !node.closest) return false;
    var field = node.closest("input, textarea, select, [contenteditable]");
    if (!field) return false;
    if (field.tagName === "INPUT") return !/^(checkbox|radio|button|submit|reset|file|range|color|image)$/.test(field.type);
    return true;
  }

  function matchesShortcut(e, def) {
    if (e.key.toLowerCase() !== def.key) return false;
    var modDown = IS_MAC ? e.metaKey : e.ctrlKey;
    var otherMod = IS_MAC ? e.ctrlKey : e.metaKey;
    return !!def.mod === modDown && !otherMod && !!def.shift === e.shiftKey && !e.altKey;
  }

  document.addEventListener("keydown", function (e) {
    if (e.defaultPrevented || e.isComposing) return;
    var typing = isTypingTarget(e.target);
    var ids = Object.keys(SHORTCUTS);
    for (var i = 0; i < ids.length; i++) {
      var def = SHORTCUTS[ids[i]];
      if (!matchesShortcut(e, def)) continue;
      if (typing && !def.mod) return;
      if (ids[i] !== "commandMenu" && (!commandMenu.hidden || !settingsModal.hidden)) return; // a dialog owns the keyboard
      e.preventDefault();
      def.run();
      return;
    }
  });

  // A tooltip is "text (shortcut)". setTip keeps the plain text so the hint can be recomputed.
  function applyHint(node) {
    var id = node.getAttribute("data-shortcut");
    var base = node.dataset.tipBase || node.getAttribute("title") || "";
    node.dataset.tipBase = base;
    var label = shortcutLabel(id);
    node.title = label ? (base ? base + " (" + label + ")" : label) : base;
  }

  function setTip(node, text) { node.dataset.tipBase = text; applyHint(node); }

  function applyShortcutHints() {
    document.querySelectorAll("[data-shortcut]").forEach(function (node) {
      var id = node.getAttribute("data-shortcut");
      var def = SHORTCUTS[id];
      if (!def) return;
      applyHint(node);
      node.setAttribute("aria-keyshortcuts", (def.mod ? (IS_MAC ? "Meta+" : "Control+") : "") + (def.shift ? "Shift+" : "") + (def.key.length === 1 ? def.key.toUpperCase() : def.key));
      if (node.hasAttribute("data-shortcut-badge") && !node.querySelector(".mp-kbd")) node.appendChild(makeKbd(id));
    });
  }

  var commandMenu = document.getElementById("commandMenu");
  var cmdInput = document.getElementById("cmdInput");
  var cmdList = document.getElementById("cmdList");
  var cmdEmpty = document.getElementById("cmdEmpty");
  var cmdVisible = [];   // the actions currently listed, in order
  var cmdIndex = 0;      // which of them is highlighted
  var cmdReturnFocus = null;

  // Built each time the menu opens so it always reflects the current SUGGESTIONS.
  function buildCommandActions() {
    var actions = [
      { id: "newChat", label: "New chat", shortcut: "newChat", keywords: "clear reset conversation", run: function () { document.getElementById("newChatBtn").click(); } },
      { id: "chat", label: "Go to chat", keywords: "close panel back", run: closePanel },
      { id: "documents", label: "Open documents", keywords: "files rag manage", run: function () { openPanel("documents"); } },
      { id: "upload", label: "Upload a document", keywords: "file pdf docx csv json txt", run: function () { openPanel("documents"); fileInput.click(); } },
      { id: "theme", label: "Toggle light / dark theme", keywords: "appearance mode", run: toggleTheme },
      { id: "settings", label: "Model & API key", keywords: "provider settings bring your own key", run: openSettings },
      { id: "focusInput", label: "Focus the message box", shortcut: "focusInput", keywords: "type write compose", run: function () { input.focus(); } },
    ];
    SUGGESTIONS.forEach(function (text, i) {
      actions.push({ id: "prompt" + i, label: "Ask: " + text, keywords: "suggestion prompt example", run: function () { input.value = text; input.focus(); autosizeInput(); } });
    });
    return actions;
  }

  // Every typed word must appear somewhere in the label or keywords; label-prefix matches sort first.
  function filterCommands(actions, query) {
    var words = query.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return actions;
    return actions.filter(function (a) {
      var hay = (a.label + " " + (a.keywords || "")).toLowerCase();
      return words.every(function (w) { return hay.indexOf(w) !== -1; });
    }).sort(function (a, b) {
      return (b.label.toLowerCase().indexOf(words[0]) === 0) - (a.label.toLowerCase().indexOf(words[0]) === 0);
    });
  }

  function setActiveCommand(index) {
    cmdIndex = index;
    Array.prototype.forEach.call(cmdList.children, function (li, i) { li.setAttribute("aria-selected", String(i === index)); });
    var active = cmdList.children[index];
    if (active) {
      cmdInput.setAttribute("aria-activedescendant", active.id);
      active.scrollIntoView({ block: "nearest" });
    } else {
      cmdInput.removeAttribute("aria-activedescendant");
    }
  }

  function renderCommandList() {
    cmdVisible = filterCommands(buildCommandActions(), cmdInput.value);
    cmdList.replaceChildren.apply(cmdList, cmdVisible.map(function (action, i) {
      var li = el("li", "mp-cmd__item");
      li.id = "cmd-opt-" + i;
      li.setAttribute("role", "option");
      li.appendChild(el("span", "mp-cmd__label", action.label));
      if (action.shortcut) li.appendChild(makeKbd(action.shortcut));
      li.addEventListener("mousedown", function (e) { e.preventDefault(); }); // keep focus in the field
      li.addEventListener("mousemove", function () { if (cmdIndex !== i) setActiveCommand(i); });
      li.addEventListener("click", function () { runCommand(i); });
      return li;
    }));
    cmdEmpty.hidden = cmdVisible.length > 0;
    setActiveCommand(0);
  }

  function openCommandMenu() {
    if (!commandMenu.hidden || !settingsModal.hidden) return;
    cmdReturnFocus = document.activeElement;
    cmdInput.value = "";
    commandMenu.hidden = false;
    renderCommandList();
    cmdInput.focus();
  }

  function closeCommandMenu() {
    if (commandMenu.hidden) return;
    commandMenu.hidden = true;
    if (cmdReturnFocus && cmdReturnFocus.focus) cmdReturnFocus.focus();
    cmdReturnFocus = null;
  }

  function runCommand(index) {
    var action = cmdVisible[index];
    if (!action) return;
    closeCommandMenu(); // first, so an action that moves focus (or opens a dialog) wins it
    action.run();
  }

  function onCommandKeydown(e) {
    if (e.isComposing) return;
    var count = cmdVisible.length;
    if (e.key === "ArrowDown") { e.preventDefault(); if (count) setActiveCommand((cmdIndex + 1) % count); }
    else if (e.key === "ArrowUp") { e.preventDefault(); if (count) setActiveCommand((cmdIndex - 1 + count) % count); }
    else if (e.key === "Enter") { e.preventDefault(); runCommand(cmdIndex); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeCommandMenu(); } // not also the panel behind it
    else if (e.key === "Tab") { e.preventDefault(); } // the field is the only stop; arrows move through the list
  }

  cmdInput.addEventListener("keydown", onCommandKeydown);
  cmdInput.addEventListener("input", renderCommandList);
  commandMenu.addEventListener("click", function (e) { if (e.target === commandMenu) closeCommandMenu(); });
  document.getElementById("cmdBtn").addEventListener("click", openCommandMenu);

  // ---------------------------------------------------------------- //
  // Revalidate: refresh what is on screen when the window regains focus or the network comes back
  // ---------------------------------------------------------------- //

  var REVALIDATE_MIN_GAP_MS = 5000; // focus fires a lot; don't hammer the server

  function revalidate(force) {
    var now = Date.now();
    if (activePanel === "documents" && (force || now - lastDocsFetch > REVALIDATE_MIN_GAP_MS)) loadDocuments();
    if (force || now - lastStatusFetch > 30000) loadStatus();
  }

  window.addEventListener("focus", function () { revalidate(false); });
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible") revalidate(false); });
  window.addEventListener("online", function () { revalidate(true); });

  // ---------------------------------------------------------------- //
  // Boot
  // ---------------------------------------------------------------- //

  applyShortcutHints();
  renderMessages();
  loadDocuments();  // warm the cache, so the first time Documents opens it is already there
  loadStatus(true); // fills the sidebar's provider badge and asks for an API key right away if none is set
})();
