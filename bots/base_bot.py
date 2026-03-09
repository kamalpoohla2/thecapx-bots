"""
BASE BOT — Every bot in this system inherits from this class.

Built-in features:
  ✅ Auto-retry  — if a step fails it tries again (up to 3 times)
  ✅ Checkpoints — saves progress before every major step
  ✅ Auto-resume — on restart, picks up from last saved checkpoint
  ✅ Run logging — records every run (success / fail) in the database
  ✅ Crash guard — unhandled exceptions are caught and logged safely

How to create a new bot:
    class MyBot(BaseBot):
        def run(self):
            self.log.info("Doing something...")
            self.checkpoint("started", {"step": 1})
            # ... do the work ...
            self.save("last_run_result", {"data": 123})
"""

import os
import json
import logging
import time
import traceback
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

import state_manager as sm

load_dotenv()

# ─────────────────────────────────────────────────────────────────
#  Shared logger setup (coloured output in terminal)
# ─────────────────────────────────────────────────────────────────

def _setup_logging():
    fmt = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
    try:
        import colorlog
        handler = colorlog.StreamHandler()
        handler.setFormatter(colorlog.ColoredFormatter(
            "%(log_color)s" + fmt,
            log_colors={"DEBUG": "cyan", "INFO": "green",
                        "WARNING": "yellow", "ERROR": "red", "CRITICAL": "bold_red"}
        ))
    except ImportError:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        root.addHandler(handler)


_setup_logging()


# ─────────────────────────────────────────────────────────────────
#  BaseBot
# ─────────────────────────────────────────────────────────────────

class BaseBot(ABC):
    """
    Base class for all bots.
    Subclasses implement the `run()` method with their logic.
    """

    def __init__(self, bot_name: str):
        self.name = bot_name
        self.log = logging.getLogger(bot_name)
        self._run_id: Optional[int] = None

        # Load config.json
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        with open(config_path) as f:
            self.config = json.load(f)

        # Target site (can be overridden with env var for quick site switch)
        self.target_site = os.getenv("TARGET_SITE_URL", self.config["target_site"])
        self.site_name   = os.getenv("SITE_NAME",       self.config["site_name"])

        self.log.info(f"Initialized. Target site: {self.target_site}")

    # ── Abstract method — subclasses must implement ───────────────

    @abstractmethod
    def run(self) -> None:
        """Main logic of the bot. Override this in your subclass."""

    # ── Entry point — call this to run the bot safely ─────────────

    def execute(self) -> bool:
        """
        Runs the bot with full crash protection and logging.
        Returns True if successful, False if it failed.
        """
        self._run_id = sm.log_run_start(self.name)
        self.log.info(f"▶ Starting (run_id={self._run_id})")

        try:
            self.run()
            sm.log_run_end(self._run_id, success=True)
            self.log.info(f"✅ Finished successfully (run_id={self._run_id})")
            return True

        except KeyboardInterrupt:
            self.log.warning("Interrupted by user.")
            sm.log_run_end(self._run_id, success=False, error_msg="KeyboardInterrupt")
            raise

        except Exception as e:
            error = traceback.format_exc()
            self.log.error(f"❌ Crashed:\n{error}")
            sm.log_run_end(self._run_id, success=False, error_msg=str(e))
            self._send_crash_email(str(e))
            return False

    # ── Helper methods available to all bots ─────────────────────

    def checkpoint(self, label: str, data: dict) -> None:
        """Save progress. On restart, load with `resume()`."""
        sm.save_checkpoint(self.name, label, data)

    def resume(self, label: str) -> Optional[dict]:
        """Load last checkpoint. Returns None if this is a fresh start."""
        cp = sm.get_last_checkpoint(self.name, label)
        if cp:
            self.log.info(f"Resuming from checkpoint '{label}': {cp}")
        return cp

    def save(self, key: str, value: Any) -> None:
        """Persist a value (survives crashes and restarts)."""
        sm.set_value(self.name, key, value)

    def load(self, key: str, default: Any = None) -> Any:
        """Load a persisted value (returns `default` if not found)."""
        return sm.get_value(self.name, key, default)

    def already_done(self, item_id: str) -> bool:
        """Check if we already processed this item (prevents duplicates)."""
        done_list = self.load("done_items", [])
        return item_id in done_list

    def mark_done(self, item_id: str) -> None:
        """Mark an item as processed so we skip it next time."""
        done_list = self.load("done_items", [])
        if item_id not in done_list:
            done_list.append(item_id)
            # Keep only last 1000 items to avoid unbounded growth
            if len(done_list) > 1000:
                done_list = done_list[-1000:]
            self.save("done_items", done_list)

    # ── Retry decorator factory ───────────────────────────────────

    @staticmethod
    def with_retry(max_attempts: int = 3, wait_seconds: int = 30):
        """
        Decorator to auto-retry a function on failure.
        Usage:
            @BaseBot.with_retry(max_attempts=3)
            def fetch_data(self):
                ...
        """
        return retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=wait_seconds, max=120),
            before_sleep=before_sleep_log(logging.getLogger(), logging.WARNING),
            reraise=True
        )

    # ── AI helper (switches provider automatically if one fails) ──

    def ask_ai(self, prompt: str, max_tokens: int = 2048) -> str:
        """
        Send a prompt to AI and get a response.
        Tries Gemini first, then Groq as fallback.
        Both are FREE.
        """
        providers = [
            ("gemini",  self._ask_gemini),
            ("groq",    self._ask_groq),
        ]
        last_error = None
        for name, fn in providers:
            try:
                self.log.debug(f"Asking {name}...")
                result = fn(prompt, max_tokens)
                return result
            except Exception as e:
                self.log.warning(f"{name} failed: {e}. Trying next provider.")
                last_error = e
                time.sleep(2)

        raise RuntimeError(f"All AI providers failed. Last error: {last_error}")

    def _ask_gemini(self, prompt: str, max_tokens: int) -> str:
        import google.generativeai as genai
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(self.config["ai"]["primary_model"])
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(max_output_tokens=max_tokens)
        )
        return response.text.strip()

    def _ask_groq(self, prompt: str, max_tokens: int) -> str:
        from groq import Groq
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set")
        client = Groq(api_key=api_key)
        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=self.config["ai"]["fallback_model"],
            max_tokens=max_tokens
        )
        return chat.choices[0].message.content.strip()

    # ── Notification ─────────────────────────────────────────────

    def _send_crash_email(self, error_msg: str) -> None:
        """Send an email if a bot crashes (uses Brevo free tier)."""
        if not self.config.get("notifications", {}).get("email_on_crash"):
            return
        api_key = os.getenv("BREVO_API_KEY", "")
        to_email = os.getenv("NOTIFICATION_EMAIL", "")
        if not api_key or not to_email:
            return
        try:
            import sib_api_v3_sdk
            from sib_api_v3_sdk.rest import ApiException
            config = sib_api_v3_sdk.Configuration()
            config.api_key["api-key"] = api_key
            api = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(config))
            email = sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email": to_email}],
                sender={"name": "CapX Bots", "email": to_email},
                subject=f"⚠️ Bot Crash: {self.name}",
                text_content=f"Bot '{self.name}' crashed.\n\nError:\n{error_msg}"
            )
            api.send_transac_email(email)
            self.log.info("Crash notification email sent.")
        except Exception as e:
            self.log.warning(f"Could not send crash email: {e}")
