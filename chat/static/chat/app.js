(() => {
  const messagesEl = document.getElementById("messages");
  const form = document.getElementById("composer");
  const input = document.getElementById("input");
  const sendBtn = document.getElementById("send");
  const statusEl = document.getElementById("status");
  const errorEl = document.getElementById("error");
  const countdownToggle = document.getElementById("countdownToggle");
  const userListEl = document.getElementById("userList");
  const activeUserLabel = document.getElementById("activeUserLabel");
  const userIdLine = document.getElementById("userIdLine");
  const activeUserIdText = document.getElementById("activeUserIdText");
  const copyUserId = document.getElementById("copyUserId");
  const newChatBtn = document.getElementById("newChatBtn");
  const modal = document.getElementById("newChatModal");
  const modalForm = document.getElementById("newChatForm");
  const ncUserId = document.getElementById("ncUserId");
  const ncName = document.getElementById("ncName");
  const ncInterests = document.getElementById("ncInterests");
  const ncOptIn = document.getElementById("ncOptIn");
  const ncCancel = document.getElementById("ncCancel");
  const ncError = document.getElementById("ncError");
  const settingsBtn = document.getElementById("settingsBtn");
  const settingsPanel = document.getElementById("settingsPanel");
  const setEnabled = document.getElementById("setEnabled");
  const setQuietStart = document.getElementById("setQuietStart");
  const setQuietEnd = document.getElementById("setQuietEnd");
  const setPause = document.getElementById("setPause");
  const setResume = document.getElementById("setResume");
  const setPausedNote = document.getElementById("setPausedNote");
  const setSave = document.getElementById("setSave");
  const setClose = document.getElementById("setClose");

  const COUNTDOWN_KEY = "persona.countdownEnabled";
  const USERS_REFRESH_MS = 30000;

  let activeUserId = null;
  let users = [];
  let canCreate = true;
  let conversationId = null;
  let lastSequence = 0;
  const seenIds = new Set();
  let lastSeenAssistantId = null;
  let pollTimer = null;
  let pollIntervalMs = 0;
  let countdownTimer = null;
  let currentPresence = "none";
  let scheduledForIso = null;
  let activityLabel = null;
  let countdownEnabled = true;
  let bootGeneration = 0;

  // ------------------------------------------------------------ helpers

  function csrfToken() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  async function api(method, url, body) {
    const opts = { method, headers: {} };
    if (method !== "GET") {
      opts.headers["Content-Type"] = "application/json";
      opts.headers["X-CSRFToken"] = csrfToken();
      opts.body = JSON.stringify(body || {});
    }
    const resp = await fetch(url, opts);
    let data = {};
    try {
      data = await resp.json();
    } catch (_) {
      data = {};
    }
    return { ok: resp.ok, status: resp.status, data };
  }

  function loadCountdownPref() {
    try {
      const raw = localStorage.getItem(COUNTDOWN_KEY);
      if (raw === null) return true;
      return raw === "1" || raw === "true";
    } catch (_) {
      return true;
    }
  }

  function saveCountdownPref(on) {
    try {
      localStorage.setItem(COUNTDOWN_KEY, on ? "1" : "0");
    } catch (_) {
      /* ignore */
    }
  }

  countdownEnabled = loadCountdownPref();
  if (countdownToggle) {
    countdownToggle.checked = countdownEnabled;
    countdownToggle.addEventListener("change", () => {
      countdownEnabled = !!countdownToggle.checked;
      saveCountdownPref(countdownEnabled);
      renderStatusLabel();
      startCountdownTick();
    });
  }

  function showError(msg) {
    errorEl.hidden = !msg;
    errorEl.textContent = msg || "";
  }

  // ------------------------------------------------------------ messages

  function appendBubble(m) {
    const messageId = m.message_id;
    if (messageId && seenIds.has(messageId)) return;
    if (messageId) seenIds.add(messageId);
    const sender = m.sender === "user" ? "user" : "assistant";
    const div = document.createElement("div");
    div.className = `bubble ${sender}`;
    if (m.message_type === "proactive") div.classList.add("proactive");
    if (messageId) div.dataset.messageId = messageId;
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = sender === "user" ? "You" : "Sarah";
    if (m.message_type === "proactive") {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = "messaged first";
      meta.appendChild(tag);
    }
    div.appendChild(meta);
    div.appendChild(document.createTextNode(m.content || ""));
    const typing = document.getElementById("typing");
    if (typing) messagesEl.insertBefore(div, typing);
    else messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    if (sender === "assistant" && messageId) markSeenSoon(messageId);
  }

  function markSeenSoon(messageId) {
    if (document.visibilityState !== "visible" || !conversationId) return;
    if (messageId === lastSeenAssistantId) return;
    lastSeenAssistantId = messageId;
    api("POST", "/api/seen/", { conversation_id: conversationId, message_id: messageId }).catch(() => {});
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    const last = [...messagesEl.querySelectorAll(".bubble.assistant")].pop();
    if (last && last.dataset.messageId) markSeenSoon(last.dataset.messageId);
    refreshUsers();
  });

  // ------------------------------------------------------------ presence / countdown

  function formatCountdown(msRemaining) {
    if (msRemaining <= 0) return "Any moment";
    const totalSec = Math.max(1, Math.round(msRemaining / 1000));
    if (totalSec < 120) return `~${totalSec}s`;
    const totalMin = Math.round(totalSec / 60);
    if (totalMin < 60) return `~${totalMin} min`;
    const hours = Math.floor(totalMin / 60);
    const mins = totalMin % 60;
    if (mins === 0) return `~${hours}h`;
    return `~${hours}h ${mins}m`;
  }

  function waitingLabel() {
    if (!scheduledForIso) return "Waiting…";
    const due = Date.parse(scheduledForIso);
    if (Number.isNaN(due)) return "Waiting…";
    const eta = formatCountdown(due - Date.now());
    return activityLabel ? `${activityLabel} · ${eta}` : eta;
  }

  function renderStatusLabel() {
    let typing = document.getElementById("typing");
    if (currentPresence === "replying") {
      statusEl.textContent = "Sarah is replying…";
      if (!typing) {
        typing = document.createElement("div");
        typing.id = "typing";
        typing.className = "typing";
        typing.textContent = "Sarah is replying…";
        messagesEl.appendChild(typing);
      }
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return;
    }
    if (typing) typing.remove();
    if (currentPresence === "waiting") {
      statusEl.textContent = countdownEnabled && scheduledForIso ? waitingLabel() : "";
      return;
    }
    if (currentPresence === "online") {
      statusEl.textContent = "Online";
      return;
    }
    if (currentPresence === "away") {
      statusEl.textContent = "Away";
      return;
    }
    statusEl.textContent = conversationId ? "" : activeUserId ? "Connecting…" : "";
  }

  function stopCountdownTick() {
    if (countdownTimer) {
      clearInterval(countdownTimer);
      countdownTimer = null;
    }
  }

  function startCountdownTick() {
    stopCountdownTick();
    if (countdownEnabled && currentPresence === "waiting" && scheduledForIso) {
      countdownTimer = setInterval(renderStatusLabel, 1000);
    }
  }

  function applyPresenceSnapshot(data) {
    if (!data || typeof data !== "object") return;
    currentPresence = data.presence || "none";
    scheduledForIso = currentPresence === "waiting" && data.scheduled_for ? data.scheduled_for : null;
    activityLabel = currentPresence === "waiting" ? data.activity_label || null : null;
    renderStatusLabel();
    startCountdownTick();
    startPolling();
  }

  function updateSendEnabled() {
    sendBtn.disabled = !input.value.trim() || !conversationId;
  }

  async function pollMessages() {
    if (!conversationId) return;
    const gen = bootGeneration;
    try {
      const { ok, data } = await api(
        "GET",
        `/api/messages/?conversation_id=${encodeURIComponent(conversationId)}&after_sequence=${lastSequence}`
      );
      if (!ok || gen !== bootGeneration) return;
      (data.messages || []).forEach((m) => {
        appendBubble(m);
        if (typeof m.sequence === "number" && m.sequence > lastSequence) lastSequence = m.sequence;
      });
      applyPresenceSnapshot(data);
    } catch (_) {
      /* polling is best-effort */
    }
  }

  function startPolling() {
    if (!conversationId) return;
    const ms = currentPresence === "replying" ? 800 : 2500;
    if (pollTimer && pollIntervalMs === ms) return;
    if (pollTimer) clearInterval(pollTimer);
    pollIntervalMs = ms;
    pollTimer = setInterval(pollMessages, ms);
  }

  function resetChat() {
    bootGeneration += 1;
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    pollIntervalMs = 0;
    stopCountdownTick();
    conversationId = null;
    lastSequence = 0;
    lastSeenAssistantId = null;
    seenIds.clear();
    messagesEl.innerHTML = "";
    currentPresence = "none";
    updateSendEnabled();
  }

  // ------------------------------------------------------------ users / sidebar

  function initials(name) {
    return (name || "?")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0].toUpperCase())
      .join("");
  }

  function renderUsers() {
    userListEl.innerHTML = "";
    users.forEach((u) => {
      const li = document.createElement("li");
      li.className = "user-item" + (u.user_id === activeUserId ? " active" : "");
      li.dataset.userId = u.user_id;
      const av = document.createElement("span");
      av.className = "user-avatar";
      av.textContent = initials(u.display_name);
      const body = document.createElement("span");
      body.className = "user-body";
      const name = document.createElement("span");
      name.className = "user-name";
      name.textContent = u.display_name || "Unnamed";
      const preview = document.createElement("span");
      preview.className = "user-preview";
      const conv = (u.conversations || [])[0];
      preview.textContent = conv && conv.last_message ? conv.last_message.content : "No messages yet";
      body.appendChild(name);
      body.appendChild(preview);
      li.appendChild(av);
      li.appendChild(body);
      if (u.unread_count > 0 && u.user_id !== activeUserId) {
        const dot = document.createElement("span");
        dot.className = "unread";
        dot.textContent = u.unread_count > 9 ? "9+" : String(u.unread_count);
        li.appendChild(dot);
      }
      li.addEventListener("click", () => switchUser(u.user_id));
      userListEl.appendChild(li);
    });
    newChatBtn.disabled = !canCreate;
    const active = users.find((u) => u.user_id === activeUserId);
    activeUserLabel.textContent = active ? `chatting as ${active.display_name}` : "not signed in";
    if (active) {
      userIdLine.hidden = false;
      activeUserIdText.textContent = active.user_id;
      activeUserIdText.title = active.user_id;
      copyUserId.textContent = "Copy";
    } else {
      userIdLine.hidden = true;
      activeUserIdText.textContent = "";
    }
    settingsBtn.disabled = !active;
  }

  copyUserId.addEventListener("click", async () => {
    const id = activeUserIdText.textContent || "";
    if (!id) return;
    try {
      await navigator.clipboard.writeText(id);
      copyUserId.textContent = "Copied";
    } catch (_) {
      activeUserIdText.textContent = id;
    }
  });

  async function refreshUsers() {
    try {
      const { ok, data } = await api("GET", "/api/users/");
      if (!ok) return;
      users = data.users || [];
      canCreate = data.can_create !== false;
      if (data.active_user_id && !activeUserId) activeUserId = data.active_user_id;
      renderUsers();
    } catch (_) {
      /* best-effort */
    }
  }

  async function switchUser(userId) {
    if (userId === activeUserId) return;
    const { ok, data } = await api("POST", "/api/users/switch/", { user_id: userId });
    if (!ok) {
      showError(data.error || "Could not switch chat");
      return;
    }
    activeUserId = data.active_user_id;
    settingsPanel.hidden = true;
    renderUsers();
    resetChat();
    bootstrap();
  }

  // ------------------------------------------------------------ new chat modal

  let modalRequired = false;

  function openModal(required) {
    modalRequired = !!required;
    ncCancel.hidden = modalRequired;
    ncError.hidden = true;
    ncUserId.value = "";
    ncName.value = "";
    ncInterests.value = "";
    ncOptIn.checked = false;
    modal.hidden = false;
    setTimeout(() => ncName.focus(), 0);
  }

  function closeModal() {
    if (modalRequired) return;
    modal.hidden = true;
  }

  newChatBtn.addEventListener("click", () => openModal(false));
  ncCancel.addEventListener("click", closeModal);
  modal.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  modalForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const existingId = ncUserId.value.trim();
    let ok;
    let data;
    if (existingId) {
      ({ ok, data } = await api("POST", "/api/users/resume/", { user_id: existingId }));
    } else {
      const name = ncName.value.trim();
      if (!name) {
        ncError.hidden = false;
        ncError.textContent = "Enter your name, or paste a user id to open an existing chat.";
        return;
      }
      let tz = null;
      try {
        tz = Intl.DateTimeFormat().resolvedOptions().timeZone || null;
      } catch (_) {
        tz = null;
      }
      ({ ok, data } = await api("POST", "/api/users/new/", {
        display_name: name,
        interests: ncInterests.value,
        proactive_opt_in: ncOptIn.checked,
        timezone: tz,
      }));
    }
    if (!ok) {
      ncError.hidden = false;
      ncError.textContent = data.error || "Could not create chat";
      return;
    }
    modalRequired = false;
    modal.hidden = true;
    activeUserId = data.user_id;
    resetChat();
    await refreshUsers();
    bootstrap();
  });

  // ------------------------------------------------------------ proactive settings

  async function openSettings() {
    const { ok, data } = await api("GET", "/api/proactive-settings/");
    if (!ok) {
      showError(data.error || "Could not load settings");
      return;
    }
    setEnabled.checked = !!data.enabled;
    setQuietStart.value = data.quiet_start || "22:00";
    setQuietEnd.value = data.quiet_end || "08:00";
    setPausedNote.textContent = data.paused_until
      ? `Paused until ${new Date(data.paused_until).toLocaleString()}`
      : "";
    settingsPanel.hidden = false;
  }

  async function saveSettings(extra) {
    const body = Object.assign(
      {
        enabled: setEnabled.checked,
        quiet_start: setQuietStart.value || null,
        quiet_end: setQuietEnd.value || null,
      },
      extra || {}
    );
    const { ok, data } = await api("POST", "/api/proactive-settings/", body);
    if (!ok) {
      showError(data.error || "Could not save settings");
      return false;
    }
    setPausedNote.textContent = data.paused_until
      ? `Paused until ${new Date(data.paused_until).toLocaleString()}`
      : "";
    return true;
  }

  settingsBtn.addEventListener("click", () => {
    if (settingsPanel.hidden) openSettings();
    else settingsPanel.hidden = true;
  });
  setClose.addEventListener("click", () => (settingsPanel.hidden = true));
  setSave.addEventListener("click", async () => {
    if (await saveSettings()) settingsPanel.hidden = true;
  });
  setPause.addEventListener("click", () => saveSettings({ pause_hours: 24 }));
  setResume.addEventListener("click", () => saveSettings({ pause_hours: 0 }));

  // ------------------------------------------------------------ bootstrap / send

  async function bootstrap() {
    showError("");
    const gen = bootGeneration;
    statusEl.textContent = "Connecting…";
    try {
      const { ok, data } = await api("GET", "/api/bootstrap/");
      if (gen !== bootGeneration) return;
      if (data.needs_user) {
        statusEl.textContent = "";
        await refreshUsers();
        if (!users.length) openModal(true);
        else switchUser(users[0].user_id);
        return;
      }
      if (!ok) throw new Error(data.error || "Failed to bootstrap");
      activeUserId = data.user_id;
      conversationId = data.conversation_id;
      messagesEl.innerHTML = "";
      seenIds.clear();
      lastSequence = 0;
      (data.messages || []).forEach((m) => {
        appendBubble(m);
        if (typeof m.sequence === "number" && m.sequence > lastSequence) lastSequence = m.sequence;
      });
      const opening = data.opening || {};
      applyPresenceSnapshot({
        presence: opening.presence || "none",
        scheduled_for: opening.scheduled_for || null,
        spare_time: opening.spare_time,
        activity: opening.activity,
        activity_label: opening.activity_label,
        reason: opening.reason,
      });
      updateSendEnabled();
      startPolling();
      pollMessages();
      refreshUsers();
    } catch (err) {
      showError(err.message || String(err));
      statusEl.textContent = "Offline";
      stopCountdownTick();
    }
  }

  input.addEventListener("input", () => {
    updateSendEnabled();
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const content = input.value.trim();
    if (!content || !conversationId) return;
    showError("");
    appendBubble({ sender: "user", content, message_id: null });
    input.value = "";
    input.style.height = "auto";
    updateSendEnabled();
    try {
      const { ok, data } = await api("POST", "/api/send/", { conversation_id: conversationId, content });
      if (!ok) throw new Error(data.error || "Send failed");
      const um = data.user_message;
      if (um && um.message_id) {
        seenIds.add(um.message_id);
        if (typeof um.sequence === "number" && um.sequence > lastSequence) lastSequence = um.sequence;
      }
      applyPresenceSnapshot(data);
      pollMessages();
    } catch (err) {
      showError(err.message || String(err));
    }
  });

  setInterval(refreshUsers, USERS_REFRESH_MS);
  refreshUsers().then(bootstrap);
})();
