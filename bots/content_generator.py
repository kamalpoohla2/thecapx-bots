"""
CONTENT GENERATOR BOT

What it does:
  1. Reads the site analysis from Website Analyzer Bot
  2. Generates SEO blog articles (3 per day) using free Gemini AI
  3. Saves each article to the database, ready for publishing
  4. Never repeats the same topic — tracks all generated content
  5. Rotates through content_gap topics and keyword angles

Run schedule: Every 12 hours (via GitHub Actions)
State saved:  generated_articles, topic_index, done_topics
"""

import json
import time
import re
import hashlib
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bots.base_bot import BaseBot
import state_manager as sm


class ContentGeneratorBot(BaseBot):

    ARTICLES_PER_RUN = 3   # Adjust in config if needed

    def __init__(self):
        super().__init__("content_generator")

    # ─────────────────────────────────────────────────────────────
    #  Main logic
    # ─────────────────────────────────────────────────────────────

    def run(self):
        # Load site analysis (from Website Analyzer Bot)
        analysis = sm.get_value("website_analyzer", "site_analysis")
        if not analysis:
            self.log.warning("No site analysis found. Running Website Analyzer first...")
            from bots.website_analyzer import WebsiteAnalyzerBot
            WebsiteAnalyzerBot().execute()
            analysis = sm.get_value("website_analyzer", "site_analysis")
            if not analysis:
                raise RuntimeError("Cannot generate content without site analysis.")

        services  = analysis.get("services", [])
        keywords  = analysis.get("keywords", [])
        gaps      = analysis.get("content_gaps", [])
        audience  = analysis.get("target_audience", [])

        # Resume from last saved topic index (crash recovery)
        topic_index = self.load("topic_index", 0)
        self.log.info(f"Starting at topic index {topic_index}")

        # Build a pool of topic ideas (never repeat)
        topics = self._build_topic_pool(services, keywords, gaps, audience)
        generated = 0

        for i in range(self.ARTICLES_PER_RUN):
            idx = (topic_index + i) % len(topics)
            topic = topics[idx]
            topic_id = hashlib.md5(topic.encode()).hexdigest()

            # Skip topics we've already written about
            if self.already_done(topic_id):
                self.log.info(f"Topic already done, skipping: {topic}")
                continue

            self.log.info(f"Generating article {i+1}/{self.ARTICLES_PER_RUN}: {topic}")
            self.checkpoint("before_article", {"topic": topic, "index": idx})

            try:
                article = self._generate_article(topic, keywords, audience)
                self._save_article(article)
                self.mark_done(topic_id)
                generated += 1
                self.log.info(f"✅ Article saved: {article['title'][:60]}...")
            except Exception as e:
                self.log.error(f"Failed to generate article for '{topic}': {e}")

            # Save progress after each article (crash recovery)
            self.save("topic_index", idx + 1)
            time.sleep(3)   # Respect free API rate limits

        self.log.info(f"Generated {generated} articles this run.")

    # ─────────────────────────────────────────────────────────────
    #  Topic generation
    # ─────────────────────────────────────────────────────────────

    def _build_topic_pool(self, services, keywords, gaps, audience) -> list:
        """Build a large list of non-repeating article topics."""
        topics = []

        # From content gaps identified by site analysis
        topics.extend(gaps)

        # From services — one article per service
        for svc in services:
            topics.append(f"Complete guide to {svc} on {self.site_name}")
            topics.append(f"How to find the best {svc} near you")
            topics.append(f"Top benefits of using {svc} through {self.site_name}")

        # From keywords
        for kw in keywords[:10]:
            topics.append(f"Everything you need to know about {kw}")
            topics.append(f"Why {kw} matters in {datetime.now().year}")

        # From audience
        for aud in audience:
            topics.append(f"How {self.site_name} helps {aud}")

        # Generic high-traffic topics
        topics += [
            f"How to get started with {self.site_name}",
            f"{self.site_name} review — is it worth it?",
            f"Top 10 tips for using {self.site_name}",
            f"Success stories from {self.site_name} users",
            f"Common mistakes to avoid on {self.site_name}",
        ]

        return topics

    # ─────────────────────────────────────────────────────────────
    #  Article generation
    # ─────────────────────────────────────────────────────────────

    def _generate_article(self, topic: str, keywords: list, audience: list) -> dict:
        kw_str  = ", ".join(keywords[:8])
        aud_str = ", ".join(audience[:3])

        prompt = f"""Write a high-quality, SEO-optimised blog article for the website {self.target_site} ({self.site_name}).

Topic: {topic}
Target audience: {aud_str}
Include these SEO keywords naturally: {kw_str}

Requirements:
- Length: 800–1200 words
- Format: Markdown (use ## headings, bullet points where helpful)
- Tone: Friendly, helpful, professional
- Include: Introduction, 4–6 sections with headings, conclusion with CTA
- CTA (call to action): Direct readers to visit {self.target_site}
- Never use filler phrases like "In conclusion" or "As we can see"
- Start with a compelling first sentence that hooks the reader

Return ONLY the article in Markdown. No preamble, no explanation.
Start with the title on the first line as a # heading."""

        raw = self.ask_ai(prompt, max_tokens=2000)

        # Extract title from first line
        lines = raw.strip().split("\n")
        title = lines[0].lstrip("# ").strip() if lines else topic

        # Generate SEO meta description
        meta_prompt = f"""Write a 155-character SEO meta description for this article about "{topic}" for the website {self.site_name} ({self.target_site}).
Return ONLY the meta description, nothing else."""
        meta_desc = self.ask_ai(meta_prompt, max_tokens=200)[:155]

        return {
            "title":        title,
            "topic":        topic,
            "body":         raw,
            "meta_desc":    meta_desc,
            "keywords":     keywords[:8],
            "site":         self.target_site,
            "created_at":   datetime.now(timezone.utc).isoformat(),
            "published":    False,
            "word_count":   len(raw.split())
        }

    # ─────────────────────────────────────────────────────────────
    #  Storage
    # ─────────────────────────────────────────────────────────────

    def _save_article(self, article: dict):
        """Save article to database for the Publisher bot to pick up."""
        articles = self.load("pending_articles", [])
        articles.append(article)
        # Keep last 50 pending articles
        if len(articles) > 50:
            articles = articles[-50:]
        self.save("pending_articles", articles)

    @staticmethod
    def get_pending_articles() -> list:
        """Called by Publisher bot to get articles ready to publish."""
        return sm.get_value("content_generator", "pending_articles", [])

    @staticmethod
    def mark_article_published(title: str):
        """Remove an article from the pending list after publishing."""
        articles = sm.get_value("content_generator", "pending_articles", [])
        articles = [a for a in articles if a["title"] != title]
        sm.set_value("content_generator", "pending_articles", articles)


# ── Run directly ──────────────────────────────────────────────────

if __name__ == "__main__":
    bot = ContentGeneratorBot()
    bot.execute()
