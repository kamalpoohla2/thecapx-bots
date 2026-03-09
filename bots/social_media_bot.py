"""
Social Media Bot — Phase 4
----------------------------
Automatically posts content to Reddit, Quora, and LinkedIn
to drive organic traffic back to thecapx.in.

Strategy per platform:
  - Reddit:   Post helpful discussions in relevant subreddits (not spammy)
  - Quora:    Answer questions related to our keywords with value + link
  - LinkedIn: Post professional insights with article links

Free tools:
  - Reddit API (free, PRAW library)
  - Quora: No official API → uses Selenium/browser automation (manual for now)
  - LinkedIn API (free, 100 API calls/day)

Anti-spam safety:
  - Never posts more than 1x per subreddit per 48 hours
  - Adds genuine value before linking
  - Tracks all posts to avoid duplicates
"""

import os
import json
import hashlib
from datetime import datetime, timedelta
from bots.base_bot import BaseBot


class SocialMediaBot(BaseBot):
    name = "social_media"

    def run(self):
        self.log("📱 Social Media Bot starting...")
        config = self.load_config()

        results = {}

        # ── Reddit ──────────────────────────────────────────────────
        reddit_client_id = os.getenv("REDDIT_CLIENT_ID", "")
        if reddit_client_id:
            results["reddit"] = self._post_to_reddit(config)
        else:
            self.log("ℹ️  Reddit credentials not set — skipping")
            results["reddit"] = {"skipped": True}

        # ── LinkedIn ────────────────────────────────────────────────
        linkedin_token = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
        if linkedin_token:
            results["linkedin"] = self._post_to_linkedin(config)
        else:
            self.log("ℹ️  LinkedIn token not set — skipping")
            results["linkedin"] = {"skipped": True}

        # ── Generate Quora answer drafts (manual posting) ────────────
        results["quora_drafts"] = self._generate_quora_drafts(config)

        self.log(f"✅ Social Media Bot done: {results}")
        return results

    # ── Reddit ───────────────────────────────────────────────────────
    def _post_to_reddit(self, config: dict) -> dict:
        """Post a helpful discussion to relevant subreddits."""
        try:
            import praw
        except ImportError:
            self.log("⚠️  praw not installed — run: pip install praw")
            return {"error": "praw_not_installed"}

        # Get site analysis to find relevant subreddits
        site_analysis_raw = self.state.get_value("site_analysis") or "{}"
        try:
            site_analysis = json.loads(site_analysis_raw)
        except Exception:
            site_analysis = {}

        keywords = site_analysis.get("keywords", [])[:5]
        services = site_analysis.get("services", [])[:3]
        site_url = config.get("target_site_url", "")
        site_name = config.get("site_name", "")

        # Generate subreddit suggestions and post content using AI
        prompt = f"""
Given a site about: {', '.join(services)}
Target keywords: {', '.join(keywords)}

Suggest 3 relevant subreddits (without r/ prefix) where this content would fit.
Then write one Reddit post (title + body) that provides genuine value to that community.
The post should NOT be spammy — it should answer a real question and naturally mention {site_name} at the end only if truly relevant.

Return JSON:
{{
  "subreddits": ["sub1", "sub2", "sub3"],
  "title": "...",
  "body": "...(250-400 words, helpful, not promotional)..."
}}
"""
        try:
            raw = self.ask_ai(prompt)
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            post_data = json.loads(raw[start:end]) if start >= 0 else {}
        except Exception as e:
            self.log(f"⚠️  Reddit post generation failed: {e}")
            return {"error": str(e)}

        subreddits = post_data.get("subreddits", [])
        title      = post_data.get("title", "")
        body       = post_data.get("body", "")

        if not subreddits or not title:
            return {"error": "no_content_generated"}

        # Connect to Reddit
        try:
            reddit = praw.Reddit(
                client_id=os.getenv("REDDIT_CLIENT_ID"),
                client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
                username=os.getenv("REDDIT_USERNAME"),
                password=os.getenv("REDDIT_PASSWORD"),
                user_agent=f"{site_name} content bot v1.0",
            )
        except Exception as e:
            return {"error": f"reddit_auth_failed: {e}"}

        posted = []
        for subreddit_name in subreddits[:1]:  # Post to 1 subreddit at a time
            # Check cooldown (48 hours per subreddit)
            cooldown_key = f"reddit_posted_{subreddit_name}"
            last_posted  = self.state.get_value(cooldown_key) or ""
            if last_posted:
                try:
                    last_dt = datetime.fromisoformat(last_posted)
                    if (datetime.utcnow() - last_dt).total_seconds() < 48 * 3600:
                        self.log(f"⏭️  r/{subreddit_name} cooldown active — skipping")
                        continue
                except Exception:
                    pass

            try:
                subreddit   = reddit.subreddit(subreddit_name)
                submission  = subreddit.submit(title, selftext=body)
                post_url    = f"https://reddit.com{submission.permalink}"

                self.state.set_value(cooldown_key, datetime.utcnow().isoformat())
                self._save_published_post("reddit", post_url, title)
                posted.append({"subreddit": subreddit_name, "url": post_url})
                self.log(f"✅ Reddit post: r/{subreddit_name} — {post_url}")

            except Exception as e:
                self.log(f"⚠️  Reddit post to r/{subreddit_name} failed: {e}")

        return {"posted": posted}

    # ── LinkedIn ─────────────────────────────────────────────────────
    def _post_to_linkedin(self, config: dict) -> dict:
        """Post a professional insight to LinkedIn."""
        import requests as http

        token       = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
        person_urn  = os.getenv("LINKEDIN_PERSON_URN", "")  # urn:li:person:XXXXX

        if not person_urn:
            self.log("ℹ️  LINKEDIN_PERSON_URN not set — skipping")
            return {"skipped": True}

        # Get latest published article for reference
        published_raw = self.state.get_value("published_articles") or "[]"
        try:
            published = json.loads(published_raw)
        except Exception:
            published = []

        latest = published[-1] if published else {}
        site_name = config.get("site_name", "")
        site_url  = config.get("target_site_url", "")

        prompt = f"""
Write a short LinkedIn post (150-200 words) for {site_name}.
Professional, insightful tone.

If there's a recent article, reference it:
Article title: {latest.get('title', '')}
Article URL: {latest.get('url', site_url)}

The post should:
- Share a professional insight relevant to the site's niche
- Be genuinely valuable (not just promotional)
- End with a relevant question to encourage engagement
- Include 3-5 relevant hashtags at the end

Return only the post text, nothing else.
"""
        try:
            post_text = self.ask_ai(prompt)
        except Exception as e:
            return {"error": str(e)}

        # LinkedIn Share API v2
        payload = {
            "author": person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": post_text},
                    "shareMediaCategory": "NONE"
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            }
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        try:
            resp = http.post(
                "https://api.linkedin.com/v2/ugcPosts",
                json=payload,
                headers=headers,
                timeout=15
            )
            if resp.status_code in (200, 201):
                post_id  = resp.json().get("id", "")
                post_url = f"https://www.linkedin.com/feed/update/{post_id}"
                self._save_published_post("linkedin", post_url, post_text[:80])
                self.log(f"✅ LinkedIn post published: {post_url}")
                return {"posted": True, "url": post_url}
            else:
                self.log(f"⚠️  LinkedIn error {resp.status_code}: {resp.text[:200]}")
                return {"error": f"linkedin_{resp.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Quora drafts ─────────────────────────────────────────────────
    def _generate_quora_drafts(self, config: dict) -> dict:
        """
        Generate Quora answer drafts. Quora has no public API,
        so drafts are saved for manual posting.
        """
        site_analysis_raw = self.state.get_value("site_analysis") or "{}"
        try:
            site_analysis = json.loads(site_analysis_raw)
        except Exception:
            site_analysis = {}

        keywords  = site_analysis.get("keywords", [])[:5]
        site_name = config.get("site_name", "")
        site_url  = config.get("target_site_url", "")

        prompt = f"""
Generate 3 Quora question-answer pairs for {site_name} ({site_url}).
Topic keywords: {', '.join(keywords)}

Each pair must:
- Be a real question someone would ask on Quora
- Have a detailed, genuinely helpful answer (200-300 words)
- Mention {site_name} naturally at the end only if truly relevant
- Not be obviously promotional

Return JSON array:
[
  {{"question": "...", "answer": "..."}},
  {{"question": "...", "answer": "..."}},
  {{"question": "...", "answer": "..."}}
]
"""
        try:
            raw = self.ask_ai(prompt)
            start = raw.find("[")
            end   = raw.rfind("]") + 1
            drafts = json.loads(raw[start:end]) if start >= 0 else []
        except Exception as e:
            self.log(f"⚠️  Quora draft generation failed: {e}")
            return {"error": str(e)}

        # Save drafts for manual posting
        existing_raw = self.state.get_value("quora_drafts") or "[]"
        try:
            existing = json.loads(existing_raw)
        except Exception:
            existing = []

        new_drafts = []
        for d in drafts:
            d["created_at"] = datetime.utcnow().isoformat()
            d["status"]     = "draft"
            existing.append(d)
            new_drafts.append(d)

        self.state.set_value("quora_drafts", json.dumps(existing[-20:]))  # Keep last 20
        self.log(f"📝 {len(new_drafts)} Quora answer drafts saved (post manually)")
        return {"drafts_created": len(new_drafts)}

    # ── Helpers ──────────────────────────────────────────────────────
    def _save_published_post(self, platform: str, url: str, title: str):
        """Save social post to shared published_social_posts list."""
        posts_raw = self.state.get_value("published_social_posts") or "[]"
        try:
            posts = json.loads(posts_raw)
        except Exception:
            posts = []

        posts.append({
            "platform":     platform,
            "url":          url,
            "title":        title,
            "published_at": datetime.utcnow().isoformat(),
        })
        self.state.set_value("published_social_posts", json.dumps(posts[-50:]))
