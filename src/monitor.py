import schedule
import time
import threading
import httpx
from bs4 import BeautifulSoup
from plyer import notification
from datetime import datetime
import re

import osint_helper

PRICE_RE = re.compile(r'\$?\s?\d[\d,]*(?:\.\d{2})?')

class Watchdog:
    def __init__(self, db_manager):
        self.db = db_manager
        self.is_running = False
        self.thread = None
        self.lock = threading.Lock()

    def start(self):
        if self.is_running: return
        self.is_running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.is_running = False

    def _loop(self):
        # Check every 1 minute if a watch item is due (simulated cron)
        # In a real app, schedule.every()... would be better, but we need to iterate dynamic list from DB
        while self.is_running:
            self._check_watchlist()
            for _ in range(60): # Sleep 60s but check stop flag
                if not self.is_running: break
                time.sleep(1)

    def _check_watchlist(self):
        # Fetch all active items
        items = self.db.get_watchlist() # id, url, kw, target_price, mode, last_check, status
        
        for item in items:
            item_id, url, keyword, target, mode, last_check, status = item
            if status != "active": continue
            
            # Simple check frequency logic: every 1 hour (hardcoded for MVP)
            # In production, add 'frequency' column
            last_dt = datetime.fromisoformat(last_check)
            if (datetime.now() - last_dt).total_seconds() < 3600:
                continue

            try:
                self._process_item(item)
                self.db.update_watch_timestamp(item_id)
            except Exception as e:
                print(f"Watchdog Error on {url}: {e}")

    def _process_item(self, item):
        item_id, url, keyword, target, mode, last_check, status = item
        
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20, follow_redirects=True)
        soup = BeautifulSoup(resp.text, 'html.parser')
        text = self._extract_visible_text(soup)
        meta_text = self._extract_meta_text(soup)
        combined = " ".join(t for t in [text, meta_text] if t)

        notify = False
        msg = ""

        if mode == "keyword":
            patterns = osint_helper.build_keyword_patterns(keyword)
            if osint_helper.match_any(combined, patterns):
                notify = True
                snippet = ""
                if match := osint_helper.find_first_match(combined, patterns):
                    snippet = self._snippet_from_match(combined, match)
                if snippet:
                    msg = f"Keyword '{keyword}' found: {snippet}"
                else:
                    msg = f"Keyword '{keyword}' found on page!"
        
        elif mode == "price":
            # Extract first price found (naive)
            match = PRICE_RE.search(text)
            if match:
                price_str = match.group(0).replace("$", "").replace(",", "")
                price = float(price_str)
                if price <= float(target):
                    notify = True
                    msg = f"Price drop! Found ${price} (Target: ${target})"

        if notify:
            self._send_notification("Gemini Watchdog", f"{msg}\n{url}")

    def _extract_visible_text(self, soup):
        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()
        return " ".join(soup.stripped_strings)

    def _extract_meta_text(self, soup):
        parts = []
        if soup.title and soup.title.get_text(strip=True):
            parts.append(soup.title.get_text(" ", strip=True))
        for tag in soup.find_all("meta"):
            key = tag.get("name") or tag.get("property") or tag.get("http-equiv")
            content = tag.get("content")
            if not key or not content:
                continue
            key = key.strip().lower()
            if key in {"description", "keywords", "author", "generator", "robots"} or key.startswith(("og:", "twitter:")):
                parts.append(content.strip())
        return " ".join(parts)

    def _snippet_from_match(self, text, match, radius=80):
        if not text or not match:
            return ""
        start = max(0, match.start() - radius)
        end = min(len(text), match.end() + radius)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = f"...{snippet}"
        if end < len(text):
            snippet = f"{snippet}..."
        return snippet

    def _send_notification(self, title, message):
        try:
            notification.notify(
                title=title,
                message=message,
                app_name='Gemini Scraper',
                timeout=10
            )
        except Exception:
            print(f"NOTIFICATION: {title} - {message}")
