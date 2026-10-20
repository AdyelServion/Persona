(() => {
  const messagesEl = document.getElementById("messages");
  const form = document.getElementById("composer");
  const input = document.getElementById("input");
  const sendBtn = document.getElementById("send");
  const statusEl = document.getElementById("status");
  const errorEl = document.getElementById("error");
  const countdownToggle = document.getElementById("countdownToggle");

  const COUNTDOWN_KEY = "persona.countdownEnabled";

  let conversationId = null;
  let lastSequence = 0;
  const seenIds = new Set();
  let pollTimer = null;
  let pollIntervalMs = 0;
  let countdownTimer = null;
  let currentPresence = "none";
  let scheduledForIso = null;
  let activityLabel = null;
  let countdownEnabled = true;

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

  function appendBubble(sender, content, messageId) {
    if (messageId && seenIds.has(messageId)) return;
    if (messageId) seenIds.add(messageId);
    const div = document.createElement("div");
    div.className = `bubble ${sender}`;
    if (messageId) div.dataset.messageId = messageId;
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = sender === "user" ? "You" : "Sarah";
    div.appendChild(meta);
    div.appendChild(document.createTextNode(content));
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function formatCountdown(msRemaining) {
    if (msRemaining <= 0) return "Any moment";
    const totalSec = Math.max(1, Math.round(msRemaining / 1000));
    if (totalSec < 120) {
      return `~${totalSec}s`;
    }
    const totalMin = Math.round(totalSec / 60);
    if (totalMin < 60) {
      return `~${totalMin} min`;
    }
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
    if (activityLabel) {
      return `${activityLabel} · ${eta}`;
    }
    return eta;
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
      if (countdownEnabled && scheduledForIso) {
        statusEl.textContent = waitingLabel();
        return;
      }
      // Countdown off — no ETA; keep quiet unless away/online handled elsewhere
      statusEl.textContent = "";
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
    if (!conversationId) {
      statusEl.textContent = "Connecting…";
      return;
    }
    statusEl.textContent = "";
  }

  function stopCountdownTick() {
    if (countdownTimer) {
      clearInterval(countdownTimer);
      countdownTimer = null;
    }
  }

  function startCountdownTick() {
    stopCountdownTick();
    if (
      countdownEnabled &&
      currentPresence === "waiting" &&
      scheduledForIso
    ) {
      countdownTimer = setInterval(renderStatusLabel, 1000);
    }
  }

  function applyPresenceSnapshot(data) {
    if (!data || typeof data !== "object") return;
    currentPresence = data.presence || "none";
    scheduledForIso =
      currentPresence === "waiting" && data.scheduled_for
        ? data.scheduled_for
        : null;
    activityLabel =
      currentPresence === "waiting"
        ? data.activity_label || null
        : null;
    renderStatusLabel();
    startCountdownTick();
    startPolling();
  }

  function updateSendEnabled() {
    sendBtn.disabled = !input.value.trim() || !conversationId;
  }

  async function pollMessages() {
    if (!conversationId) return;
    try {
      const resp = await fetch(
        `/api/messages/?conversation_id=${encodeURIComponent(conversationId)}&after_sequence=${lastSequence}`
      );
      const data = await resp.json();
      if (!resp.ok) return;
      (data.messages || []).forEach((m) => {
        appendBubble(m.sender, m.content, m.message_id);
        if (typeof m.sequence === "number" && m.sequence > lastSequence) {
          lastSequence = m.sequence;
        }
      });
      applyPresenceSnapshot(data);
    } catch (_) {
      /* polling is best-effort */
    }
  }

  function startPolling() {
    const ms = currentPresence === "replying" ? 800 : 2500;
    if (pollTimer && pollIntervalMs === ms) return;
    if (pollTimer) clearInterval(pollTimer);
    pollIntervalMs = ms;
    pollTimer = setInterval(pollMessages, ms);
  }

  async function bootstrap() {
    showError("");
    statusEl.textContent = "Connecting…";
    try {
      const resp = await fetch("/api/bootstrap/");
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Failed to bootstrap");
      conversationId = data.conversation_id;
      messagesEl.innerHTML = "";
      seenIds.clear();
      lastSequence = 0;
      (data.messages || []).forEach((m) => {
        appendBubble(m.sender, m.content, m.message_id);
        if (typeof m.sequence === "number" && m.sequence > lastSequence) {
          lastSequence = m.sequence;
        }
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
      const lastAssistant = [...(data.messages || [])].reverse().find((m) => m.sender === "assistant");
      if (lastAssistant) {
        fetch("/api/seen/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            conversation_id: conversationId,
            message_id: lastAssistant.message_id,
          }),
        }).catch(() => {});
      }
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

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const content = input.value.trim();
    if (!content || !conversationId) return;
    showError("");
    // Optimistic UI — keep input enabled for further messages
    appendBubble("user", content, null);
    input.value = "";
    input.style.height = "auto";
    updateSendEnabled();

    try {
      const resp = await fetch("/api/send/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId, content }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Send failed");
      const um = data.user_message;
      if (um && um.message_id) {
        // Tag last optimistic bubble if needed — re-poll will dedupe by id later
        seenIds.add(um.message_id);
        if (typeof um.sequence === "number" && um.sequence > lastSequence) {
          lastSequence = um.sequence;
        }
      }
      applyPresenceSnapshot(data);
      // Do not wait for Sarah — poll will deliver her reply
      pollMessages();
    } catch (err) {
      showError(err.message || String(err));
    }
  });

  bootstrap();
})();
