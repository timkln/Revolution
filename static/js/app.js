/* ============================================================
   Revolution – AI Notifier – Frontend JS
   ============================================================ */

"use strict";

// ---- Utilities ----

const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

function toast(title, msg = "", type = "info", duration = 4000) {
  const container = $("#toast-container");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = `
    <div>
      <div class="toast-title">${escHtml(title)}</div>
      ${msg ? `<div class="toast-msg">${escHtml(msg)}</div>` : ""}
    </div>`;
  container.appendChild(el);
  setTimeout(() => el.remove(), duration);
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function timeAgo(isoStr) {
  const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
  if (diff < 60)   return "à l'instant";
  if (diff < 3600) return `il y a ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `il y a ${Math.floor(diff / 3600)} h`;
  return `il y a ${Math.floor(diff / 86400)} j`;
}

function scoreClass(score) {
  if (score >= 8) return "score-high";
  if (score >= 6) return "score-medium";
  return "score-low";
}

// ---- SocketIO ----

let socket;

// ---- Event bus for cross-component communication ----
const eventBus = new EventTarget();

function initSocket() {
  socket = io({ transports: ["websocket", "polling"] });

  socket.on("connect", () => {
    console.info("[Revolution] WebSocket connected");
  });

  socket.on("new_notifications", ({ notifications }) => {
    if (!notifications || !notifications.length) return;
    toast(
      `🔔 ${notifications.length} nouvelle(s) notification(s)`,
      notifications[0].title,
      "info",
      6000
    );
    eventBus.dispatchEvent(
      Object.assign(new Event("new_notifications"), { notifications })
    );
    refreshStatus();
  });

  socket.on("init", ({ unread_count }) => {
    updateNavBadge(unread_count);
  });
}

// ---- Status ----

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    const dot  = $("#status-dot");
    const text = $("#status-text");
    if (data.ai_configured) {
      dot.className = "status-dot ok";
      text.textContent = "IA connectée";
    } else {
      dot.className = "status-dot err";
      text.textContent = "Clé API manquante";
    }
    updateNavBadge(data.unread_count);
    return data;
  } catch {
    return null;
  }
}

function updateNavBadge(count) {
  const badge = $("#nav-badge");
  if (!badge) return;
  if (count > 0) {
    badge.textContent = count;
    badge.style.display = "inline-block";
  } else {
    badge.style.display = "none";
  }
}

// ===========================================================
// Dashboard page
// ===========================================================

let _allNotifs = [];
let _currentFilter = "all";

async function initDashboard() {
  initSocket();
  refreshStatus();
  await loadNotifications();

  eventBus.addEventListener("new_notifications", (e) => {
    _allNotifs = [...e.notifications, ..._allNotifs];
    renderNotifications();
  });

  // Manual check button
  $("#btn-check-now")?.addEventListener("click", async () => {
    const btn = $("#btn-check-now");
    btn.disabled = true;
    btn.textContent = "Analyse en cours…";
    try {
      const res = await fetch("/api/check", { method: "POST" });
      const data = await res.json();
      toast("Analyse lancée", data.message || "", "info");
    } catch {
      toast("Erreur", "Impossible de lancer l'analyse", "error");
    }
    setTimeout(() => {
      btn.disabled = false;
      btn.innerHTML = '<span class="btn-icon">🔍</span> Analyser maintenant';
    }, 5000);
  });

  // Mark-all-read button
  $("#btn-mark-all-read")?.addEventListener("click", async () => {
    await fetch("/api/notifications/read-all", { method: "POST" });
    _allNotifs.forEach(n => (n.read = true));
    renderNotifications();
    refreshStatus();
    toast("Tout marqué comme lu", "", "success");
  });

  // Filter buttons
  $$(".filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      $$(".filter-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      _currentFilter = btn.dataset.filter;
      renderNotifications();
    });
  });
}

async function loadNotifications() {
  const loading = $("#loading");
  const list    = $("#notifications-list");
  if (loading) loading.style.display = "flex";
  if (list)    list.innerHTML = "";

  try {
    const res  = await fetch("/api/notifications");
    _allNotifs = await res.json();
  } catch {
    _allNotifs = [];
    toast("Erreur", "Impossible de charger les notifications", "error");
  }

  if (loading) loading.style.display = "none";
  renderNotifications();

  // Update stats
  const status = await refreshStatus();
  if (status) {
    const u = $("#stat-unread");
    const t = $("#stat-total");
    const s = $("#stat-sources");
    if (u) u.textContent = status.unread_count;
    if (t) t.textContent = status.notifications_count;
    if (s) s.textContent = status.sources_count;
  }
}

function renderNotifications() {
  const list   = $("#notifications-list");
  const empty  = $("#empty-state");
  if (!list) return;

  let filtered = _allNotifs;
  if (_currentFilter === "unread")  filtered = _allNotifs.filter(n => !n.read);
  if (_currentFilter === "high")    filtered = _allNotifs.filter(n => (n.score || 0) >= 8);

  list.innerHTML = "";

  if (filtered.length === 0) {
    if (empty) empty.style.display = "block";
    return;
  }
  if (empty) empty.style.display = "none";

  const tpl = $("#notif-template");
  filtered.forEach(n => {
    const node = tpl.content.cloneNode(true);
    const card = node.querySelector(".notif-card");
    card.dataset.id = n.id;
    card.classList.add(n.read ? "read" : "unread");

    node.querySelector(".notif-source").textContent = n.source_name || "Source";
    node.querySelector(".notif-time").textContent   = timeAgo(n.timestamp);
    node.querySelector(".notif-title").textContent  = n.title;
    node.querySelector(".notif-summary").textContent = n.summary;

    const reasonEl = node.querySelector(".notif-reason");
    if (n.reason) {
      reasonEl.textContent = `💡 ${n.reason}`;
    } else {
      reasonEl.remove();
    }

    const badge = node.querySelector(".notif-score-badge");
    badge.textContent = `Score ${n.score}/10`;
    badge.classList.add(scoreClass(n.score || 0));

    const link = node.querySelector(".notif-link");
    if (n.link) {
      link.href = n.link;
    } else {
      link.style.display = "none";
    }

    node.querySelector(".notif-read-btn")?.addEventListener("click", () => markRead(n.id));
    node.querySelector(".notif-delete-btn")?.addEventListener("click", () => deleteNotif(n.id));

    list.appendChild(node);
  });

  // Update stats counters
  const unread = _allNotifs.filter(n => !n.read).length;
  const u = $("#stat-unread");
  const t = $("#stat-total");
  if (u) u.textContent = unread;
  if (t) t.textContent = _allNotifs.length;
  updateNavBadge(unread);
}

async function markRead(id) {
  await fetch(`/api/notifications/${id}/read`, { method: "POST" });
  const n = _allNotifs.find(n => n.id === id);
  if (n) n.read = true;
  renderNotifications();
  refreshStatus();
}

async function deleteNotif(id) {
  await fetch(`/api/notifications/${id}`, { method: "DELETE" });
  _allNotifs = _allNotifs.filter(n => n.id !== id);
  renderNotifications();
  refreshStatus();
}

// ===========================================================
// Settings page
// ===========================================================

async function initSettings() {
  initSocket();
  refreshStatus();
  await loadSettingsForm();
  await loadSources();

  // Settings form submit
  $("#settings-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd   = new FormData(e.target);
    const body = {};
    for (const [k, v] of fd.entries()) body[k] = v;
    body.check_interval = parseInt(body.check_interval, 10);

    try {
      const res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.ok) {
        toast("Paramètres enregistrés", "", "success");
        refreshStatus();
      }
    } catch {
      toast("Erreur", "Impossible d'enregistrer les paramètres", "error");
    }
  });

  // Add source form
  $("#add-source-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name     = $("#src-name").value.trim();
    const type     = $("#src-type").value;
    const url      = $("#src-url").value.trim();
    const kwRaw    = $("#src-keywords").value.trim();
    const keywords = kwRaw ? kwRaw.split(",").map(k => k.trim()).filter(Boolean) : [];

    if (!name || !url) {
      toast("Champs requis", "Remplissez le nom et l'URL", "error");
      return;
    }

    try {
      const res = await fetch("/api/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, type, url, keywords }),
      });
      if (res.ok) {
        e.target.reset();
        toast("Source ajoutée ✓", name, "success");
        await loadSources();
        refreshStatus();
      }
    } catch {
      toast("Erreur", "Impossible d'ajouter la source", "error");
    }
  });
}

async function loadSettingsForm() {
  try {
    const res  = await fetch("/api/settings");
    const data = await res.json();

    const apiInput = $("#api-key");
    if (apiInput && data.openai_api_key_set) {
      apiInput.placeholder = "Clé déjà configurée – saisissez pour modifier";
    }

    const modelSel = $("#model");
    if (modelSel && data.model) {
      modelSel.value = data.model;
    }
    const intervalSel = $("#interval");
    if (intervalSel && data.check_interval) {
      intervalSel.value = String(data.check_interval);
    }
    const langSel = $("#language");
    if (langSel && data.language) {
      langSel.value = data.language;
    }
  } catch { /* ignore */ }
}

async function loadSources() {
  const list  = $("#sources-list");
  const empty = $("#sources-empty");
  if (!list) return;
  list.innerHTML = "";

  let sources = [];
  try {
    const res = await fetch("/api/sources");
    sources = await res.json();
  } catch { /* ignore */ }

  if (sources.length === 0) {
    if (empty) empty.style.display = "block";
    return;
  }
  if (empty) empty.style.display = "none";

  const tpl = $("#source-template");
  sources.forEach(s => {
    const node = tpl.content.cloneNode(true);
    const item = node.querySelector(".source-item");
    item.dataset.id = s.id;

    const badge = node.querySelector(".source-type-badge");
    badge.textContent = s.type === "rss" ? "RSS" : "Web";
    badge.classList.add(s.type === "rss" ? "type-rss" : "type-webpage");

    node.querySelector(".source-name").textContent = s.name;
    node.querySelector(".source-url").textContent  = s.url;

    const kwEl = node.querySelector(".source-keywords");
    if (s.keywords && s.keywords.length) {
      kwEl.textContent = `🏷️ ${s.keywords.join(", ")}`;
    } else {
      kwEl.remove();
    }

    node.querySelector(".source-delete-btn")?.addEventListener("click", () => deleteSource(s.id));

    list.appendChild(node);
  });
}

async function deleteSource(id) {
  await fetch(`/api/sources/${id}`, { method: "DELETE" });
  toast("Source supprimée", "", "info");
  await loadSources();
  refreshStatus();
}
