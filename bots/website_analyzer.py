"""
WEBSITE ANALYZER BOT

What it does:
  1. Crawls your target website (thecapx.in)
  2. Extracts: services offered, target audience, key pages, keywords
  3. Saves the analysis to the database
  4. All other bots read this analysis to understand your site

Run schedule: Every 24 hours (via GitHub Actions)
State saved:  services, keywords, audience, pages list
"""

import re
import time
import json
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bots.base_bot import BaseBot


class WebsiteAnalyzerBot(BaseBot):

    def __init__(self):
        super().__init__("website_analyzer")
        self.visited_urls: set = set()
        self.all_text: list   = []
        self.all_pages: list  = []

    # ─────────────────────────────────────────────────────────────
    #  Main logic
    # ─────────────────────────────────────────────────────────────

    def run(self):
        self.log.info(f"Analyzing site: {self.target_site}")

        # Resume if we were interrupted mid-crawl
        cp = self.resume("crawl_progress")
        start_urls = cp.get("remaining_urls", [self.target_site]) if cp else [self.target_site]

        # ── Step 1: Crawl the site ────────────────────────────────
        self.checkpoint("crawl_progress", {"remaining_urls": start_urls})
        self._crawl(start_urls, max_pages=30)
        self.log.info(f"Crawled {len(self.all_pages)} pages.")

        # ── Step 2: Extract services & keywords ──────────────────
        self.checkpoint("before_analysis", {"page_count": len(self.all_pages)})
        analysis = self._analyze_with_ai()

        # ── Step 3: Save everything ───────────────────────────────
        self.save("site_analysis",      analysis)
        self.save("all_pages",          self.all_pages)
        self.save("all_text_combined",  " ".join(self.all_text)[:50000])  # cap size
        self.save("last_crawl_time",    __import__("datetime").datetime.utcnow().isoformat())

        # Also write to config.json so other bots see it immediately
        self._update_config_description(analysis)

        self.log.info("✅ Analysis complete.")
        self._print_summary(analysis)

    # ─────────────────────────────────────────────────────────────
    #  Crawler
    # ─────────────────────────────────────────────────────────────

    def _crawl(self, start_urls: list, max_pages: int = 30):
        queue = list(start_urls)
        base_domain = urlparse(self.target_site).netloc

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; CapXBot/1.0; +https://www.thecapx.in)"
        }

        while queue and len(self.all_pages) < max_pages:
            url = queue.pop(0)
            if url in self.visited_urls:
                continue
            self.visited_urls.add(url)

            try:
                self.log.debug(f"Fetching: {url}")
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                # Extract page text (remove nav/footer noise)
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                text = soup.get_text(separator=" ", strip=True)
                text = re.sub(r"\s+", " ", text).strip()

                if len(text) > 100:   # skip near-empty pages
                    self.all_pages.append({"url": url, "title": soup.title.string if soup.title else url, "text": text[:3000]})
                    self.all_text.append(text)

                # Collect internal links
                for a in soup.find_all("a", href=True):
                    href = urljoin(url, a["href"])
                    parsed = urlparse(href)
                    if parsed.netloc == base_domain and href not in self.visited_urls:
                        queue.append(href)

                time.sleep(0.5)   # be polite — don't overload the server

            except Exception as e:
                self.log.warning(f"Could not fetch {url}: {e}")

    # ─────────────────────────────────────────────────────────────
    #  AI Analysis
    # ─────────────────────────────────────────────────────────────

    def _analyze_with_ai(self) -> dict:
        combined_text = " ".join(self.all_text)[:8000]

        prompt = f"""You are a digital marketing analyst.

Analyze the following website content from {self.target_site} and extract:

1. SERVICES — List every service or product offered (be specific)
2. TARGET_AUDIENCE — Who are the users? (demographics, job types, needs)
3. KEYWORDS — Top 20 SEO keywords this site should rank for
4. UNIQUE_VALUE — What makes this site special?
5. CONTENT_GAPS — 5 blog topics that would drive traffic to this site
6. AD_ANGLES — 5 compelling angles for ads targeting new users

Website content:
---
{combined_text}
---

Respond ONLY with valid JSON in this exact format:
{{
  "services": ["service1", "service2", ...],
  "target_audience": ["audience1", "audience2", ...],
  "keywords": ["keyword1", "keyword2", ...],
  "unique_value": "one paragraph",
  "content_gaps": ["topic1", "topic2", "topic3", "topic4", "topic5"],
  "ad_angles": ["angle1", "angle2", "angle3", "angle4", "angle5"]
}}"""

        for attempt in range(3):
            try:
                raw = self.ask_ai(prompt, max_tokens=2000)
                # Strip markdown code fences if present
                raw = re.sub(r"^```json\s*", "", raw.strip())
                raw = re.sub(r"```\s*$", "", raw.strip())
                return json.loads(raw)
            except Exception as e:
                self.log.warning(f"AI analysis attempt {attempt+1} failed: {e}")
                time.sleep(5)

        # Fallback: return basic structure if AI fails
        return {
            "services": ["See website"],
            "target_audience": ["General users"],
            "keywords": [self.site_name],
            "unique_value": f"{self.site_name} — multi-service platform",
            "content_gaps": ["How to use this platform", "Benefits", "Guide", "FAQ", "Review"],
            "ad_angles": ["Easy to use", "Free to join", "Trusted platform", "Best deals", "Join now"]
        }

    # ─────────────────────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────────────────────

    def _update_config_description(self, analysis: dict):
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        try:
            with open(config_path) as f:
                cfg = json.load(f)
            cfg["site_description"] = analysis.get("unique_value", "")
            with open(config_path, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            self.log.warning(f"Could not update config.json: {e}")

    def _print_summary(self, analysis: dict):
        self.log.info("─── Site Analysis Summary ───────────────────────")
        self.log.info(f"Services:   {', '.join(analysis.get('services', [])[:5])}")
        self.log.info(f"Audience:   {', '.join(analysis.get('target_audience', [])[:3])}")
        self.log.info(f"Keywords:   {', '.join(analysis.get('keywords', [])[:8])}")
        self.log.info(f"Unique Val: {analysis.get('unique_value', '')[:100]}")
        self.log.info("─────────────────────────────────────────────────")


# ── Run directly ──────────────────────────────────────────────────

if __name__ == "__main__":
    bot = WebsiteAnalyzerBot()
    bot.execute()
