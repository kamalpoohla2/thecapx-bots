"""
STATE MANAGER — Persistent storage for all bots.

Every bot saves its progress here before and after each operation.
If the server crashes or restarts, bots load their last saved state
and continue from exactly where they stopped.

Storage:
  • Local:  SQLite file (bot_state.db) — works with zero setup
  • Cloud:  Supabase (free 500MB tier) — used in production
  The system automatically uses Supabase if SUPABASE_URL is set,
  otherwise falls back to local SQLite.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("StateManager")


# ─────────────────────────────────────────────────────────────────
#  SQLite backend (local / zero-config)
# ─────────────────────────────────────────────────────────────────

DB_FILE = os.path.join(os.path.dirname(__file__), "bot_state.db")


def _get_sqlite():
    """Return a SQLite connection (creates file if missing)."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _init_sqlite():
    """Create tables if they don't exist yet."""
    conn = _get_sqlite()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bot_state (
            bot_name    TEXT    NOT NULL,
            key         TEXT    NOT NULL,
            value       TEXT,
            updated_at  TEXT    NOT NULL,
            PRIMARY KEY (bot_name, key)
        );

        CREATE TABLE IF NOT EXISTS checkpoints (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_name    TEXT    NOT NULL,
            label       TEXT    NOT NULL,
            data        TEXT    NOT NULL,
            saved_at    TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bot_runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_name    TEXT    NOT NULL,
            status      TEXT    NOT NULL,   -- running / success / failed
            started_at  TEXT    NOT NULL,
            ended_at    TEXT,
            error_msg   TEXT
        );

        CREATE TABLE IF NOT EXISTS published_urls (
            url         TEXT PRIMARY KEY,
            platform    TEXT NOT NULL,
            title       TEXT,
            published_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────
#  Supabase backend (cloud / production)
# ─────────────────────────────────────────────────────────────────

_supabase_client = None


def _get_supabase():
    """Return Supabase client, or None if not configured."""
    global _supabase_client
    if _supabase_client:
        return _supabase_client
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()
    if url and key:
        try:
            from supabase import create_client
            _supabase_client = create_client(url, key)
            log.info("Connected to Supabase.")
            return _supabase_client
        except Exception as e:
            log.warning(f"Supabase connection failed: {e}. Using SQLite.")
    return None


# ─────────────────────────────────────────────────────────────────
#  Public API  (all bots use ONLY these functions)
# ─────────────────────────────────────────────────────────────────

def set_value(bot_name: str, key: str, value: Any) -> None:
    """
    Save a value for a bot.
    Example:
        set_value("content_generator", "last_topic_index", 7)
    """
    value_str = json.dumps(value)
    now = _now()

    sb = _get_supabase()
    if sb:
        try:
            sb.table("bot_state").upsert({
                "bot_name": bot_name, "key": key,
                "value": value_str, "updated_at": now
            }).execute()
            return
        except Exception as e:
            log.warning(f"Supabase set failed, using SQLite: {e}")

    # Fallback: SQLite
    conn = _get_sqlite()
    conn.execute(
        "INSERT OR REPLACE INTO bot_state (bot_name, key, value, updated_at) VALUES (?,?,?,?)",
        (bot_name, key, value_str, now)
    )
    conn.commit()
    conn.close()


def get_value(bot_name: str, key: str, default: Any = None) -> Any:
    """
    Load a saved value for a bot.
    Returns `default` if not found (first run).
    Example:
        idx = get_value("content_generator", "last_topic_index", 0)
    """
    sb = _get_supabase()
    if sb:
        try:
            res = sb.table("bot_state").select("value") \
                .eq("bot_name", bot_name).eq("key", key).execute()
            if res.data:
                return json.loads(res.data[0]["value"])
            return default
        except Exception as e:
            log.warning(f"Supabase get failed, using SQLite: {e}")

    conn = _get_sqlite()
    row = conn.execute(
        "SELECT value FROM bot_state WHERE bot_name=? AND key=?",
        (bot_name, key)
    ).fetchone()
    conn.close()
    if row:
        return json.loads(row["value"])
    return default


def save_checkpoint(bot_name: str, label: str, data: dict) -> None:
    """
    Save a named checkpoint so the bot can resume after a crash.
    Call this BEFORE starting any important operation.
    Example:
        save_checkpoint("content_generator", "before_publish", {"article_id": 42})
    """
    data_str = json.dumps(data)
    now = _now()

    sb = _get_supabase()
    if sb:
        try:
            sb.table("checkpoints").insert({
                "bot_name": bot_name, "label": label,
                "data": data_str, "saved_at": now
            }).execute()
            return
        except Exception as e:
            log.warning(f"Supabase checkpoint failed, using SQLite: {e}")

    conn = _get_sqlite()
    conn.execute(
        "INSERT INTO checkpoints (bot_name, label, data, saved_at) VALUES (?,?,?,?)",
        (bot_name, label, data_str, now)
    )
    conn.commit()
    conn.close()
    log.debug(f"[{bot_name}] Checkpoint saved: {label}")


def get_last_checkpoint(bot_name: str, label: str) -> Optional[dict]:
    """
    Load the most recent checkpoint for a bot.
    Returns None if no checkpoint exists.
    Example:
        cp = get_last_checkpoint("content_generator", "before_publish")
        if cp:
            resume_from_article(cp["article_id"])
    """
    sb = _get_supabase()
    if sb:
        try:
            res = sb.table("checkpoints").select("data") \
                .eq("bot_name", bot_name).eq("label", label) \
                .order("saved_at", desc=True).limit(1).execute()
            if res.data:
                return json.loads(res.data[0]["data"])
            return None
        except Exception as e:
            log.warning(f"Supabase checkpoint read failed, using SQLite: {e}")

    conn = _get_sqlite()
    row = conn.execute(
        "SELECT data FROM checkpoints WHERE bot_name=? AND label=? ORDER BY saved_at DESC LIMIT 1",
        (bot_name, label)
    ).fetchone()
    conn.close()
    if row:
        return json.loads(row["data"])
    return None


def log_run_start(bot_name: str) -> int:
    """Record that a bot run has started. Returns the run ID."""
    now = _now()
    conn = _get_sqlite()
    cur = conn.execute(
        "INSERT INTO bot_runs (bot_name, status, started_at) VALUES (?,?,?)",
        (bot_name, "running", now)
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def log_run_end(run_id: int, success: bool, error_msg: str = "") -> None:
    """Record that a bot run has finished (success or failure)."""
    status = "success" if success else "failed"
    now = _now()
    conn = _get_sqlite()
    conn.execute(
        "UPDATE bot_runs SET status=?, ended_at=?, error_msg=? WHERE id=?",
        (status, now, error_msg, run_id)
    )
    conn.commit()
    conn.close()


def mark_url_published(url: str, platform: str, title: str = "") -> None:
    """Remember a URL we already published so we don't duplicate it."""
    now = _now()
    conn = _get_sqlite()
    conn.execute(
        "INSERT OR IGNORE INTO published_urls (url, platform, title, published_at) VALUES (?,?,?,?)",
        (url, platform, title, now)
    )
    conn.commit()
    conn.close()


def is_url_published(url: str) -> bool:
    """Check if we already published something at this URL."""
    conn = _get_sqlite()
    row = conn.execute(
        "SELECT 1 FROM published_urls WHERE url=?", (url,)
    ).fetchone()
    conn.close()
    return row is not None


def get_all_state(bot_name: str) -> dict:
    """Return all saved key-value pairs for a bot as a dict."""
    conn = _get_sqlite()
    rows = conn.execute(
        "SELECT key, value FROM bot_state WHERE bot_name=?", (bot_name,)
    ).fetchall()
    conn.close()
    return {r["key"]: json.loads(r["value"]) for r in rows}


def clear_bot_state(bot_name: str) -> None:
    """
    Wipe all saved state for a bot.
    Used when switching to a new target site.
    """
    conn = _get_sqlite()
    conn.execute("DELETE FROM bot_state WHERE bot_name=?", (bot_name,))
    conn.execute("DELETE FROM checkpoints WHERE bot_name=?", (bot_name,))
    conn.commit()
    conn.close()
    log.info(f"Cleared all state for bot: {bot_name}")


def get_run_summary() -> list:
    """Return the last 20 bot runs for the dashboard."""
    conn = _get_sqlite()
    rows = conn.execute(
        "SELECT bot_name, status, started_at, ended_at, error_msg "
        "FROM bot_runs ORDER BY started_at DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Initialise SQLite tables on import
_init_sqlite()
log.debug("StateManager ready.")
