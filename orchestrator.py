"""
ORCHESTRATOR — Master controller for all bots.

Commands:
  python orchestrator.py run all          → Run every bot once
  python orchestrator.py run analyze      → Run Website Analyzer only
  python orchestrator.py run content      → Run Content Generator only
  python orchestrator.py run publish      → Run SEO Publisher only
  python orchestrator.py schedule         → Start scheduler (runs bots on their intervals)
  python orchestrator.py status           → Show last run status of all bots
  python orchestrator.py switch <URL>     → ⚡ Switch ALL bots to a new target site

Examples:
  python orchestrator.py run all
  python orchestrator.py switch https://www.mynewsite.com
  python orchestrator.py status
"""

import sys
import os
import json
import signal
import time
import logging
import argparse
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("Orchestrator")

# ─────────────────────────────────────────────────────────────────
#  Bot registry — add new bots here
# ─────────────────────────────────────────────────────────────────

def _load_bots():
    """Import all bot classes. Returns dict of {name: class}."""
    from bots.website_analyzer  import WebsiteAnalyzerBot
    from bots.content_generator import ContentGeneratorBot
    from bots.seo_publisher      import SeoPublisherBot
    from bots.analytics_bot      import AnalyticsBot
    from bots.engagement_bot     import EngagementBot
    from bots.ad_manager_bot     import AdManagerBot
    from bots.social_media_bot   import SocialMediaBot
    from bots.optimizer_bot      import OptimizerBot
    return {
        "analyze":  WebsiteAnalyzerBot,
        "content":  ContentGeneratorBot,
        "publish":  SeoPublisherBot,
        "analytics": AnalyticsBot,
        "engage":   EngagementBot,
        "ads":      AdManagerBot,
        "social":   SocialMediaBot,
        "optimize": OptimizerBot,
    }


# ─────────────────────────────────────────────────────────────────
#  Run command
# ─────────────────────────────────────────────────────────────────

def cmd_run(target: str):
    """Run one or all bots immediately."""
    bots = _load_bots()

    if target == "all":
        targets = list(bots.keys())
    elif target in bots:
        targets = [target]
    else:
        print(f"❌ Unknown bot: '{target}'. Available: {', '.join(bots.keys())}, all")
        sys.exit(1)

    results = {}
    for name in targets:
        log.info(f"\n{'='*50}")
        log.info(f"Running bot: {name}")
        log.info('='*50)
        bot = bots[name]()
        success = bot.execute()
        results[name] = "✅ Success" if success else "❌ Failed"
        time.sleep(1)

    print("\n─── Run Summary ─────────────────────────")
    for name, result in results.items():
        print(f"  {name:20s}  {result}")
    print("─────────────────────────────────────────")


# ─────────────────────────────────────────────────────────────────
#  Schedule command (runs bots on their configured intervals)
# ─────────────────────────────────────────────────────────────────

def cmd_schedule():
    """
    Start the scheduler. Bots run on their configured intervals.
    This is for when you have a server that stays on (e.g. Railway).
    If you're using GitHub Actions, you don't need this.
    """
    import schedule

    log.info("Scheduler started. Press Ctrl+C to stop.")

    bots = _load_bots()
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path) as f:
        config = json.load(f)

    bot_config = config.get("bots", {})

    # Map bot names to schedule keys
    schedule_map = {
        "analyze": "website_analyzer",
        "content": "content_generator",
        "publish": "seo_publisher",
    }

    def make_job(bot_name, bot_class):
        def job():
            log.info(f"Scheduled run: {bot_name}")
            try:
                bot_class().execute()
            except Exception as e:
                log.error(f"Scheduled bot '{bot_name}' crashed: {e}")
        return job

    # Register each bot on its interval
    for name, cls in bots.items():
        cfg_key = schedule_map.get(name, name)
        interval_h = bot_config.get(cfg_key, {}).get("interval_hours", 24)
        if bot_config.get(cfg_key, {}).get("enabled", True):
            schedule.every(interval_h).hours.do(make_job(name, cls))
            log.info(f"  Scheduled '{name}' every {interval_h} hours")

    # Run all bots once immediately on startup
    log.info("Running all bots once on startup...")
    cmd_run("all")

    # Handle graceful shutdown
    def _shutdown(signum, frame):
        log.info("Shutdown signal received. Stopping scheduler...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    # Main loop
    while True:
        schedule.run_pending()
        time.sleep(60)


# ─────────────────────────────────────────────────────────────────
#  Status command
# ─────────────────────────────────────────────────────────────────

def cmd_status():
    """Print last run status of all bots."""
    import state_manager as sm

    runs = sm.get_run_summary()

    print("\n─── Bot Run History (last 20 runs) ──────────────────────────")
    print(f"{'Bot':<25} {'Status':<10} {'Started':<25} {'Error'}")
    print("─" * 80)

    if not runs:
        print("  No runs recorded yet. Run 'python orchestrator.py run all' first.")
    else:
        for r in runs:
            status_icon = "✅" if r["status"] == "success" else ("🔄" if r["status"] == "running" else "❌")
            started = r["started_at"][:19].replace("T", " ") if r["started_at"] else ""
            error   = (r["error_msg"] or "")[:40]
            print(f"  {r['bot_name']:<23} {status_icon} {r['status']:<8} {started:<25} {error}")

    print("─" * 80)

    # Show pending articles count
    pending = len(sm.get_value("content_generator", "pending_articles", []))
    published = sm.get_value("seo_publisher", "last_published", {})
    analysis  = sm.get_value("website_analyzer", "site_analysis", {})

    print(f"\n  Target site:      {os.getenv('TARGET_SITE_URL', 'Not set')}")
    print(f"  Services found:   {len(analysis.get('services', []))}")
    print(f"  Pending articles: {pending}")
    print(f"  Last published:   {published.get('title', 'None')[:50]}")
    print("─" * 80 + "\n")


# ─────────────────────────────────────────────────────────────────
#  Dashboard export command — generates dashboard_data.json
# ─────────────────────────────────────────────────────────────────

def cmd_export_dashboard():
    """
    Generate a self-contained dashboard.html with all bot data embedded.
    Open this single file in any browser — no server, no fetch, no CORS issues.
    """
    import state_manager as sm
    import json, os
    from datetime import datetime

    log = logging.getLogger("Orchestrator")
    log.info("📊 Generating self-contained dashboard.html...")

    # Gather all data
    site_analysis      = sm.get_value("website_analyzer", "site_analysis", {})
    published_articles = sm.get_value("seo_publisher",    "published_articles", [])
    pending_articles   = sm.get_value("content_generator","pending_articles", [])
    analytics_report   = sm.get_value("analytics",        "analytics_report", {})
    content_strategy   = sm.get_value("analytics",        "content_strategy", {})
    pending_ads        = sm.get_value("ad_manager",        "pending_ads", [])
    social_posts       = sm.get_value("social_media",      "published_social_posts", [])
    quora_drafts       = sm.get_value("social_media",      "quora_drafts", [])
    optimizer_report   = sm.get_value("optimizer",         "optimizer_report", {})
    last_crawl         = sm.get_value("website_analyzer",  "last_crawl_time", "")
    recent_runs        = sm.get_run_summary()

    # Published URLs from the published_urls table
    published_urls = []
    try:
        import sqlite3
        db_path = os.path.join(os.path.dirname(__file__), "bot_state.db")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT url, platform, title, published_at FROM published_urls ORDER BY published_at DESC LIMIT 20"
            ).fetchall()
            conn.close()
            published_urls = [dict(r) for r in rows]
    except Exception as e:
        log.warning(f"Could not read published_urls: {e}")

    data = {
        "generated_at":           datetime.utcnow().isoformat(),
        "target_site":            os.getenv("TARGET_SITE_URL", ""),
        "site_name":              os.getenv("SITE_NAME", ""),
        "site_analysis":          site_analysis if isinstance(site_analysis, dict) else {},
        "last_crawl":             last_crawl,
        "articles_generated":     len(pending_articles) + len(published_articles),
        "articles_published":     len(published_articles),
        "pending_ads":            pending_ads if isinstance(pending_ads, list) else [],
        "published_social_posts": social_posts if isinstance(social_posts, list) else [],
        "quora_drafts":           quora_drafts if isinstance(quora_drafts, list) else [],
        "analytics":              analytics_report if isinstance(analytics_report, dict) else {},
        "content_strategy":       content_strategy if isinstance(content_strategy, dict) else {},
        "optimizer_report":       optimizer_report if isinstance(optimizer_report, dict) else {},
        "published_urls":         published_urls,
        "recent_runs":            recent_runs,
        "total_runs":             len(recent_runs),
        "traffic_sessions":       (analytics_report or {}).get("total_sessions", 0),
    }

    # Also write dashboard_data.json (for debugging / future use)
    json_path = os.path.join(os.path.dirname(__file__), "dashboard_data.json")
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    # Read the HTML template
    html_path = os.path.join(os.path.dirname(__file__), "dashboard", "index.html")
    with open(html_path, "r") as f:
        html = f.read()

    # Inject data as a global variable and replace the fetch-based loadStatus
    # with a version that reads from window.DASHBOARD_DATA instead.
    data_json = json.dumps(data, default=str)
    inject_script = f"""
<script>
// ── Embedded data (injected at build time, no fetch needed) ──────
window.DASHBOARD_DATA = {data_json};
</script>"""

    # Patch loadStatus to use embedded data instead of fetch
    old_fetch_block = '''  try {
    const res = await fetch("../dashboard_data.json?" + Date.now());
    if (!res.ok) throw new Error("No data yet");
    const d = await res.json();'''

    new_fetch_block = '''  try {
    const d = window.DASHBOARD_DATA;
    if (!d) throw new Error("No embedded data found");'''

    html = html.replace(old_fetch_block, new_fetch_block)

    # Insert the data script just before </head>
    html = html.replace("</head>", inject_script + "\n</head>")

    # Write the self-contained file
    out_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(out_path, "w") as f:
        f.write(html)

    ads_pending = len([a for a in data['pending_ads'] if a.get('status') == 'pending_approval'])
    log.info(f"✅ dashboard.html written ({os.path.getsize(out_path):,} bytes) — open this file in any browser")
    log.info(f"   Articles: {data['articles_published']} published, {data['articles_generated']} total")
    log.info(f"   Ads pending approval: {ads_pending}")
    log.info(f"   Social posts: {len(data['published_social_posts'])}")
    log.info(f"   Quora drafts: {len(data['quora_drafts'])}")


# ─────────────────────────────────────────────────────────────────
#  ⚡ Switch site command — THE KEY FEATURE
# ─────────────────────────────────────────────────────────────────

def cmd_switch(new_url: str, new_name: str = ""):
    """
    Switch ALL bots to a new target site with ONE command.

    What happens:
      1. Updates config.json with the new URL
      2. Sets the TARGET_SITE_URL environment variable
      3. Clears old site analysis (so bots re-analyze the new site)
      4. Keeps all other state (published articles list, run history)
      5. Immediately runs Website Analyzer on the new site

    Usage:
      python orchestrator.py switch https://www.newsite.com
      python orchestrator.py switch https://www.newsite.com "My New Site"
    """
    import state_manager as sm

    # Validate URL
    if not new_url.startswith("http"):
        new_url = "https://" + new_url

    print(f"\n⚡ SWITCHING TARGET SITE")
    print(f"  Old site: {_current_target()}")
    print(f"  New site: {new_url}")

    # ── 1. Update config.json ─────────────────────────────────────
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path) as f:
        config = json.load(f)

    old_url  = config["target_site"]
    old_name = config["site_name"]

    config["target_site"]      = new_url
    config["site_description"] = "Auto-detected on first run"
    if new_name:
        config["site_name"] = new_name
    else:
        # Guess name from URL
        from urllib.parse import urlparse
        parsed = urlparse(new_url)
        config["site_name"] = parsed.netloc.replace("www.", "").split(".")[0].title()

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"  ✅ config.json updated → site_name: {config['site_name']}")

    # ── 2. Update .env file if it exists ─────────────────────────
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            env_lines = f.readlines()
        new_lines = []
        updated_url  = False
        updated_name = False
        for line in env_lines:
            if line.startswith("TARGET_SITE_URL="):
                new_lines.append(f"TARGET_SITE_URL={new_url}\n")
                updated_url = True
            elif line.startswith("SITE_NAME="):
                new_lines.append(f"SITE_NAME={config['site_name']}\n")
                updated_name = True
            else:
                new_lines.append(line)
        if not updated_url:
            new_lines.append(f"TARGET_SITE_URL={new_url}\n")
        if not updated_name:
            new_lines.append(f"SITE_NAME={config['site_name']}\n")
        with open(env_path, "w") as f:
            f.writelines(new_lines)
        print(f"  ✅ .env updated")

    # ── 3. Clear old site analysis ────────────────────────────────
    sm.clear_bot_state("website_analyzer")
    print(f"  ✅ Old site analysis cleared")

    # Keep a record of the switch
    switches = sm.get_value("orchestrator", "site_switches", [])
    switches.append({
        "from_url":  old_url,
        "to_url":    new_url,
        "switched_at": datetime.now(timezone.utc).isoformat()
    })
    sm.set_value("orchestrator", "site_switches", switches)

    # ── 4. Re-analyze the new site immediately ────────────────────
    print(f"\n  🔍 Running Website Analyzer on new site...")
    os.environ["TARGET_SITE_URL"] = new_url
    os.environ["SITE_NAME"]       = config["site_name"]

    from bots.website_analyzer import WebsiteAnalyzerBot
    bot = WebsiteAnalyzerBot()
    success = bot.execute()

    if success:
        print(f"\n✅ Site switch complete! All bots will now target: {new_url}")
        print(f"   Run 'python orchestrator.py run all' to start generating content.\n")
    else:
        print(f"\n⚠️  Site switch recorded but analyzer failed. Check your internet connection.")
        print(f"   Run 'python orchestrator.py run analyze' to retry.\n")


# ─────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────

def _current_target() -> str:
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    try:
        with open(config_path) as f:
            return json.load(f).get("target_site", "unknown")
    except Exception:
        return "unknown"


# ─────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────

def main():
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="CapX Bot Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run command
    p_run = subparsers.add_parser("run", help="Run a bot")
    p_run.add_argument("target",
                       choices=["all", "analyze", "content", "publish",
                                "analytics", "engage", "ads", "social", "optimize"],
                       help="Which bot to run")

    # schedule command
    subparsers.add_parser("schedule", help="Start the continuous scheduler")

    # status command
    subparsers.add_parser("status", help="Show last run status of all bots")

    # export-dashboard command
    subparsers.add_parser("export-dashboard", help="Generate dashboard_data.json for the web dashboard")

    # switch command
    p_switch = subparsers.add_parser("switch", help="Switch all bots to a new site")
    p_switch.add_argument("url",  help="New target site URL")
    p_switch.add_argument("name", nargs="?", default="", help="Optional site name")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args.target)
    elif args.command == "schedule":
        cmd_schedule()
    elif args.command == "status":
        cmd_status()
    elif args.command == "export-dashboard":
        cmd_export_dashboard()
    elif args.command == "switch":
        cmd_switch(args.url, args.name)


if __name__ == "__main__":
    main()
