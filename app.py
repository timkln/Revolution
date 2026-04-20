"""
Revolution – AI-powered importance notifier
Main Flask application entry point.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit
from openai import OpenAI

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_FILE = Path(__file__).parent / "data.json"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_MINUTES", "30"))
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "100"))

# ---------------------------------------------------------------------------
# Flask & SocketIO setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

DEFAULT_DATA: dict = {
    "sources": [],        # list of {id, type, name, url, keywords}
    "notifications": [],  # list of {id, source_id, title, summary, importance, timestamp, read}
    "settings": {
        "openai_api_key": "",
        "model": OPENAI_MODEL,
        "check_interval": CHECK_INTERVAL,
        "language": "fr",
    },
}


def load_data() -> dict:
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                stored = json.load(f)
            # merge defaults for any missing keys
            for key, val in DEFAULT_DATA.items():
                stored.setdefault(key, val)
            return stored
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read data file – using defaults")
    return json.loads(json.dumps(DEFAULT_DATA))


def save_data(data: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# AI helpers
# ---------------------------------------------------------------------------

def get_openai_client(api_key: str | None = None) -> OpenAI | None:
    key = api_key or os.getenv("OPENAI_API_KEY", "")
    if not key or key == "your_openai_api_key_here":
        return None
    return OpenAI(api_key=key)


def analyse_importance(client: OpenAI, text: str, keywords: list[str], lang: str = "fr", model: str | None = None) -> dict:
    """
    Ask the AI to evaluate importance and provide a short summary.
    Returns {"important": bool, "score": int 1-10, "summary": str, "reason": str}.
    """
    used_model = model or OPENAI_MODEL
    kw_hint = (
        f"Mots-clés d'intérêt : {', '.join(keywords)}" if keywords else ""
    )
    system_prompt = (
        "Tu es un assistant expert en analyse d'informations. "
        "Pour chaque contenu qu'on te soumet, tu dois évaluer son importance "
        "et fournir un résumé concis. Réponds TOUJOURS en JSON valide avec les "
        "champs : important (booléen), score (entier de 1 à 10), "
        "summary (résumé en 2-3 phrases), reason (explication courte de l'importance)."
    )
    user_prompt = (
        f"{kw_hint}\n\nContenu à analyser :\n{text[:3000]}\n\n"
        "Réponds uniquement en JSON valide."
    )
    try:
        response = client.chat.completions.create(
            model=used_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        result = json.loads(raw)
        result.setdefault("important", result.get("score", 0) >= 7)
        result.setdefault("score", 5)
        result.setdefault("summary", text[:200])
        result.setdefault("reason", "")
        return result
    except Exception as exc:
        logger.error("OpenAI analysis failed: %s", exc)
        return {"important": False, "score": 0, "summary": text[:200], "reason": str(exc)}


# ---------------------------------------------------------------------------
# Content fetchers
# ---------------------------------------------------------------------------

def fetch_rss(url: str) -> list[dict]:
    """Return a list of {title, content, link} items from an RSS feed."""
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:10]:
            content = entry.get("summary", "") or entry.get("content", [{}])[0].get("value", "")
            soup = BeautifulSoup(content, "html.parser")
            items.append({
                "title": entry.get("title", ""),
                "content": soup.get_text(separator=" ", strip=True)[:2000],
                "link": entry.get("link", ""),
            })
        return items
    except Exception as exc:
        logger.error("RSS fetch error (%s): %s", url, exc)
        return []


def fetch_webpage(url: str) -> list[dict]:
    """Return the main text content of a webpage."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Revolution-AI-notifier/1.0)"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        title = soup.title.string if soup.title else url
        return [{"title": title, "content": text[:3000], "link": url}]
    except Exception as exc:
        logger.error("Webpage fetch error (%s): %s", url, exc)
        return []


# ---------------------------------------------------------------------------
# Background check
# ---------------------------------------------------------------------------

_check_lock = threading.Lock()


def run_check() -> None:
    """Fetch all sources, analyse with AI, push new important notifications."""
    if not _check_lock.acquire(blocking=False):
        logger.info("Check already running – skipping")
        return
    try:
        data = load_data()
        api_key = data["settings"].get("openai_api_key") or os.getenv("OPENAI_API_KEY", "")
        client = get_openai_client(api_key)
        if not client:
            logger.warning("No valid OpenAI API key – skipping AI check")
            return

        existing_links = {n.get("link", "") for n in data["notifications"]}
        new_notifications = []
        user_model = data["settings"].get("model") or OPENAI_MODEL

        for source in data["sources"]:
            s_type = source.get("type", "rss")
            url = source.get("url", "")
            keywords = source.get("keywords", [])

            if s_type == "rss":
                items = fetch_rss(url)
            else:
                items = fetch_webpage(url)

            for item in items:
                if item["link"] and item["link"] in existing_links:
                    continue  # already seen

                combined = f"{item['title']}\n\n{item['content']}"
                result = analyse_importance(
                    client, combined, keywords,
                    lang=data["settings"].get("language", "fr"),
                    model=user_model,
                )

                if result.get("important"):
                    notif = {
                        "id": f"{int(time.time() * 1000)}-{len(new_notifications)}",
                        "source_id": source.get("id", ""),
                        "source_name": source.get("name", url),
                        "title": item["title"],
                        "summary": result.get("summary", ""),
                        "reason": result.get("reason", ""),
                        "score": result.get("score", 0),
                        "link": item["link"],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "read": False,
                    }
                    new_notifications.append(notif)
                    existing_links.add(item["link"])

        if new_notifications:
            data["notifications"] = (new_notifications + data["notifications"])[:MAX_HISTORY]
            save_data(data)
            socketio.emit("new_notifications", {"notifications": new_notifications})
            logger.info("Pushed %d new notifications", len(new_notifications))

    finally:
        _check_lock.release()


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(run_check, "interval", minutes=CHECK_INTERVAL, id="check_job")
scheduler.start()


# ---------------------------------------------------------------------------
# Routes – pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/settings")
def settings():
    return render_template("settings.html")


# ---------------------------------------------------------------------------
# Routes – API
# ---------------------------------------------------------------------------

@app.route("/api/notifications")
def api_notifications():
    data = load_data()
    return jsonify(data["notifications"])


@app.route("/api/notifications/<notif_id>/read", methods=["POST"])
def api_mark_read(notif_id: str):
    data = load_data()
    for n in data["notifications"]:
        if n["id"] == notif_id:
            n["read"] = True
            break
    save_data(data)
    return jsonify({"ok": True})


@app.route("/api/notifications/read-all", methods=["POST"])
def api_mark_all_read():
    data = load_data()
    for n in data["notifications"]:
        n["read"] = True
    save_data(data)
    return jsonify({"ok": True})


@app.route("/api/notifications/<notif_id>", methods=["DELETE"])
def api_delete_notification(notif_id: str):
    data = load_data()
    data["notifications"] = [n for n in data["notifications"] if n["id"] != notif_id]
    save_data(data)
    return jsonify({"ok": True})


@app.route("/api/sources", methods=["GET"])
def api_sources():
    data = load_data()
    return jsonify(data["sources"])


@app.route("/api/sources", methods=["POST"])
def api_add_source():
    payload = request.get_json(force=True) or {}
    name = (payload.get("name") or "").strip()
    url = (payload.get("url") or "").strip()
    s_type = payload.get("type", "rss")
    keywords = [k.strip() for k in payload.get("keywords", []) if k.strip()]

    if not name or not url:
        return jsonify({"error": "name and url are required"}), 400

    data = load_data()
    source = {
        "id": str(int(time.time() * 1000)),
        "name": name,
        "url": url,
        "type": s_type,
        "keywords": keywords,
    }
    data["sources"].append(source)
    save_data(data)
    return jsonify(source), 201


@app.route("/api/sources/<source_id>", methods=["DELETE"])
def api_delete_source(source_id: str):
    data = load_data()
    data["sources"] = [s for s in data["sources"] if s["id"] != source_id]
    save_data(data)
    return jsonify({"ok": True})


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    data = load_data()
    settings = dict(data["settings"])
    # mask the API key
    if settings.get("openai_api_key"):
        settings["openai_api_key_set"] = True
        key = settings["openai_api_key"]
        settings["openai_api_key"] = "••••••••" + (key[-4:] if len(key) >= 4 else key)
    else:
        settings["openai_api_key_set"] = False
    return jsonify(settings)


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    payload = request.get_json(force=True) or {}
    data = load_data()
    # only update provided keys
    for key in ("openai_api_key", "model", "check_interval", "language"):
        if key in payload:
            data["settings"][key] = payload[key]
    # reschedule if interval changed
    new_interval = int(data["settings"].get("check_interval", CHECK_INTERVAL))
    scheduler.reschedule_job("check_job", trigger="interval", minutes=new_interval)
    save_data(data)
    return jsonify({"ok": True})


@app.route("/api/check", methods=["POST"])
def api_trigger_check():
    """Manually trigger an AI analysis check."""
    thread = threading.Thread(target=run_check, daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Analyse en cours…"})


@app.route("/api/status")
def api_status():
    data = load_data()
    api_key = data["settings"].get("openai_api_key") or os.getenv("OPENAI_API_KEY", "")
    client = get_openai_client(api_key)
    unread = sum(1 for n in data["notifications"] if not n.get("read"))
    return jsonify({
        "ai_configured": client is not None,
        "sources_count": len(data["sources"]),
        "notifications_count": len(data["notifications"]),
        "unread_count": unread,
    })


# ---------------------------------------------------------------------------
# SocketIO events
# ---------------------------------------------------------------------------

@socketio.on("connect")
def on_connect():
    data = load_data()
    unread = [n for n in data["notifications"] if not n.get("read")]
    emit("init", {"unread_count": len(unread)})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
