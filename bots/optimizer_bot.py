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
import state_manager as sm


class OptimizerBot(BaseBot):

    def __init__(self):
        super().__init__("optimizer")

    def run(self):
        self.log.info("🧠 Optimizer Bot starting...")

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
        self.save("optimizer_report", report)
        self.log.info(f"✅ Optimizer: {len(applied)} optimizations applied")
        return report

    # ── Gather data ──────────────────────────────────────────────────
    def _gather_performance_data(self) -> dict:
        """Collect metrics from all other bots."""
        # Analytics (stored by analytics bot)
        analytics = sm.get_value("analytics", "analytics_report", {})
        if not isinstance(analytics, dict):
            analytics = {}

        # Published articles (stored by seo_publisher)
        published_articles = sm.get_value("seo_publisher", "published_articles", [])
        if not isinstance(published_articles, list):
            published_articles = []

        # Pending articles (stored by content_generator)
        pending_articles = sm.get_value("content_generator", "pending_articles", [])
        if not isinstance(pending_articles, list):
            pending_articles = []

        # Social media posts (stored by social_media bot)
        social_posts = sm.get_value("social_media", "published_social_posts", [])
        if not isinstance(social_posts, list):
            social_posts = []

        # Ad performance (stored by ad_manager bot)
        ads = sm.get_value("ad_manager", "pending_ads", [])
        if not isinstance(ads, list):
            ads = []

        published_ads = [a for a in ads if a.get("status") == "published"]
        pending_ads   = [a for a in ads if a.get("status") == "pending_approval"]

        # Content strategy (stored by analytics bot)
        content_strategy = sm.get_value("analytics", "content_strategy", {})
        if not isinstance(content_strategy, dict):
            content_strategy = {}

        # Config
        config = self.config

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
            "content_strategy":         content_strategy,
            "config_articles_per_day":  config.get("bots", {}).get("content_generator", {}).get("articles_per_day", 3),
        }

    # ── Generate AI recommendations ──────────────────────────────────
    def _generate_recommendations(self, data: dict) -> list:
        """Ask AI what changes would most improve performance."""
        site_name = self.site_name
        site_url  = self.target_site

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
            self.log.warning(f"⚠️  Recommendation generation failed: {e}")
            return []

    # ── Apply safe optimizations ─────────────────────────────────────
    def _apply_optimizations(self, recommendations: list) -> list:
        """
        Apply optimizations that are safe to automate.
        High-impact or risky changes are saved for human review.
        """
        config  = self.config
        applied = []

        for rec in recommendations:
            if not rec.get("auto_apply", False):
                self.log.info(f"📋 Recommendation (needs review): {rec.get('action')} — {rec.get('reason', '')[:80]}")
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
                        self.log.info(f"⚡ Auto-applied: articles/day {current} → {new_val}")

                elif action == "update_focus_keywords":
                    strategy = sm.get_value("analytics", "content_strategy", {})
                    if not isinstance(strategy, dict):
                        strategy = {}
                    strategy["focus_keywords"] = value if isinstance(value, list) else [value]
                    strategy["updated_at"] = datetime.utcnow().isoformat()
                    sm.set_value("analytics", "content_strategy", strategy)
                    applied.append({"action": action, "value": value})
                    self.log.info(f"⚡ Auto-applied: focus keywords updated")

                else:
                    # Unknown action — save for review
                    self.log.info(f"📋 Unknown action '{action}' — saved for review")

            except Exception as e:
                self.log.warning(f"⚠️  Failed to apply {action}: {e}")

        # Save pending recommendations for dashboard
        pending_recs = [r for r in recommendations if not r.get("auto_apply", False)]
        self.save("pending_recommendations", pending_recs)

        return applied

    def _save_config(self, config: dict):
        """Save updated config back to config.json."""
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        with open(os.path.normpath(config_path), "w") as f:
            json.dump(config, f, indent=2)
