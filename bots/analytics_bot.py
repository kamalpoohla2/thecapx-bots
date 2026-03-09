"""
Analytics Bot — Phase 2
------------------------
Reads Google Analytics GA4 data (or falls back to web scraping) to:
  - Track weekly traffic trends
  - Identify top-performing content
  - Detect traffic sources
  - Generate an insight report saved to state
  - Feed data to content generator (write more of what works)

Free tier: GA4 Data API — 200,000 requests/day free.
Fallback: If GA4 not configured, scrapes public metrics from the site itself.
"""

import os
import json
from datetime import datetime, timedelta
from bots.base_bot import BaseBot
import state_manager as sm


class AnalyticsBot(BaseBot):

    def __init__(self):
        super().__init__("analytics")

    def run(self):
        self.log.info("📊 Analytics Bot starting...")
        target_url = self.target_site

        # ── Try GA4 first ───────────────────────────────────────────
        ga4_key_file = os.getenv("GA4_KEY_FILE", "service_account.json")
        ga4_property  = os.getenv("GA4_PROPERTY_ID", "")

        if ga4_property and os.path.exists(ga4_key_file):
            report = self._fetch_ga4_report(ga4_property, ga4_key_file)
        else:
            self.log.info("ℹ️  GA4 not configured — using lightweight web metrics fallback")
            report = self._lightweight_metrics(target_url)

        # ── Save report to state ────────────────────────────────────
        report["generated_at"] = datetime.utcnow().isoformat()
        self.save("analytics_report", report)
        self.log.info(f"✅ Analytics report saved: {len(report.get('top_pages', []))} pages tracked")

        # ── Feed insights to content generator ─────────────────────
        self._update_content_strategy(report)
        return report

    # ── GA4 ─────────────────────────────────────────────────────────
    def _fetch_ga4_report(self, property_id: str, key_file: str) -> dict:
        """Pull real traffic data from Google Analytics 4 Data API."""
        try:
            from google.analytics.data_v1beta import BetaAnalyticsDataClient
            from google.analytics.data_v1beta.types import (
                RunReportRequest, DateRange, Metric, Dimension, OrderBy
            )
            from google.oauth2 import service_account

            credentials = service_account.Credentials.from_service_account_file(
                key_file,
                scopes=["https://www.googleapis.com/auth/analytics.readonly"]
            )
            client = BetaAnalyticsDataClient(credentials=credentials)

            end_date   = datetime.utcnow().date()
            start_date = end_date - timedelta(days=28)

            request = RunReportRequest(
                property=f"properties/{property_id}",
                date_ranges=[DateRange(
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat()
                )],
                dimensions=[
                    Dimension(name="pagePath"),
                    Dimension(name="sessionDefaultChannelGroup"),
                ],
                metrics=[
                    Metric(name="sessions"),
                    Metric(name="engagedSessions"),
                    Metric(name="bounceRate"),
                    Metric(name="averageSessionDuration"),
                ],
                order_bys=[OrderBy(
                    metric=OrderBy.MetricOrderBy(metric_name="sessions"),
                    desc=True
                )],
                limit=20
            )

            response = client.run_report(request)

            top_pages = []
            for row in response.rows:
                top_pages.append({
                    "path":    row.dimension_values[0].value,
                    "channel": row.dimension_values[1].value,
                    "sessions": int(row.metric_values[0].value),
                    "engaged":  int(row.metric_values[1].value),
                    "bounce":   float(row.metric_values[2].value),
                    "avg_duration": float(row.metric_values[3].value),
                })

            total_sessions = sum(p["sessions"] for p in top_pages)
            self.log.info(f"✅ GA4: {total_sessions} sessions, {len(top_pages)} pages")

            return {
                "source":        "ga4",
                "total_sessions": total_sessions,
                "top_pages":     top_pages[:10],
                "period_days":   28,
            }

        except Exception as e:
            self.log.warning(f"⚠️  GA4 fetch failed: {e} — falling back to lightweight metrics")
            return self._lightweight_metrics("")

    # ── Lightweight fallback ─────────────────────────────────────────
    def _lightweight_metrics(self, target_url: str) -> dict:
        """
        When GA4 is not set up, gather what we can from:
          1. Our own published article URLs (stored in state)
          2. Simple HTTP HEAD requests to check article accessibility
          3. AI-generated traffic estimate based on SEO factors
        """
        import requests as http

        # Get articles we've already published (stored by seo_publisher)
        published = sm.get_value("seo_publisher", "published_articles", [])
        if not isinstance(published, list):
            published = []

        accessible = []
        for article in published[:20]:
            url = article.get("url", "")
            if not url:
                continue
            try:
                r = http.head(url, timeout=5, allow_redirects=True)
                accessible.append({
                    "path":     url,
                    "channel":  article.get("platform", "unknown"),
                    "sessions": 0,   # unknown without GA4
                    "status":   r.status_code,
                    "live":     r.status_code == 200,
                })
            except Exception:
                pass

        # Ask AI for strategic insights without real numbers
        site_analysis = sm.get_value("website_analyzer", "site_analysis", {})
        if not isinstance(site_analysis, dict):
            site_analysis = {}

        prompt = f"""
You are a digital marketing analyst.
Site: {target_url}
Site keywords: {', '.join(site_analysis.get('keywords', [])[:8])}
Published articles: {len(published)} total
Accessible article URLs: {len(accessible)} checked

Based on this, suggest:
1. Top 3 content types that likely drive most traffic for this niche
2. Top 3 traffic source channels to focus on
3. One quick SEO win this site can implement today

Format as JSON:
{{
  "best_content_types": ["...", "...", "..."],
  "top_channels": ["...", "...", "..."],
  "quick_win": "..."
}}
"""
        try:
            raw = self.ask_ai(prompt)
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            insights = json.loads(raw[start:end]) if start >= 0 else {}
        except Exception:
            insights = {}

        return {
            "source":          "lightweight",
            "total_sessions":  0,
            "top_pages":       accessible,
            "period_days":     28,
            "ai_insights":     insights,
            "articles_live":   len([a for a in accessible if a.get("live")]),
            "articles_total":  len(published),
        }

    # ── Update content strategy ──────────────────────────────────────
    def _update_content_strategy(self, report: dict):
        """
        Tell the content generator what's working so it writes
        more of the high-performing content types.
        """
        insights = report.get("ai_insights", {})
        top_pages = report.get("top_pages", [])

        strategy = {
            "focus_content_types": insights.get("best_content_types", []),
            "focus_channels":      insights.get("top_channels", []),
            "quick_win":           insights.get("quick_win", ""),
            "top_performing_paths": [p["path"] for p in top_pages[:5]],
            "updated_at":          datetime.utcnow().isoformat(),
        }

        self.save("content_strategy", strategy)
        self.log.info("📌 Content strategy updated based on analytics")
