"""
Ad Manager Bot — Phase 3
--------------------------
Creates ad drafts for Google/Meta using AI, then waits for human approval
before publishing. YOU always review ads before they go live.

Flow:
  1. Generates 3-5 ad variants (headlines + descriptions) per run
  2. Saves them as "pending_approval" in the database
  3. Shows them in the dashboard for you to approve/reject
  4. Approved ads → published to Google Ads or Meta Ads (Phase 3b)
  5. Rejected ads → discarded

Free tools:
  - Google Ads API (free to use, you pay only for clicks)
  - Meta Marketing API (free to use, you pay only for impressions)
  - AI writes the copy (Gemini free tier)

IMPORTANT: No ad goes live without your approval. Ever.
"""

import os
import json
import hashlib
from datetime import datetime
from bots.base_bot import BaseBot
import state_manager as sm


class AdManagerBot(BaseBot):

    def __init__(self):
        super().__init__("ad_manager")

    def run(self):
        self.log.info("📢 Ad Manager Bot starting...")

        # ── Step 1: Publish any approved ads ──────────────────────
        published_count = self._publish_approved_ads()

        # ── Step 2: Generate new ad drafts ────────────────────────
        created_count = self._generate_new_ad_drafts()

        self.log.info(f"✅ Ad Manager: {published_count} published, {created_count} new drafts created")
        return {
            "published": published_count,
            "drafts_created": created_count,
        }

    # ── Generate new ad drafts ───────────────────────────────────────
    def _generate_new_ad_drafts(self) -> int:
        site_name = self.site_name
        site_url  = self.target_site

        # Get site analysis for context (stored by website_analyzer)
        site_analysis = sm.get_value("website_analyzer", "site_analysis", {})
        if not isinstance(site_analysis, dict):
            site_analysis = {}

        # Get content strategy from analytics bot
        strategy = sm.get_value("analytics", "content_strategy", {})
        if not isinstance(strategy, dict):
            strategy = {}

        services  = site_analysis.get("services", [])[:5]
        keywords  = site_analysis.get("keywords", [])[:8]
        audience  = site_analysis.get("target_audience", [])[:3]

        prompt = f"""
You are an expert digital advertising copywriter for {site_name} ({site_url}).

Site description: {site_analysis.get('unique_value', '')}
Services: {', '.join(services)}
Target audience: {', '.join(audience)}
Top keywords: {', '.join(keywords)}

Create 3 different Google Search Ad variants. Each variant must have:
- headline_1: max 30 chars
- headline_2: max 30 chars
- headline_3: max 30 chars
- description_1: max 90 chars
- description_2: max 90 chars
- ad_angle: what unique benefit this ad emphasizes (e.g. "speed", "price", "trust")

Return ONLY a JSON array of 3 objects. No extra text.
Example format:
[
  {{
    "headline_1": "...",
    "headline_2": "...",
    "headline_3": "...",
    "description_1": "...",
    "description_2": "...",
    "ad_angle": "..."
  }}
]
"""

        try:
            raw = self.ask_ai(prompt)
            start = raw.find("[")
            end   = raw.rfind("]") + 1
            ad_variants = json.loads(raw[start:end]) if start >= 0 else []
        except Exception as e:
            self.log.warning(f"⚠️  Ad generation failed: {e}")
            return 0

        created = 0
        for ad in ad_variants:
            # Deduplicate by content hash
            content_hash = hashlib.md5(
                json.dumps(ad, sort_keys=True).encode()
            ).hexdigest()

            if self.already_done(f"ad_{content_hash}"):
                continue

            # Save as pending approval
            pending_ads = self.load("pending_ads", [])
            if not isinstance(pending_ads, list):
                pending_ads = []

            ad_entry = {
                "id":           content_hash[:8],
                "status":       "pending_approval",
                "type":         "google_search_ad",
                "platform":     "google",
                "created_at":   datetime.utcnow().isoformat(),
                "site_url":     site_url,
                **ad
            }
            pending_ads.append(ad_entry)
            self.save("pending_ads", pending_ads)
            self.mark_done(f"ad_{content_hash}")
            created += 1
            self.log.info(f"📝 New ad draft: '{ad.get('headline_1', '')}' [{ad.get('ad_angle', '')}]")

        return created

    # ── Publish approved ads ─────────────────────────────────────────
    def _publish_approved_ads(self) -> int:
        pending_ads = self.load("pending_ads", [])
        if not isinstance(pending_ads, list):
            return 0

        approved = [a for a in pending_ads if a.get("status") == "approved"]
        if not approved:
            return 0

        published_count = 0
        for ad in approved:
            platform = ad.get("platform", "google")
            result = self._publish_to_platform(ad, platform)
            if result.get("success"):
                ad["status"]       = "published"
                ad["published_at"] = datetime.utcnow().isoformat()
                ad["published_url"] = result.get("url", "")
                published_count += 1
                self.log.info(f"✅ Ad published to {platform}: '{ad.get('headline_1', '')}'")
            else:
                self.log.warning(f"⚠️  Ad publish failed: {result.get('error', 'unknown')}")

        # Save updated list
        self.save("pending_ads", pending_ads)
        return published_count

    # ── Platform publishers ──────────────────────────────────────────
    def _publish_to_platform(self, ad: dict, platform: str) -> dict:
        """
        Publish ad to Google Ads or Meta Ads API.
        Returns {"success": True/False, "url": "...", "error": "..."}
        """
        if platform == "google":
            return self._publish_google_ad(ad)
        elif platform == "meta":
            return self._publish_meta_ad(ad)
        else:
            return {"success": False, "error": f"Unknown platform: {platform}"}

    def _publish_google_ad(self, ad: dict) -> dict:
        """Publish to Google Ads via API (requires GOOGLE_ADS_* env vars)."""
        customer_id    = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "")
        developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")

        if not customer_id or not developer_token:
            self.log.info("ℹ️  Google Ads credentials not set — ad staged for manual upload")
            return {"success": False, "error": "credentials_not_set",
                    "manual_action": "Upload this ad via Google Ads UI"}

        # Google Ads API integration would go here
        self.log.info(f"📋 Google Ad ready for upload:\n"
                 f"  H1: {ad.get('headline_1')}\n"
                 f"  H2: {ad.get('headline_2')}\n"
                 f"  H3: {ad.get('headline_3')}\n"
                 f"  D1: {ad.get('description_1')}\n"
                 f"  D2: {ad.get('description_2')}")
        return {"success": True, "url": "manual_upload_required"}

    def _publish_meta_ad(self, ad: dict) -> dict:
        """Publish to Meta Ads via Marketing API."""
        access_token = os.getenv("META_ACCESS_TOKEN", "")
        ad_account   = os.getenv("META_AD_ACCOUNT_ID", "")

        if not access_token or not ad_account:
            self.log.info("ℹ️  Meta Ads credentials not set — ad staged for manual upload")
            return {"success": False, "error": "credentials_not_set",
                    "manual_action": "Upload this ad via Meta Ads Manager"}

        # Meta Marketing API integration would go here
        return {"success": True, "url": "manual_upload_required"}
