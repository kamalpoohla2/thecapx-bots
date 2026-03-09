"""
Engagement Bot — Phase 2
--------------------------
Re-engages website visitors and leads via:
  1. Email newsletters (Brevo free tier: 300 emails/day)
  2. Tracks user engagement signals from analytics

Flow:
  - Pulls latest published articles from state
  - Composes a weekly digest email with top 3 articles
  - Sends via Brevo (free) or logs draft for manual send
  - Never sends duplicate digests (tracks last_digest_sent in state)

Free tier: Brevo — 300 emails/day, unlimited contacts.
"""

import os
import json
from datetime import datetime, timedelta
from bots.base_bot import BaseBot


class EngagementBot(BaseBot):
    name = "engagement"

    def run(self):
        self.log("💌 Engagement Bot starting...")

        # Check if we already sent a digest this week
        last_sent = self.state.get_value("last_digest_sent") or ""
        if last_sent:
            try:
                last_dt = datetime.fromisoformat(last_sent)
                days_since = (datetime.utcnow() - last_dt).days
                if days_since < 6:
                    self.log(f"⏭️  Digest sent {days_since} days ago — skipping (sends weekly)")
                    return {"skipped": True, "reason": "already_sent_this_week"}
            except Exception:
                pass

        # Load recent published articles
        published_raw = self.state.get_value("published_articles") or "[]"
        try:
            published = json.loads(published_raw)
        except Exception:
            published = []

        if not published:
            self.log("⏭️  No published articles yet — skipping digest")
            return {"skipped": True, "reason": "no_articles"}

        # Pick top 3 most recent articles
        recent = sorted(
            published,
            key=lambda x: x.get("published_at", ""),
            reverse=True
        )[:3]

        # Generate digest email content
        config     = self.load_config()
        site_name  = config.get("site_name", os.getenv("SITE_NAME", "Our Site"))
        site_url   = config.get("target_site_url", os.getenv("TARGET_SITE_URL", ""))
        email_body = self._compose_digest(site_name, site_url, recent)

        # Send email
        result = self._send_digest(site_name, email_body)

        # Mark as sent
        self.state.set_value("last_digest_sent", datetime.utcnow().isoformat())
        self.log(f"✅ Engagement digest: {result.get('status', 'done')}")
        return result

    # ── Compose digest ───────────────────────────────────────────────
    def _compose_digest(self, site_name: str, site_url: str, articles: list) -> str:
        """Use AI to write a friendly weekly digest email."""
        articles_text = "\n".join([
            f"- {a.get('title', 'Article')} ({a.get('url', '')})"
            for a in articles
        ])

        prompt = f"""
Write a short, friendly weekly digest email for {site_name} ({site_url}).

Include these 3 articles:
{articles_text}

Requirements:
- Conversational, warm tone (not salesy)
- 150-200 words max
- Subject line on first line starting with "Subject: "
- Brief intro paragraph
- List the 3 articles with a one-line description each
- Short closing with CTA to visit the site
- Plain text format (no HTML tags)
"""
        try:
            return self.ask_ai(prompt)
        except Exception as e:
            # Fallback template
            lines = [f"Subject: 📰 This week on {site_name}\n"]
            lines.append(f"Hi there,\n\nHere are this week's top articles from {site_name}:\n")
            for a in articles:
                lines.append(f"• {a.get('title', 'Article')} — {a.get('url', '')}")
            lines.append(f"\nVisit us at {site_url}\n\nCheers,\nThe {site_name} Team")
            return "\n".join(lines)

    # ── Send via Brevo ───────────────────────────────────────────────
    def _send_digest(self, site_name: str, email_body: str) -> dict:
        """Send digest email via Brevo API (300 emails/day free)."""
        import requests as http

        brevo_key    = os.getenv("BREVO_API_KEY", "")
        from_email   = os.getenv("FROM_EMAIL", "")
        notify_email = os.getenv("NOTIFICATION_EMAIL", "")

        # Parse subject from body
        lines = email_body.strip().split("\n")
        subject = "Weekly Digest"
        body_start = 0
        for i, line in enumerate(lines):
            if line.startswith("Subject:"):
                subject = line.replace("Subject:", "").strip()
                body_start = i + 1
                break
        body = "\n".join(lines[body_start:]).strip()

        # Save draft to state (always, even if sending fails)
        draft = {
            "subject":    subject,
            "body":       body,
            "created_at": datetime.utcnow().isoformat(),
        }
        self.state.set_value("latest_digest_draft", json.dumps(draft))
        self.log(f"📝 Digest draft saved: '{subject}'")

        if not brevo_key or not from_email or not notify_email:
            self.log("ℹ️  BREVO_API_KEY / FROM_EMAIL / NOTIFICATION_EMAIL not set — draft saved only")
            return {"status": "draft_only", "subject": subject}

        # Send via Brevo Transactional Email API
        payload = {
            "sender":  {"name": site_name, "email": from_email},
            "to":      [{"email": notify_email}],
            "subject": subject,
            "textContent": body,
        }
        headers = {
            "accept":       "application/json",
            "content-type": "application/json",
            "api-key":      brevo_key,
        }

        try:
            resp = http.post(
                "https://api.brevo.com/v3/smtp/email",
                json=payload,
                headers=headers,
                timeout=15
            )
            if resp.status_code in (200, 201):
                self.log(f"✉️  Digest email sent to {notify_email}")
                return {"status": "sent", "subject": subject}
            else:
                self.log(f"⚠️  Brevo error {resp.status_code}: {resp.text[:200]}")
                return {"status": "brevo_error", "code": resp.status_code}
        except Exception as e:
            self.log(f"⚠️  Email send failed: {e}")
            return {"status": "error", "error": str(e)}
