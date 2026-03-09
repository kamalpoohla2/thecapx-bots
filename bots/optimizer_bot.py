"""
Optimizer Bot — Phase 4
------------------------
Reads all bot outputs and analytics data to decide:
  1. What's working → do more of it
  2. What's not working → stop or change it
  3. Adjusts config (articles/day, target topics, platform weights)
  4. Generates a weekly performance summary report

This is the "brain" that makes the whole system smarter over time.
"""

import os
import json
from datetime import datetime
from bots.base_bot import BaseBot


class OptimizerBot(BaseBot):
    name = "optimizer"

    def run(self):
        self.log("🧠 Optimizer Bot starting...")

        # ── Gather all performance data ─────────────────────────────
        data = self._gather_performance_data()

        # ── Ask AI for optimization recommendations ─────────────────
        recommendations = self._generate_recommendations(data)

        # ── Apply safe automatic optimizations ─────────────────────
        applied = self._apply_optimizations(recommendations)

        # ── Save weekly report ──────────────────────────────────────
        report = {
            "generated_at":    datetime.utcnow().isoformat(),
            "performance_data": data,
            "recommendations":  recommendations,
            "applied":          applied,
        }
        self.state.set_value("optimizer_report", json.dumps(report))
        self.log(f"✅ Optimizer: {len(applied)} optimizations applied")
        return report

    # ── Gather data ──────────────────────────────────────────────────
    def _gather_performance_data(self) -> dict:
        """Collect metrics from all other bots."""
        # Analytics
        analytics_raw = self.state.get_value("analytics_report") or "{}"
        try:
            analytics = json.loads(analytics_raw)
        except Exception:
            analytics = {}

        # Content generator stats
        published_raw = self.state.get_value("published_articles") or "[]"
        try:
            published_articles = json.loads(published_raw)
        except Exception:
            published_articles = []

        # Pending articles
        pending_raw = self.state.get_value("pending_articles") or "[]"
        try:
            pending_articles = json.loads(pending_raw)
        except Exception:
            pending_articles = []

        # Social media posts
        social_raw = self.state.get_value("published_social_posts") or "[]"
        try:
            social_posts = json.loads(social_raw)
        except Exception:
            social_posts = []

        # Ad performance
        ads_raw = self.state.get_value("pending_ads") or "[]"
        try:
            ads = json.loads(ads_raw)
        except Exception:
            ads = []

        published_ads = [a for a in ads if a.get("status") == "published"]
        pending_ads   = [a for a in ads if a.get("status") == "pending_approval"]

        # Config
        config = self.load_config()

        return {
            "articles_published_total": len(published_articles),
            "articles_pending":         len(pending_articles),
            "articles_per_day_setting": config.get("bots", {}).get("content_generator", {}).get("articles_per_day", 3),
            "social_posts_total":       len(social_posts),
            "social_platforms_active":  list(set(p.get("platform") for p in social_posts)),
            "ads_published":            len(published_ads),
            "ads_pending_approval":     len(pending_ads),
            "analytics_sessions":       analytics.get("total_sessions", 0),
            "analytics_top_pages":      analytics.get("top_pages", [])[:3],
            "ai_insights":              analytics.get("ai_insights", {}),
            "content_strategy":         json.loads(self.state.get_value("content_strategy") or "{}"),
            "config_articles_per_day":  config.get("bots", {}).get("content_generator", {}).get("articles_per_day", 3),
        }

    # ── Generate AI recommendations ──────────────────────────────────
    def _generate_recommendations(self, data: dict) -> list:
        """Ask AI what changes would most improve performance."""
        config    = self.load_config()
        site_name = config.get("site_name", "")
        site_url  = config.get("target_site_url", "")

        prompt = f"""
You are a growth optimizer for {site_name} ({site_url}).

Current performance:
- Articles published: {data['articles_published_total']}
- Articles per day: {data['articles_per_day_setting']}
- Social posts: {data['social_posts_total']} across {data['social_platforms_active']}
- Ads live: {data['ads_published']} (pending approval: {data['ads_pending_approval']})
- Traffic sessions: {data['analytics_sessions']}
- AI insights: {json.dumps(data['ai_insights'], indent=2)}

Based on this data, provide 3-5 specific, actionable optimization recommendations.

For each recommendation, specify:
- action: what to change (e.g. "increase_articles_per_day", "focus_topic_shift", "add_platform")
- value: the new value or specific change
- reason: why this will improve performance
- priority: "high", "medium", or "low"
- auto_apply: true if safe to apply automatically, false if needs human review

Return ONLY a JSON array:
[
  {{
    "action": "...",
    "value": "...",
    "reason": "...",
    "priority": "high",
    "auto_apply": true
  }}
]
"""
        try:
            raw = self.ask_ai(prompt)
            start = raw.find("[")
            end   = raw.rfind("]") + 1
            return json.loads(raw[start:end]) if start >= 0 else []
        except Exception as e:
            self.log(f"⚠️  Recommendation generation failed: {e}")
            return []

    # ── Apply safe optimizations ─────────────────────────────────────
    def _apply_optimizations(self, recommendations: list) -> list:
        """
        Apply optimizations that are safe to automate.
        High-impact or risky changes are saved for human review.
        """
        config  = self.load_config()
        applied = []

        for rec in recommendations:
            if not rec.get("auto_apply", False):
                self.log(f"📋 Recommendation (needs review): {rec.get('action')} — {rec.get('reason', '')[:80]}")
                continue

            action = rec.get("action", "")
            value  = rec.get("value", "")

            try:
                if action == "increase_articles_per_day":
                    current = config.get("bots", {}).get("content_generator", {}).get("articles_per_day", 3)
                    new_val = min(int(str(value)), 5)  # Cap at 5/day
                    if new_val > current:
                        if "bots" not in config:
                            config["bots"] = {}
                        if "content_generator" not in config["bots"]:
                            config["bots"]["content_generator"] = {}
                        config["bots"]["content_generator"]["articles_per_day"] = new_val
                        self._save_config(config)
                        applied.append({"action": action, "old": current, "new": new_val})
                        self.log(f"⚡ Auto-applied: articles/day {current} → {new_val}")

                elif action == "update_focus_keywords":
                    strategy = json.loads(self.state.get_value("content_strategy") or "{}")
                    strategy["focus_keywords"] = value if isinstance(value, list) else [value]
                    strategy["updated_at"] = datetime.utcnow().isoformat()
                    self.state.set_value("content_strategy", json.dumps(strategy))
                    applied.append({"action": action, "value": value})
                    self.log(f"⚡ Auto-applied: focus keywords updated")

                else:
                    # Unknown action — save for review
                    self.log(f"📋 Unknown action '{action}' — saved for review")

            except Exception as e:
                self.log(f"⚠️  Failed to apply {action}: {e}")

        # Save pending recommendations for dashboard
        pending_recs = [r for r in recommendations if not r.get("auto_apply", False)]
        self.state.set_value("pending_recommendations", json.dumps(pending_recs))

        return applied

    def _save_config(self, config: dict):
        """Save updated config back to config.json."""
        import os
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        with open(os.path.normpath(config_path), "w") as f:
            json.dump(config, f, indent=2)
