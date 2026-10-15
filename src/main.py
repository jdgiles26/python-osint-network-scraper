#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini Scraper v5.0 - Intent-First Edition
Site-wide recursive crawler with Vision AI, smart auto-extraction, and shopping/OSINT focus controls.
"""
import csv
import json
import sys
import threading
import queue
import webbrowser
import re
import warnings
import os
from datetime import datetime
from urllib.parse import urljoin, urlparse
from collections import deque
import time
import ast
from pathlib import Path

try:
    from bs4 import BeautifulSoup
    import httpx
    import ttkbootstrap as ttk
    from ttkbootstrap.constants import *
    from tkinter import filedialog, messagebox, scrolledtext
    import openpyxl
    from PIL import Image

    try:
        from ddgs import DDGS  # new package name
    except ImportError:
        from duckduckgo_search import DDGS  # fallback for older installs
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    
    import ai_helper
    import osint_helper
    from database_manager import DatabaseManager
    from monitor import Watchdog
    import uuid
except ImportError as e:
    print(f"Missing dependency: {e}. Run start.sh to install.", file=sys.stderr)
    sys.exit(1)
# Silence noisy rename warnings from duckduckgo_search
warnings.filterwarnings("ignore", message="This package (`duckduckgo_search`) has been renamed", category=RuntimeWarning)

# --- Configuration ---
DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"}
MAX_OSINT_RESULTS = 20
LOG_STAT_PREFIX = "__STAT__:"
PRICE_RE = re.compile(r'\$?\s?\d[\d,]*(?:\.\d{2})?')
RATING_RE = re.compile(r'([0-5](?:\.\d)?)\s*(?:out of|/)?\s*5', re.IGNORECASE)
SHIPPING_HINTS = re.compile(r'(prime|ship|delivery|arrive|tomorrow|free\s+returns)', re.IGNORECASE)
_QUERY_SPLIT_RE = re.compile(r"[|,]+")
ASSET_EXTS = ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.csv', '.txt', '.json', '.xml', '.zip', '.7z', '.tar', '.gz', '.conf', '.env', '.ini', '.yml', '.yaml', '.log')
META_TAG_NAMES = {"description", "keywords", "author", "generator", "robots"}
META_TAG_PREFIXES = ("og:", "twitter:")

# --- Core Scraping & Crawling Logic ---
_SPACE_RE = re.compile(r'\s+')
def norm_space(text):
    return _SPACE_RE.sub(' ', text or '').strip()

def _build_osint_queries(keyword, dork_type=None):
    """Generate multiple web search variants to avoid zero-result searches."""
    if not keyword:
        return []
    keyword = keyword.strip()
    
    # If a specific dork type is requested, apply it primarily
    primary_query = osint_helper.apply_dork(keyword, dork_type)
    
    queries, seen = [], set()
    def _add(q):
        q = q.strip()
        if q and q.lower() not in seen:
            queries.append(q); seen.add(q.lower())

    _add(primary_query)
    
    # Also add the raw keyword as fallback if dork is complex
    if primary_query != keyword:
         _add(keyword)

    pieces = [p.strip() for p in _QUERY_SPLIT_RE.split(keyword) if p.strip()]
    if pieces:
        collapsed = " ".join(pieces)
        _add(collapsed)
        for piece in pieces:
            if len(piece) >= 3:
                _add(piece)
    return queries

def _osint_search(keyword, log_queue, limit=MAX_OSINT_RESULTS, dork_type=None):
    urls, seen = [], set()
    for query in _build_osint_queries(keyword, dork_type):
        log_queue.put(f"INFO: Web searching for '{query}'...")
        try:
            for result in DDGS().text(query, max_results=limit):
                href = result.get('href')
                if not href or not href.startswith(("http://", "https://")):
                    continue
                href = href.split("#")[0]
                if href in seen:
                    continue
                seen.add(href); urls.append(href)
                if len(urls) >= limit:
                    return urls
        except Exception as e:
            log_queue.put(f"ERROR: DDGS search for '{query}' failed: {e}")
    return urls

class Crawler:
    def __init__(self, config, log_queue, scrape_queue):
        self.config = config
        self.log_queue = log_queue
        self.scrape_queue = scrape_queue
        self.driver = None
        self.url_queue = deque()
        self.visited_urls = set()
        self.allowed_domains = set()
        self.base_domain = None
        self.pages_crawled = 0
        self.keyword = (self.config.get("focus_keyword") or self.config.get("keyword") or "").strip()
        self._keyword_patterns = osint_helper.build_keyword_patterns(self.keyword)

    def _normalized_url(self, url):
        return url.split('#')[0].rstrip('/')

    def _keyword_match(self, text):
        return osint_helper.match_any(text, self._keyword_patterns)

    def _find_keyword_match(self, text):
        return osint_helper.find_first_match(text, self._keyword_patterns)

    def _snippet_from_match(self, text, match, radius=80):
        if not text or not match:
            return ""
        start = max(0, match.start() - radius)
        end = min(len(text), match.end() + radius)
        snippet = text[start:end]
        snippet = norm_space(snippet)
        if start > 0:
            snippet = f"...{snippet}"
        if end < len(text):
            snippet = f"{snippet}..."
        return snippet

    def _flatten_metadata_pairs(self, metadata):
        pairs = []
        if not metadata:
            return pairs

        def _add(label, value):
            if value is None:
                return
            if isinstance(value, dict):
                for key, inner in value.items():
                    _add(f"{label}.{key}", inner)
                return
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    _add(label, item)
                return
            text = norm_space(str(value))
            if text:
                pairs.append((label, text))

        for key, val in metadata.items():
            _add(key, val)
        return pairs

    def _init_driver(self):
        try:
            self.log_queue.put("INFO: Initializing crawler engine (Selenium)...")
            opts = ChromeOptions()
            opts.add_argument(f"user-agent={self.config['user_agent']}")
            opts.add_argument("--log-level=3")
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_experimental_option("excludeSwitches", ["enable-automation"])
            self.driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=opts)
            self.driver.set_page_load_timeout(self.config.get("page_timeout", 20))
            self.log_queue.put("INFO: Crawler engine ready.")
            return True
        except Exception as e:
            self.log_queue.put(f"FATAL: Failed to initialize Selenium: {e}")
            return False

    def _parse_json_ld(self, soup):
        types, names, urls, same_as, emails, phones = set(), set(), set(), set(), set(), set()

        def _add_limited(target_set, value, limit=20, max_len=240):
            if not value:
                return
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    return
                if len(value) > max_len:
                    value = value[:max_len] + "..."
                if len(target_set) < limit:
                    target_set.add(value)
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    _add_limited(target_set, item, limit=limit, max_len=max_len)

        def _walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    lowered = key.lower()
                    if lowered in {"@type", "type"}:
                        _add_limited(types, value)
                    elif lowered == "name":
                        _add_limited(names, value)
                    elif lowered in {"url", "sameas"}:
                        _add_limited(urls if lowered == "url" else same_as, value)
                    elif lowered == "email":
                        _add_limited(emails, value)
                    elif lowered in {"telephone", "phone"}:
                        _add_limited(phones, value)
                    _walk(value)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string or script.get_text(strip=True)
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            _walk(payload)

        data = {}
        if types:
            data["types"] = sorted(types)
        if names:
            data["names"] = sorted(names)
        if urls:
            data["urls"] = sorted(urls)
        if same_as:
            data["same_as"] = sorted(same_as)
        if emails:
            data["emails"] = sorted(emails)
        if phones:
            data["phones"] = sorted(phones)
        return data

    def _collect_asset_metadata(self, soup, page_url):
        if not self.config.get("osint_mode"):
            return []
        limit = max(0, int(self.config.get("asset_metadata_limit", 5)))
        if limit == 0:
            return []
        assets = []
        seen = set()
        for tag in soup.find_all("a", href=True):
            href = urljoin(page_url, tag["href"])
            href_clean = href.split("#")[0].split("?", 1)[0]
            if not href_clean.lower().endswith(ASSET_EXTS):
                continue
            if href_clean in seen:
                continue
            seen.add(href_clean)
            meta = {"url": href_clean}
            if not _is_public_http_url(href_clean):
                assets.append(meta)
                if len(assets) >= limit:
                    break
                continue
            try:
                head = httpx.head(href_clean, timeout=5, follow_redirects=True)
                if head.status_code == 200:
                    if size := head.headers.get("Content-Length"):
                        meta["size_kb"] = int(size) // 1024
                    if mod := head.headers.get("Last-Modified"):
                        meta["modified"] = mod
                    if ctype := head.headers.get("Content-Type"):
                        meta["content_type"] = ctype
            except Exception:
                pass
            assets.append(meta)
            if len(assets) >= limit:
                break
        return assets

    def extract_page_metadata(self, soup, page_url):
        metadata = {}
        if soup.title and soup.title.get_text(strip=True):
            metadata["title"] = norm_space(soup.title.get_text(" ", strip=True))

        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            metadata["lang"] = html_tag.get("lang")

        canonical = soup.find("link", rel=lambda v: v and "canonical" in v.lower())
        if canonical and canonical.get("href"):
            metadata["canonical"] = urljoin(page_url, canonical["href"])

        for tag in soup.find_all("meta"):
            key = tag.get("name") or tag.get("property") or tag.get("http-equiv")
            content = tag.get("content")
            if not key or not content:
                continue
            key = key.strip().lower()
            if key in META_TAG_NAMES or key.startswith(META_TAG_PREFIXES):
                metadata[key] = norm_space(content)

        if json_ld := self._parse_json_ld(soup):
            metadata["json_ld"] = json_ld

        if assets := self._collect_asset_metadata(soup, page_url):
            metadata["assets"] = assets

        return metadata

    def crawl(self):
        if not self._init_driver(): return
        
        start_urls = self.config['urls']
        self.allowed_domains = {urlparse(u).netloc for u in start_urls if urlparse(u).netloc}
        # Keep base_domain for backwards compatibility (first URL)
        self.base_domain = start_urls and urlparse(start_urls[0]).netloc
        
        for url in start_urls:
            normalized = self._normalized_url(url)
            self.url_queue.append(normalized)
            self.visited_urls.add(normalized)

        pages_crawled = 0
        while self.url_queue and pages_crawled < self.config['max_pages']:
            if not self.config['is_running_check']():
                self.log_queue.put("INFO: Crawl cancelled by user.")
                break
            
            url = self.url_queue.popleft()
            self.log_queue.put(f"Crawling ({pages_crawled + 1}/{self.config['max_pages']}): {url}")

            try:
                self.driver.get(url)
                WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')

                page_metadata = {}
                if self.config.get("osint_mode") or self.config.get("keyword_hits_mode"):
                    page_metadata = self.extract_page_metadata(soup, self.driver.current_url)

                # 1. Extract data from the current page
                for item in self.extract_data(soup, self.driver.current_url, page_metadata):
                    self.scrape_queue.put(item)
                
                # 2. Find new links to crawl
                self.enqueue_links(soup, self.driver.current_url)
                pages_crawled += 1
                self.pages_crawled = pages_crawled
                self.log_queue.put(f"{LOG_STAT_PREFIX}pages={pages_crawled},queue={len(self.url_queue)}")
                time.sleep(self.config.get('delay', 0.5)) # Be polite

            except Exception as e:
                self.log_queue.put(f"ERROR: Failed to process {url}: {e}")
                continue
        
        self.log_queue.put(f"INFO: Crawl finished. Visited {pages_crawled} pages.")
        self.close()

    def extract_data(self, soup, page_url, page_metadata=None):
        keyword = self.keyword
        page_metadata = page_metadata or {}
        if self.config.get("keyword_hits_mode") and keyword:
            for item in self.keyword_hits(soup, page_url, keyword, page_metadata):
                yield item
        if self.config.get("smart_mode"):
            for item in self.smart_extract(soup, page_url, page_metadata):
                yield item

        selector = self.config.get('css_selector', '')
        if not selector: return # Don't scrape if no selector is provided and smart mode already tried
        
        for el in soup.select(selector):
            text = norm_space(el.get_text())
            if not text: continue
            
            link, image_src = '', ''
            if link_tag := el.find('a', href=True): link = urljoin(page_url, link_tag['href'])
            if self.config['scrape_images'] and (img_tag := el.find('img', src=True)): image_src = urljoin(page_url, img_tag['src'])
            
            yield {"Match": 1, "Title": text, "Price": "", "Rating": "", "Shipping": "", "Link": link, "ImageURL": image_src, "SourceURL": page_url}

    def _score_candidate(self, el, action, signals):
        text = norm_space(el.get_text(" ", strip=True))
        if len(text) < 30 or len(text) > 5000: return 0, text
        score = 0
        price_present = bool(PRICE_RE.search(text))
        rating_present = bool(RATING_RE.search(text))
        shipping_present = bool(SHIPPING_HINTS.search(text))
        keyword_hit = self._keyword_match(text)

        if keyword_hit: score += 3
        if price_present: score += 4
        if rating_present: score += 2
        if shipping_present: score += 2
        if el.find(['h1', 'h2', 'h3', 'h4']): score += 2
        if el.find('img', src=True): score += 1

        # User focus toggles
        if signals.get("price") and price_present: score += 3
        if signals.get("reviews") and rating_present: score += 2
        if signals.get("shipping") and shipping_present: score += 2

        # Action presets for prioritization
        if action == "best_price":
            if price_present: score += 4
            if shipping_present: score += 1
        elif action == "best_reviews":
            if rating_present: score += 4
            if price_present: score += 1
        elif action == "fast_shipping":
            if shipping_present: score += 4
        elif action == "keyword_hits":
            if keyword_hit: score += 6
            if price_present or rating_present or shipping_present: score += 1
        else: # balanced
            if price_present and rating_present: score += 1
        return score, text

    def _extract_fields(self, el, page_url, match_score=0):
        text_content = norm_space(el.get_text(" ", strip=True))
        title = ""
        for tag_name in ["h1", "h2", "h3", "h4", "strong"]:
            if (heading := el.find(tag_name)) and (heading_text := norm_space(heading.get_text(" ", strip=True))):
                title = heading_text; break
        if not title:
            if (anchor := el.find('a', href=True)) and (anchor_text := norm_space(anchor.get_text(" ", strip=True))):
                title = anchor_text
            else:
                title = text_content[:180]

        price_match = PRICE_RE.search(text_content)
        rating_match = RATING_RE.search(text_content)
        ship_match = SHIPPING_HINTS.search(text_content)

        price = price_match.group(0) if price_match else ""
        rating = rating_match.group(0) if rating_match else ""
        shipping = ship_match.group(0) if ship_match else ""

        link = ""
        if anchor := el.find('a', href=True):
            link = urljoin(page_url, anchor['href'])
        image_src = ""
        if self.config['scrape_images'] and (img_tag := el.find('img', src=True)):
            image_src = urljoin(page_url, img_tag['src'])
        
        # OSINT Entity extraction if mode enabled
        entities = {}
        if self.config.get('osint_mode'):
            entities = osint_helper.extract_entities(text_content)
            
            # Asset Metadata Check
            clean_link = link.split("#")[0].split("?", 1)[0] if link else ""
            if clean_link.lower().endswith(ASSET_EXTS) and _is_public_http_url(link):
                try:
                    # Quick HEAD request for metadata
                    head = httpx.head(link, timeout=5, follow_redirects=True)
                    if head.status_code == 200:
                        meta = []
                        if size := head.headers.get('Content-Length'):
                            meta.append(f"Size: {int(size)//1024}KB")
                        if mod := head.headers.get('Last-Modified'):
                            meta.append(f"Modified: {mod}")
                        if meta:
                            if "assets" not in entities: entities["assets"] = []
                            entities["assets"].append(f"{link} ({', '.join(meta)})")
                except Exception:
                    pass

        return {
            "Match": match_score, "Title": title, 
            "Price": price, "Rating": rating, "Shipping": shipping, 
            "Entities": entities, # New field
            "Link": link, "ImageURL": image_src, "SourceURL": page_url
        }

    def smart_extract(self, soup, page_url, page_metadata=None):
        has_keyword = bool(self._keyword_patterns)
        page_metadata = page_metadata or {}
        action = self.config.get("focus_action", "balanced")
        signals = {
            "price": self.config.get("focus_price", False),
            "reviews": self.config.get("focus_reviews", False),
            "shipping": self.config.get("focus_shipping", False),
        }
        candidates = []
        for el in soup.find_all(['article', 'div', 'li', 'section']):
            # Skip huge containers to limit noise
            if len(el.find_all(['article', 'div', 'li', 'section'])) > 80:
                continue
            score, text = self._score_candidate(el, action, signals)
            if score < 3 and not has_keyword: continue
            # Boost score when requested focus is present
            if signals["price"] and PRICE_RE.search(text): score += 2
            if signals["reviews"] and RATING_RE.search(text): score += 1
            if signals["shipping"] and SHIPPING_HINTS.search(text): score += 1
            if score >= 3:
                candidates.append((score, el))
        
        # OSINT Mode: Add specific entity search scan
        if self.config.get('osint_mode'):
            # In OSINT mode, we also want to scan the entire body or large blocks for entities even if they don't look like products
            try:
                body_text = soup.get_text(" ", strip=True) 
                # This might be too heavy for the tree view if we dump everything, 
                # but let's try to extract top-level entities found on the page as a single "Page Result"
                page_entities = osint_helper.extract_entities(body_text)
                if page_metadata:
                    meta_pairs = self._flatten_metadata_pairs(page_metadata)
                    if meta_pairs:
                        page_entities["metadata"] = [f"{label}: {value}" for label, value in meta_pairs]
                if page_entities:
                    # Create a synthetic item for page-wide findings
                    yield {
                        "Match": 10,
                        "Title": f"OSINT Findings: {page_url}",
                        "Price": "", "Rating": "", "Shipping": "",
                        "Entities": page_entities,
                        "Link": page_url, "ImageURL": "", "SourceURL": page_url
                    }
            except Exception:
                pass

        # Sort high to low, keep top slice to avoid duplicates
        candidates = sorted(candidates, key=lambda tup: tup[0], reverse=True)[:50]
        seen = set()
        for score, el in candidates:
            item = self._extract_fields(el, page_url, match_score=score)
            if not norm_space(item.get("Title")):
                continue
            key = (item["Title"], item["Link"], item["Price"])
            if key in seen: continue
            seen.add(key)
            yield item

    def keyword_hits(self, soup, page_url, keyword, page_metadata=None):
        """Return every occurrence of the keyword across text and metadata."""
        if not keyword or not self._keyword_patterns:
            return
        limit = int(self.config.get("keyword_hits_limit", 60))
        hits = 0
        seen = set()
        page_metadata = page_metadata or {}

        def _make_item(snippet, link="", image_src="", label=None):
            nonlocal hits
            if not snippet:
                return None
            title = snippet
            if label:
                title = f"{label}: {snippet}"
            key = (label or "text", title[:200], link or page_url)
            if key in seen:
                return None
            seen.add(key)
            hits += 1
            return {
                "Match": 10,
                "Title": title[:200],
                "Price": "",
                "Rating": "",
                "Shipping": "",
                "Link": link,
                "ImageURL": image_src,
                "SourceURL": page_url,
            }

        for text_node in soup.find_all(string=True):
            parent = text_node.parent
            if not parent or getattr(parent, "name", "") in ["script", "style", "noscript", "template"]:
                continue
            text = norm_space(str(text_node))
            if not text:
                continue
            if not (match := self._find_keyword_match(text)):
                continue
            snippet = self._snippet_from_match(text, match)
            anchor = parent if getattr(parent, "name", "") == "a" and parent.get("href") else parent.find_parent("a", href=True)
            link = urljoin(page_url, anchor["href"]) if anchor and anchor.get("href") else ""
            image_src = ""
            if self.config.get("scrape_images"):
                if img_tag := parent.find('img', src=True):
                    image_src = urljoin(page_url, img_tag['src'])
            if item := _make_item(snippet, link, image_src):
                yield item
            if hits >= limit:
                return

        for label, value in self._flatten_metadata_pairs(page_metadata):
            if not value:
                continue
            if not (match := self._find_keyword_match(value)):
                continue
            snippet = self._snippet_from_match(value, match) or value[:160]
            if item := _make_item(snippet, link=page_url, label=f"META {label}"):
                yield item
            if hits >= limit:
                return

        attr_specs = [
            ("alt", "ATTR alt"),
            ("title", "ATTR title"),
            ("aria-label", "ATTR aria-label"),
        ]
        for attr, label in attr_specs:
            for tag in soup.find_all(attrs={attr: True}):
                value = norm_space(tag.get(attr))
                if not value:
                    continue
                if not (match := self._find_keyword_match(value)):
                    continue
                snippet = self._snippet_from_match(value, match) or value[:160]
                link = ""
                if tag.name == "a" and tag.get("href"):
                    link = urljoin(page_url, tag["href"])
                if item := _make_item(snippet, link=link, label=label):
                    yield item
                if hits >= limit:
                    return

        for tag in soup.find_all("a", href=True):
            href = urljoin(page_url, tag["href"])
            if not href:
                continue
            if not self._keyword_match(href):
                continue
            if item := _make_item(href, link=href, label="ATTR href"):
                yield item
            if hits >= limit:
                return

        for tag in soup.find_all("img", src=True):
            src = urljoin(page_url, tag["src"])
            if not src:
                continue
            if not self._keyword_match(src):
                continue
            if item := _make_item(src, link=src, label="ATTR src"):
                yield item
            if hits >= limit:
                return

    def enqueue_links(self, soup, page_url):
        allow_external = self.config.get("allow_external", False)
        for link_tag in soup.find_all('a', href=True):
            link = urljoin(page_url, link_tag['href'])
            if not _is_public_http_url(link):
                continue
            parsed_link = urlparse(link)
            normalized = self._normalized_url(link)
            
            # Stay on the same domain, basic validation
            domain_ok = (allow_external or not self.allowed_domains or parsed_link.netloc in self.allowed_domains)
            if (parsed_link.scheme in ['http', 'https'] and
                domain_ok and
                normalized not in self.visited_urls and
                not any(x in normalized.lower() for x in ['login', 'logout', 'cart', '.zip', '.pdf', '.jpg'])):
                self.visited_urls.add(normalized)
                self.url_queue.append(normalized)

    def close(self):
        if self.driver: self.driver.quit()

def scrape_controller(config, log_queue, scrape_queue):
    try:
        if config['use_ai'] and not ai_helper.configure_api(config['api_key']):
            reason = ai_helper.get_last_error() or "AI API key is invalid or not configured."
            log_queue.put(f"WARNING: {reason} -- Continuing without AI features.")
            config['use_ai'] = False

        urls = config['urls']
        if config['osint_mode']:
            seed_urls = list(urls)
            log_queue.put(f"INFO: OSINT mode: Searching for '{config['keyword']}'...")
            found_urls = _osint_search(config['keyword'], log_queue, MAX_OSINT_RESULTS, dork_type=config.get('dork_type'))
            if found_urls:
                urls = found_urls
            elif seed_urls:
                log_queue.put("INFO: Web search returned no URLs; using provided Start URLs instead.")
                urls = seed_urls
            log_queue.put(f"INFO: Found {len(urls)} URLs to scrape."); config['urls'] = urls
        if not urls:
            log_queue.put("ERROR: No URLs to begin crawl."); return
        config['urls'] = list(dict.fromkeys(urls))  # de-dupe while keeping order

        crawler = Crawler(config, log_queue, scrape_queue)
        crawler.crawl()
    except Exception as e:
        log_queue.put(f"FATAL: Unhandled exception in scrape controller: {e}")

def _report_tools():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    from src.domain.graph import build_relation_graph
    from src.infrastructure.report_html import render_report_html
    return build_relation_graph, render_report_html


_PUBLIC_URL = None


def _is_public_http_url(url):
    """Refuse loopback, link-local, and RFC 1918 before enqueue or HEAD."""
    global _PUBLIC_URL
    if _PUBLIC_URL is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        from src.domain.url_guard import is_public_http_url
        _PUBLIC_URL = is_public_http_url
    return _PUBLIC_URL(url)


# --- GUI ---
class ScraperGUI(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=15)
        self.master = master
        self.pack(fill=BOTH, expand=YES)
        self.master.title("Gemini Scraper v4.0 - The Final Word")
        self.master.geometry("1400x950")
        self.log_queue, self.scrape_queue, self.is_running = queue.Queue(), queue.Queue(), False
        self.db = DatabaseManager()
        self.monitor = Watchdog(self.db)
        self.monitor.start()
        self.current_session_id = None
        self._seen_items = set()
        self._all_results_cache = []
        self._model_config = None
        self._model_config_path = os.path.join(os.getcwd(), "model_config.json")
        self._installing_libraries = False
        self._install_notes = queue.Queue()
        self._load_saved_model()
        self.pages_crawled = 0
        self.queue_size = 0
        self.run_started_at = None
        self._elapsed_at_stop = 0
        
        # UI State Variables
        self.mode_var = ttk.StringVar(value="shopping")
        self.url_var = ttk.StringVar()
        self.keyword_var = ttk.StringVar()
        self.osint_keyword_var = ttk.StringVar()
        self.action_var = ttk.StringVar(value="balanced") # Shopping sort
        self.dork_var = ttk.StringVar(value="general")
        
        # Config (Global/Shared)
        self.strength_var = ttk.IntVar(value=10)
        self.smart_var = ttk.BooleanVar(value=True)
        self.osint_var = ttk.BooleanVar(value=False)
        self.images_var = ttk.BooleanVar(value=True)
        self.allow_external_var = ttk.BooleanVar(value=False)
        self.delay_var = ttk.DoubleVar(value=0.5)
        self.timeout_var = ttk.IntVar(value=20)
        self.keyword_hits_var = ttk.BooleanVar(value=False)
        self.keyword_limit_var = ttk.IntVar(value=120)
        self.focus_price_var = ttk.BooleanVar(value=True)
        self.focus_reviews_var = ttk.BooleanVar(value=True)
        self.focus_shipping_var = ttk.BooleanVar(value=True)
        self.ai_var = ttk.BooleanVar(value=bool(os.getenv("GEMINI_API_KEY")))
        
        self._create_widgets()
        self.master.after(100, self._process_queues)

    def _create_widgets(self):
        main_pane = ttk.Panedwindow(self, orient=HORIZONTAL); main_pane.pack(fill=BOTH, expand=YES)
        controls_frame = ttk.Frame(main_pane, padding=10); main_pane.add(controls_frame, weight=1)
        results_frame = ttk.Frame(main_pane, padding=5); main_pane.add(results_frame, weight=3)

        # --- Sidebar / Controls ---
        # 1. Mode Switcher
        mode_frame = ttk.Frame(controls_frame); mode_frame.pack(fill=X, pady=(0, 15))
        ttk.Label(mode_frame, text="Select Mode:", font=("Helvetica", 10, "bold")).pack(anchor=W, pady=(0,5))
        
        modes = [("🛒 Shopping", "shopping"), ("🕵️ OSINT", "osint"), ("🐕 Watchdog", "watchdog"), ("🛠️ Custom", "custom")]
        for label, val in modes:
            btn = ttk.Radiobutton(mode_frame, text=label, variable=self.mode_var, value=val, 
                                  command=self._toggle_mode, bootstyle="toolbutton-outline")
            btn.pack(side=LEFT, expand=YES, fill=X, padx=2)

        # 2. Dynamic Input Area
        self.input_container = ttk.Frame(controls_frame); self.input_container.pack(fill=BOTH, expand=YES)
        
        # Create the three views (hidden by default)
        self.shopping_view = ttk.Frame(self.input_container)
        self._build_shopping_view(self.shopping_view)
        
        self.osint_view = ttk.Frame(self.input_container)
        self._build_osint_view(self.osint_view)
        
        self.custom_view = ttk.Frame(self.input_container)
        self._build_custom_view(self.custom_view)

        # Watchdog View
        self.watchdog_view = ttk.Frame(self.input_container)
        self._build_watchdog_view(self.watchdog_view)
        
        # 3. Action Buttons (Bottom of controls)
        btn_frame = ttk.Frame(controls_frame); btn_frame.pack(fill=X, side=BOTTOM, pady=5)
        self.scrape_btn = ttk.Button(btn_frame, text="🚀 LAUNCH CRAWL", command=self.start_scraping, style="success.TButton")
        self.scrape_btn.pack(fill=X, ipady=8, pady=(0,5))
        self.stop_btn = ttk.Button(btn_frame, text="STOP", command=self.stop_scraping, style="danger.TButton", state=DISABLED)
        self.stop_btn.pack(fill=X)

        # 4. Results Area
        res_log_pane = ttk.Panedwindow(results_frame, orient=VERTICAL); res_log_pane.pack(fill=BOTH, expand=YES)
        results_ui_frame = ttk.Frame(res_log_pane); res_log_pane.add(results_ui_frame, weight=3)
        log_frame = ttk.Labelframe(res_log_pane, text="Log", padding=5); res_log_pane.add(log_frame, weight=1)
        self.log_text = scrolledtext.ScrolledText(log_frame, state=DISABLED, wrap=WORD); self.log_text.pack(fill=BOTH, expand=YES)

        header_frame = ttk.Frame(results_ui_frame); header_frame.pack(fill=X, pady=(0,5))
        ttk.Label(header_frame, text="Results", font=("Helvetica", 12, "bold")).pack(side=LEFT)
        self.stats_var = ttk.StringVar(value="Ready")
        ttk.Label(header_frame, textvariable=self.stats_var, bootstyle="inverse-primary").pack(side=LEFT, padx=10)
        
        export_frame = ttk.Frame(header_frame); export_frame.pack(side=RIGHT)
        ttk.Button(export_frame, text="CSV", command=self.export_csv, bootstyle="info-outline").pack(side=LEFT, padx=2)
        ttk.Button(export_frame, text="Excel", command=self.export_excel, bootstyle="secondary-outline").pack(side=LEFT, padx=2)
        ttk.Button(export_frame, text="JSON", command=self.export_json, bootstyle="primary-outline").pack(side=LEFT, padx=2)
        ttk.Button(export_frame, text="Relationship report", command=self.export_report, bootstyle="success").pack(side=LEFT, padx=2)
        ttk.Button(export_frame, text="Model setup", command=self.open_model_wizard, bootstyle="warning-outline").pack(side=LEFT, padx=2)
        ttk.Button(export_frame, text="AI chat", command=self.open_ai_chat, bootstyle="warning").pack(side=LEFT, padx=2)
        self.install_btn = ttk.Button(export_frame, text=self._library_button_text(), command=self.install_model_libraries, bootstyle="info")
        self.install_btn.pack(side=LEFT, padx=2)
        
        filter_frame = ttk.Frame(results_ui_frame); filter_frame.pack(fill=X, pady=5)
        self.filter_var = ttk.StringVar(); self.filter_var.trace_add("write", self._filter_results_ui)
        ttk.Entry(filter_frame, textvariable=self.filter_var, width=30).pack(side=LEFT, fill=X, expand=YES)
        ttk.Button(filter_frame, text="History", command=self.show_history, bootstyle="info-outline").pack(side=LEFT, padx=5)
        ttk.Button(filter_frame, text="Clear", command=self.clear_results, bootstyle="link").pack(side=RIGHT)

        self.columns = ("Match", "Title", "Price", "Rating", "Shipping", "Entities", "Link", "ImageURL", "SourceURL"); self.tree = ttk.Treeview(results_ui_frame, columns=self.columns, show="headings")
        v_scroll = ttk.Scrollbar(self.tree, orient=VERTICAL, command=self.tree.yview); v_scroll.pack(side=RIGHT, fill=Y)
        h_scroll = ttk.Scrollbar(self.tree, orient=HORIZONTAL, command=self.tree.xview); h_scroll.pack(side=BOTTOM, fill=X)
        self.tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        for col in self.columns: self.tree.heading(col, text=col)
        self.tree.column("Match", width=70, anchor=CENTER); self.tree.column("Title", width=320); self.tree.column("Price", width=90); self.tree.column("Rating", width=90); self.tree.column("Shipping", width=120)
        self.tree.column("Entities", width=200) # New column
        self.tree.column("Link", width=250); self.tree.column("ImageURL", width=200); self.tree.column("SourceURL", width=220)
        self.tree.pack(fill=BOTH, expand=YES); self.tree.bind("<Button-3>", self.show_context_menu)

        # Initialize View
        self._toggle_mode()

    def _build_shopping_view(self, parent):
        ttk.Label(parent, text="Find Products", font=("Helvetica", 12)).pack(anchor=W, pady=(10,5))
        ttk.Label(parent, text="Product Name or URL:").pack(anchor=W)
        self.shop_input = ttk.Entry(parent, textvariable=self.url_var, font=("Helvetica", 11))
        self.shop_input.pack(fill=X, pady=5, ipady=3)
        self.shop_input.bind("<Return>", lambda e: self.start_scraping())
        
        ttk.Label(parent, text="Prioritize:").pack(anchor=W, pady=(15,5))
        opts = [("⚖️ Balanced", "balanced"), ("💰 Best Price", "best_price"), ("⭐ Best Reviews", "best_reviews"), ("🚚 Fast Shipping", "fast_shipping")]
        for txt, val in opts:
            ttk.Radiobutton(parent, text=txt, variable=self.action_var, value=val).pack(anchor=W, pady=2)

    def _build_osint_view(self, parent):
        ttk.Label(parent, text="OSINT Investigator", font=("Helvetica", 12)).pack(anchor=W, pady=(10,5))
        ttk.Label(parent, text="Target Keyword / Person / Domain:").pack(anchor=W)
        self.osint_input = ttk.Entry(parent, textvariable=self.osint_keyword_var, font=("Helvetica", 11))
        self.osint_input.pack(fill=X, pady=5, ipady=3)
        self.osint_input.bind("<Return>", lambda e: self.start_scraping())
        
        ttk.Label(parent, text="Search Type (Dork):").pack(anchor=W, pady=(15,5))
        dork_options = ["general"] + list(osint_helper.DORKS.keys())
        ttk.Combobox(parent, textvariable=self.dork_var, values=dork_options, state="readonly").pack(fill=X)
        ttk.Label(parent, text="* Finds emails, phones, social profiles automatically.", font=("Helvetica", 9), bootstyle="secondary").pack(anchor=W, pady=5)

    def _build_custom_view(self, parent):
        nb = ttk.Notebook(parent); nb.pack(fill=BOTH, expand=YES)
        tab_main = ttk.Frame(nb, padding=5); nb.add(tab_main, text="Control")
        tab_adv = ttk.Frame(nb, padding=5); nb.add(tab_adv, text="Advanced")
        
        # Main Control
        ttk.Label(tab_main, text="Wait... you want to do it yourself?").pack(anchor=W, pady=5)
        ttk.Label(tab_main, text="Start URL(s):").pack(anchor=W)
        self.url_text = scrolledtext.ScrolledText(tab_main, height=4, width=30); self.url_text.pack(fill=X, pady=2)
        
        ttk.Label(tab_main, text="Focus Keyword (Optional):").pack(anchor=W)
        self.custom_keyword = ttk.Entry(tab_main, textvariable=self.keyword_var); self.custom_keyword.pack(fill=X, pady=(0,5))

        ttk.Label(tab_main, text="CSS Selector (Optional):").pack(anchor=W, pady=(5,0))
        self.selector_entry = ttk.Entry(tab_main); self.selector_entry.pack(fill=X)
        
        ttk.Label(tab_main, text="AI Generator:").pack(anchor=W, pady=(10,0))
        self.ai_desc_entry = ttk.Entry(tab_main); self.ai_desc_entry.pack(fill=X)
        ai_box = ttk.Frame(tab_main); ai_box.pack(fill=X, pady=2)
        ttk.Button(ai_box, text="Gen (Text)", command=self.generate_selector_with_ai).pack(side=LEFT, expand=YES, fill=X)
        ttk.Button(ai_box, text="Gen (Image)", command=self.generate_selector_from_image).pack(side=LEFT, expand=YES, fill=X)

        # Advanced
        ttk.Label(tab_adv, text="Scraping Strength (Pages):").pack(anchor=W)
        ttk.Scale(tab_adv, from_=1, to=200, variable=self.strength_var, orient=HORIZONTAL, command=self._update_strength_label).pack(fill=X)
        self.strength_label = ttk.Label(tab_adv, text=f"Max Pages: {self.strength_var.get()}"); self.strength_label.pack(anchor=W)
        
        ttk.Checkbutton(tab_adv, text="OSINT Mode", variable=self.osint_var).pack(anchor=W, pady=2)
        kw_frame = ttk.Frame(tab_adv); kw_frame.pack(fill=X, pady=2)
        ttk.Checkbutton(kw_frame, text="Keyword Hit Finder", variable=self.keyword_hits_var).pack(side=LEFT)
        ttk.Label(kw_frame, text="Limit:").pack(side=LEFT, padx=5)
        ttk.Entry(kw_frame, textvariable=self.keyword_limit_var, width=6).pack(side=LEFT)
        ttk.Checkbutton(tab_adv, text="Scrape Images", variable=self.images_var).pack(anchor=W, pady=2)
        ttk.Checkbutton(tab_adv, text="Cross-Domain", variable=self.allow_external_var).pack(anchor=W, pady=2)
        ttk.Checkbutton(tab_adv, text="Use AI Features", variable=self.ai_var).pack(anchor=W, pady=2)
        
        ttk.Label(tab_adv, text="API Key:").pack(anchor=W, pady=(5,0))
        self.api_key_entry = ttk.Entry(tab_adv, show="*"); self.api_key_entry.pack(fill=X)
        default_api = os.getenv("GEMINI_API_KEY")
        if default_api: self.api_key_entry.insert(0, default_api)

    def _toggle_mode(self):
        mode = self.mode_var.get()
        self.shopping_view.pack_forget()
        self.osint_view.pack_forget()
        self.custom_view.pack_forget()
        self.watchdog_view.pack_forget()
        
        if mode == "shopping":
            self.shopping_view.pack(fill=BOTH, expand=YES)
            self.action_var.set("balanced") # Default
        elif mode == "osint":
            self.osint_view.pack(fill=BOTH, expand=YES)
            self.dork_var.set("general") # Default
        elif mode == "custom":
            self.custom_view.pack(fill=BOTH, expand=YES)
        elif mode == "watchdog":
            self.watchdog_view.pack(fill=BOTH, expand=YES)
            self._refresh_watchlist()

    def _build_watchdog_view(self, parent):
        ttk.Label(parent, text="Web Watchdog", font=("Helvetica", 12)).pack(anchor=W, pady=(10,5))
        
        # Inputs
        input_frame = ttk.Frame(parent); input_frame.pack(fill=X, pady=5)
        ttk.Label(input_frame, text="URL:").pack(anchor=W)
        self.watch_url = ttk.Entry(input_frame); self.watch_url.pack(fill=X)
        
        ttk.Label(input_frame, text="Keyword (or Price):").pack(anchor=W)
        self.watch_kw = ttk.Entry(input_frame); self.watch_kw.pack(fill=X)
        
        mode_frame = ttk.Frame(input_frame); mode_frame.pack(fill=X, pady=5)
        self.watch_mode = ttk.StringVar(value="keyword")
        ttk.Radiobutton(mode_frame, text="Keyword Match", variable=self.watch_mode, value="keyword").pack(side=LEFT)
        ttk.Radiobutton(mode_frame, text="Price Drop", variable=self.watch_mode, value="price").pack(side=LEFT, padx=10)
        
        ttk.Button(input_frame, text="Add Monitor", command=self._add_monitor, bootstyle="warning").pack(fill=X, pady=5)
        
        # List
        ttk.Label(parent, text="Active Monitors:", font=("Helvetica", 10, "bold")).pack(anchor=W, pady=(10,0))
        self.watch_tree = ttk.Treeview(parent, columns=("ID", "URL", "Condition"), show="headings", height=8)
        self.watch_tree.heading("ID", text="ID"); self.watch_tree.column("ID", width=30)
        self.watch_tree.heading("URL", text="URL"); self.watch_tree.column("URL", width=150)
        self.watch_tree.heading("Condition", text="Condition"); self.watch_tree.column("Condition", width=100)
        self.watch_tree.pack(fill=BOTH, expand=YES)
        
        ttk.Button(parent, text="Remove Selected", command=self._remove_monitor, bootstyle="danger-outline").pack(fill=X, pady=5)

    def _refresh_watchlist(self):
        self.watch_tree.delete(*self.watch_tree.get_children())
        for row in self.db.get_watchlist():
            crit = f"Price <= {row[3]}" if row[4] == "price" else f"Has '{row[2]}'"
            self.watch_tree.insert("", END, values=(row[0], row[1], crit))

    def _add_monitor(self):
        url = self.watch_url.get().strip()
        kw = self.watch_kw.get().strip()
        mode = self.watch_mode.get()
        target = 0.0
        if mode == "price":
            try: target = float(kw)
            except: messagebox.showerror("Error", "Enter a numeric price."); return
            
        if not url: return
        self.db.add_watch_item(url, kw, target, mode)
        self._refresh_watchlist()
        self.watch_url.delete(0, END); self.watch_kw.delete(0, END)
        messagebox.showinfo("Success", "Added to Watchdog!")

    def _remove_monitor(self):
        if not self.watch_tree.selection(): return
        item = self.watch_tree.selection()[0]
        db_id = self.watch_tree.item(item, "values")[0]
        self.db.delete_watch_item(db_id)
        self._refresh_watchlist()



    def _update_strength_label(self, val):
        self.strength_label.config(text=f"Max Pages: {int(float(val))}")
        
    def _filter_results_ui(self, *args):
        self._render_results()

    def _process_queues(self):
        self._drain_install_notes()
        # Process logs
        new_data = False
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            if msg.startswith(LOG_STAT_PREFIX):
                self._apply_stat_line(msg)
                continue
            self.log_text.config(state=NORMAL); self.log_text.insert(END, msg + "\n"); self.log_text.see(END); self.log_text.config(state=DISABLED)
        # Process results
        while not self.scrape_queue.empty():
            item = self.scrape_queue.get_nowait()
            values = [str(item.get(c, "")) for c in self.columns]
            key_parts = []
            if len(values) > 1:
                key_parts.append(values[1])
            if len(values) > 6:
                key_parts.append(values[6])
            if len(values) > 8:
                key_parts.append(values[8])
            key = tuple(key_parts) if key_parts else tuple(values)
            if key in self._seen_items: continue
            self._seen_items.add(key)
            self._all_results_cache.append(values) # Add to cache
            
            # Save to DB if we have an active session
            if self.current_session_id:
                # Reconstruct item dict for DB
                db_item = {
                    "Match": item.get("Match", 0), "Title": item.get("Title"), "Price": item.get("Price"),
                    "Rating": item.get("Rating"), "Shipping": item.get("Shipping"), "Link": item.get("Link"),
                    "ImageURL": item.get("ImageURL"), "SourceURL": item.get("SourceURL"), "Entities": item.get("Entities")
                }
                self.db.save_result(self.current_session_id, db_item)
                
            new_data = True
        if new_data:
            self._render_results()
        self._update_stats()
        self.master.after(100, self._process_queues)

    def _score_from_row(self, row):
        try: return float(row[0])
        except Exception: return 0.0

    def _render_results(self):
        query = self.filter_var.get().lower()
        for i in self.tree.get_children(): self.tree.delete(i)
        for row_data in sorted(self._all_results_cache, key=self._score_from_row, reverse=True):
            if query and (len(row_data) < 2 or query not in str(row_data[1]).lower()):
                continue
            self.tree.insert("", END, values=row_data)

    def _apply_stat_line(self, msg):
        try:
            payload = msg.replace(LOG_STAT_PREFIX, "")
            parts = dict(part.split("=") for part in payload.split(",") if "=" in part)
            self.pages_crawled = int(parts.get("pages", self.pages_crawled))
            self.queue_size = int(parts.get("queue", self.queue_size))
        except Exception:
            pass

    def _update_stats(self):
        runtime = self._elapsed_at_stop
        if self.run_started_at:
            runtime = int((datetime.now() - self.run_started_at).total_seconds())
        self.stats_var.set(f"Pages: {self.pages_crawled} | Queue: {self.queue_size} | Items: {len(self._all_results_cache)} | Runtime: {runtime}s")

    def _normalize_entities(self, value):
        if isinstance(value, dict):
            return {str(k): self._normalize_entities(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._normalize_entities(v) for v in value]
        return value

    def _coerce_entities(self, raw):
        if isinstance(raw, dict):
            return self._normalize_entities(raw)
        if raw is None:
            return {}
        text = raw if isinstance(raw, str) else str(raw)
        text = text.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            return self._normalize_entities(parsed)
        except Exception:
            pass
        try:
            parsed = ast.literal_eval(text)
            return self._normalize_entities(parsed)
        except Exception:
            return {}

    def _prepare_export_data(self):
        data = []
        for row in self._all_results_cache:
            record = dict(zip(self.columns, row))
            record["Entities"] = self._coerce_entities(record.get("Entities"))
            data.append(record)
        return data

    def export_csv(self):
        if not self._all_results_cache:
            messagebox.showinfo("No Data", "Run a crawl before exporting results.")
            return
        default_name = f"scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=default_name, filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if not path: return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(self.columns)
                writer.writerows(self._all_results_cache)
            messagebox.showinfo("Export Complete", f"Saved {len(self._all_results_cache)} rows to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not export CSV:\n{e}")

    def export_excel(self):
        if not self._all_results_cache:
            messagebox.showinfo("No Data", "Run a crawl before exporting results.")
            return
        default_name = f"scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile=default_name, filetypes=[("Excel Workbook", "*.xlsx"), ("All files", "*.*")])
        if not path: return
        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(self.columns)
            for row in self._all_results_cache:
                ws.append(row)
            wb.save(path)
            messagebox.showinfo("Export Complete", f"Saved {len(self._all_results_cache)} rows to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not export Excel:\n{e}")

    def export_json(self):
        if not self._all_results_cache:
            messagebox.showinfo("No Data", "Run a crawl before exporting results.")
            return
        default_name = f"scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile=default_name, filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path: return
        try:
            as_dicts = self._prepare_export_data()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(as_dicts, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("Export Complete", f"Saved {len(self._all_results_cache)} rows to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not export JSON:\n{e}")

    def _project_root(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        return root

    def _load_saved_model(self):
        try:
            self._project_root()
            from src.infrastructure.model_store import load_model_config
            self._model_config = load_model_config(self._model_config_path)
        except Exception:
            self._model_config = None

    def _remember_model(self, config):
        self._model_config = config
        self.install_btn.configure(text=self._library_button_text())

    def _library_button_text(self):
        self._project_root()
        from src.application.packages import install_button_label, packages_for
        backend = "huggingface"
        if self._model_config is not None and (self._model_config.backend or "").strip():
            backend = self._model_config.backend.strip()
        if not packages_for(backend):
            return "Install libraries"
        return install_button_label(backend)

    def install_model_libraries(self):
        """Pip-install the libraries for the saved backend. Hugging Face is the default."""
        self._project_root()
        from src.application.packages import NO_LIBRARY, packages_for
        backend = "huggingface"
        if self._model_config is not None and (self._model_config.backend or "").strip():
            backend = self._model_config.backend.strip()
        packages = packages_for(backend)
        if not packages:
            self.log_queue.put(f"INFO: {NO_LIBRARY}")
            return NO_LIBRARY
        if self._installing_libraries:
            return "An install is already running."
        self._installing_libraries = True
        self.install_btn.configure(state=DISABLED)
        label = " + ".join(packages)
        self.log_queue.put(f"INFO: Installing {label}. This can take a few minutes.")

        def work():
            from src.infrastructure.pip_install import install_packages
            self._install_notes.put(install_packages(packages))

        threading.Thread(target=work, daemon=True).start()
        return f"Installing {label}. This can take a few minutes."

    def _drain_install_notes(self):
        try:
            while True:
                ok, message = self._install_notes.get_nowait()
                self._installing_libraries = False
                self.install_btn.configure(state=NORMAL)
                self.log_text.config(state=NORMAL)
                self.log_text.insert(END, ("INFO: " if ok else "ERROR: ") + message + "\n")
                self.log_text.see(END)
                self.log_text.config(state=DISABLED)
                if ok:
                    messagebox.showinfo("Libraries", message)
                else:
                    messagebox.showerror("Libraries", message)
        except queue.Empty:
            pass

    def open_model_wizard(self):
        self._project_root()
        from src.presentation.model_wizard import ModelWizard
        ModelWizard(self.master, on_saved=self._remember_model, store_path=self._model_config_path)

    def open_ai_chat(self):
        self._project_root()
        from src.application.chat import ask_about_results, backend_label, local_complete, opening_reply, records_from_rows, sessions_from_history
        from src.domain.inference import InferenceResult
        from src.infrastructure.inference_factory import build_backend
        from src.presentation.chat_window import ChatWindow

        present, past, saved = self._chat_materials(records_from_rows, sessions_from_history)
        gemini_ready = bool(os.getenv("GEMINI_API_KEY") or self.api_key_entry.get().strip())
        snapshot = {"rows": (present, past, saved)}

        def complete(prompt):
            return local_complete(self._model_config, prompt, build_backend)

        def fallback(prompt):
            text, err = ai_helper.generate_text(prompt, self.api_key_entry.get())
            if text:
                return InferenceResult(True, text, "")
            return InferenceResult(False, "", err or "Gemini did not answer.")

        def before_ask():
            snapshot["rows"] = self._chat_materials(records_from_rows, sessions_from_history)

        def ask(question, history):
            live_present, live_past, live_saved = snapshot["rows"]
            return ask_about_results(question, live_present, live_past, live_saved, history, complete, fallback)

        ChatWindow(
            self.master,
            ask=ask,
            run_action=self._apply_chat_action,
            opening=opening_reply(present, past, saved),
            backend_label=backend_label(self._model_config, gemini_ready),
            before_ask=before_ask,
            install_libraries=self.install_model_libraries,
        )

    def _chat_materials(self, records_from_rows, sessions_from_history):
        present = records_from_rows(list(self._all_results_cache))
        try:
            history_rows = self.db.get_history() or []
        except Exception:
            history_rows = []
        past = sessions_from_history(history_rows[:8])
        saved = []
        for row in history_rows[:2]:
            try:
                saved.extend(self.db.get_results_for_session(row[0])[:4])
            except Exception:
                continue
        return present, past, records_from_rows(saved)

    def _apply_chat_action(self, action):
        self._project_root()
        from src.application.chat import plan_action
        plan = plan_action(action)
        if not plan.ok:
            return plan.message
        if plan.mode in {"osint", "custom"} and self.is_running:
            return "A crawl is already running. Stop it before starting another."
        if plan.mode == "osint":
            self.mode_var.set("osint")
            self._toggle_mode()
            self.osint_keyword_var.set(plan.keyword)
            self.dork_var.set(plan.dork_type or "general")
            self.log_queue.put(f"INFO: AI chat search: {plan.keyword}")
            self.start_scraping()
        elif plan.mode == "custom":
            self.mode_var.set("custom")
            self._toggle_mode()
            self.url_text.delete("1.0", END)
            self.url_text.insert("1.0", plan.url)
            if plan.keyword:
                self.keyword_var.set(plan.keyword)
            self.smart_var.set(True)
            self.log_queue.put(f"INFO: AI chat scrape: {plan.url}")
            self.start_scraping()
        elif plan.mode == "watchdog":
            self.db.add_watch_item(plan.url, plan.keyword, plan.target_price, plan.watch_mode or "keyword")
            self._refresh_watchlist()
            self.log_queue.put(plan.message)
        return plan.message

    def export_report(self):
        if not self._all_results_cache:
            messagebox.showinfo("No Data", "Run a crawl before exporting results.")
            return
        default_name = f"osint_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        path = filedialog.asksaveasfilename(defaultextension=".html", initialfile=default_name, filetypes=[("HTML Report", "*.html"), ("All files", "*.*")])
        if not path: return
        
        try:
            data = self._prepare_export_data()
            build_relation_graph, render_report_html = _report_tools()
            html_content = render_report_html(build_relation_graph(data), title="OSINT Relationship Map")
            with open(path, "w", encoding="utf-8") as f:
                f.write(html_content)

            messagebox.showinfo("Export Complete", f"Saved Report to:\n{path}")
            report_uri = Path(path).resolve().as_uri()
            webbrowser.open(report_uri)
            
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not export Report:\n{e}")

    def copy_row_to_clipboard(self, row_values):
        try:
            self.master.clipboard_clear()
            self.master.clipboard_append("\t".join(str(v) for v in row_values))
            self.log_queue.put("INFO: Copied row to clipboard.")
        except Exception as e:
            messagebox.showerror("Clipboard Error", f"Could not copy row:\n{e}")

    def _ai_gen_common_checks(self):
        if not self.ai_var.get(): messagebox.showwarning("AI Disabled", "Enable AI Features & provide API key in Settings."); return False
        if not ai_helper.configure_api(self.api_key_entry.get()):
            msg = ai_helper.get_last_error() or "The Gemini API key is invalid."
            messagebox.showerror("API Error", msg); return False
        return True

    def show_history(self):
        hist_win = ttk.Toplevel(self.master)
        hist_win.title("Crawl History")
        hist_win.geometry("600x400")
        
        cols = ("Time", "Mode", "Keyword", "Items")
        tree = ttk.Treeview(hist_win, columns=cols, show="headings")
        for c in cols: tree.heading(c, text=c)
        tree.pack(fill=BOTH, expand=YES)
        
        for sess in self.db.get_history():
            tree.insert("", END, values=(sess[1], sess[3], sess[2], sess[4]), tags=(sess[0],))
            
        def load_session(event):
            try:
                item = tree.selection()[0]
                sess_id = tree.item(item, "tags")[0]
                self.clear_results()
                results = self.db.get_results_for_session(sess_id)
                for r in results:
                    values = [str(r.get(c, "")) for c in self.columns]
                    self._all_results_cache.append(values)
                    self.tree.insert("", END, values=values)
                self.stats_var.set(f"Loaded {len(results)} items from history.")
            except IndexError: pass
            
        tree.bind("<Double-1>", load_session)

    def generate_selector_from_image(self):
        if not self._ai_gen_common_checks(): return
        url_text = self.url_text.get("1.0", "1.end").strip()
        url, desc = (url_text.splitlines()[0] if url_text else ""), self.ai_desc_entry.get().strip()
        if not url or not desc: messagebox.showwarning("Input Error", "URL and AI Description are required."); return
        if not (image_path := filedialog.askopenfilename(title="Select Screenshot")): return
        self.log_queue.put("INFO: Getting page HTML for Vision AI analysis...")
        try:
            content = httpx.get(url, headers=DEFAULT_HEADERS, follow_redirects=True, timeout=20).text
            threading.Thread(target=self._run_ai_selector_gen, args=(ai_helper.generate_selector_from_image, content, image_path, desc)).start()
        except Exception as e: messagebox.showerror("Error", f"Failed to fetch page for AI: {e}")

    def generate_selector_with_ai(self): # Text-based
        if not self._ai_gen_common_checks(): return
        url_text = self.url_text.get("1.0", "1.end").strip()
        url, desc = (url_text.splitlines()[0] if url_text else ""), self.ai_desc_entry.get().strip()
        if not url or not desc: messagebox.showwarning("Input Error", "URL and AI Description are required."); return
        self.log_queue.put("INFO: Getting page HTML for AI analysis...")
        try:
            content = httpx.get(url, headers=DEFAULT_HEADERS, follow_redirects=True, timeout=20).text
            threading.Thread(target=self._run_ai_selector_gen, args=(ai_helper.generate_css_selector, content, desc)).start()
        except Exception as e: messagebox.showerror("Error", f"Failed to fetch page for AI: {e}")

    def _run_ai_selector_gen(self, gen_function, *args):
        self.log_queue.put("INFO: Generating CSS selector with Gemini AI...")
        selector, err = gen_function(*args)
        if err: messagebox.showerror("AI Error", f"Failed to generate selector:\n{err}")
        else:
            self.selector_entry.delete(0, END); self.selector_entry.insert(0, selector)
            self.log_queue.put(f"SUCCESS: AI generated selector: {selector}")

    def preview_first_page(self):
        raw_url_text = self.url_text.get("1.0", "1.end").strip()
        start_url = raw_url_text.splitlines()[0].strip() if raw_url_text else ""
        selector = self.selector_entry.get().strip()
        smart_mode = self.smart_var.get()
        keyword_hits_mode = self.keyword_hits_var.get() or self.action_var.get() == "keyword_hits"
        action_choice = "keyword_hits" if keyword_hits_mode else self.action_var.get()
        try:
            keyword_hits_limit = max(5, int(self.keyword_limit_var.get()))
        except Exception:
            keyword_hits_limit = 120
        if not start_url:
            messagebox.showwarning("Input Error", "Enter a Start URL to preview."); return
        if not selector and not smart_mode and not keyword_hits_mode:
            messagebox.showwarning("Input Error", "Provide a CSS selector, enable Smart auto-detect, or enable Keyword hit finder."); return
        focus = {
            "keyword": self.keyword_var.get().strip(),
            "action": action_choice,
            "price": self.focus_price_var.get(),
            "reviews": self.focus_reviews_var.get(),
            "shipping": self.focus_shipping_var.get(),
        }
        self.log_queue.put(f"INFO: Previewing {start_url} without launching a browser...")
        threading.Thread(
            target=self._preview_worker,
            args=(start_url, selector, smart_mode, focus, self.images_var.get(), keyword_hits_mode, keyword_hits_limit),
            daemon=True,
        ).start()

    def _preview_worker(self, start_url, selector, smart_mode, focus, scrape_images, keyword_hits_mode, keyword_hits_limit):
        try:
            resp = httpx.get(start_url, headers=DEFAULT_HEADERS, follow_redirects=True, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            preview_items = []
            if selector:
                for el in soup.select(selector):
                    text = norm_space(el.get_text(" ", strip=True))
                    if not text: continue
                    link = ""
                    if anchor := el.find('a', href=True):
                        link = urljoin(start_url, anchor['href'])
                    preview_items.append({"Title": text[:200], "Price": "", "Link": link, "SourceURL": start_url})
                    if len(preview_items) >= 5: break
            elif smart_mode:
                config = {"focus_keyword": focus["keyword"], "focus_action": focus["action"], "focus_price": focus["price"],
                          "focus_reviews": focus["reviews"], "focus_shipping": focus["shipping"], "scrape_images": scrape_images}
                dummy = Crawler(config, self.log_queue, queue.Queue())
                for item in dummy.smart_extract(soup, start_url):
                    preview_items.append(item)
                    if len(preview_items) >= 5: break
            if keyword_hits_mode and focus["keyword"]:
                dummy_config = {
                    "scrape_images": scrape_images,
                    "keyword_hits_limit": keyword_hits_limit,
                    "focus_keyword": focus["keyword"],
                }
                dummy = Crawler(dummy_config, self.log_queue, queue.Queue())
                for item in dummy.keyword_hits(soup, start_url, focus["keyword"]):
                    preview_items.append(item)
                    if len(preview_items) >= 5: break
            if preview_items:
                self.log_queue.put(f"INFO: Preview found {len(preview_items)} item(s). Showing up to 5.")
                for item in preview_items:
                    title = norm_space(item.get("Title", ""))[:140]
                    price = item.get("Price") or "-"
                    link = item.get("Link") or item.get("SourceURL") or ""
                    self.log_queue.put(f"PREVIEW: {title} | Price={price} | Link={link}")
            else:
                self.log_queue.put("INFO: No preview matches found with current selector/settings.")
        except Exception as e:
            self.log_queue.put(f"ERROR: Preview failed for {start_url}: {e}")
            self.master.after(0, lambda: messagebox.showerror("Preview Error", f"Could not preview {start_url}:\n{e}"))

    def start_scraping(self):
        # Init DB ID
        self.current_session_id = str(uuid.uuid4())
        mode = self.mode_var.get()
        kw = self.osint_keyword_var.get() if mode == "osint" else (self.url_var.get() or self.keyword_var.get())
        if kw: self.db.create_session(self.current_session_id, kw, mode)

        start_urls = []
        keyword = ""
        osint_enabled = self.osint_var.get()
        dork_type = None
        
        # Override settings based on mode
        if mode == "shopping":
            raw = self.url_var.get().strip()
            if raw.startswith(("http://", "https://")):
                start_urls = [raw]
            else:
                keyword = raw
                if not start_urls: osint_enabled = True # Use search if no URL
            
            # Shopping Defaults
            self.smart_var.set(True)
            self.action_var.set(self.action_var.get() or "balanced")
            
        elif mode == "osint":
            keyword = self.osint_keyword_var.get().strip()
            osint_enabled = True
            dork_type = self.dork_var.get()
            self.smart_var.set(True)
            # Disable shopping noise
            self.focus_price_var.set(False)
            
        elif mode == "custom":
            raw_text = self.url_text.get("1.0", END).strip()
            start_urls = [u.strip() for u in raw_text.split("\n") if u.strip()]
            keyword = self.keyword_var.get().strip()
            # Respect checkboxes in Custom tab
        
        # Common Logic
        keyword_hits_mode = self.keyword_hits_var.get() or self.action_var.get() == "keyword_hits"
        if mode == "osint" and keyword:
            keyword_hits_mode = True
        action_choice = "keyword_hits" if keyword_hits_mode else self.action_var.get()
        
        try:
            keyword_hits_limit = max(5, int(self.keyword_limit_var.get()))
        except:
            keyword_hits_limit = 120

        if not start_urls and osint_enabled and not keyword:
             messagebox.showwarning("Input Error", "Enter a keyword or URL."); return

        if not start_urls and not osint_enabled:
             messagebox.showwarning("Input Error", "Enter a Start URL."); return

        config = { 
            "urls": start_urls, 
            "keyword": keyword, # Used for OSINT search
            "focus_keyword": keyword, # Used for scoring
            "focus_action": action_choice,
            "focus_price": self.focus_price_var.get(), 
            "focus_reviews": self.focus_reviews_var.get(), 
            "focus_shipping": self.focus_shipping_var.get(),
            "smart_mode": self.smart_var.get(),
            "css_selector": self.selector_entry.get().strip(), 
            "osint_mode": osint_enabled, 
            "scrape_images": self.images_var.get(),
            "keyword_hits_mode": keyword_hits_mode, 
            "keyword_hits_limit": keyword_hits_limit,
            "max_pages": int(self.strength_var.get()), 
            "user_agent": DEFAULT_HEADERS['User-Agent'], 
            "use_ai": self.ai_var.get(), 
            "api_key": self.api_key_entry.get(), 
            "is_running_check": lambda: self.is_running,
            "page_timeout": int(self.timeout_var.get()), 
            "delay": float(self.delay_var.get()),
            "allow_external": self.allow_external_var.get(),
            "dork_type": dork_type,
            "asset_metadata_limit": 5,
        }
        
        self.clear_results(); self.scrape_btn.config(state=DISABLED); self.stop_btn.config(state=NORMAL); self.is_running = True
        self.run_started_at = datetime.now()
        self.pages_crawled = 0
        self.queue_size = 0
        self._elapsed_at_stop = 0
        self._seen_items.clear()
        self._update_stats()
        
        self.log_queue.put(f"INFO: Mode='{mode}' | Intent='{keyword}' | OSINT={osint_enabled}")
        self.log_queue.put("--- Starting crawl job ---")
        self.scrape_thread = threading.Thread(target=scrape_controller, args=(config, self.log_queue, self.scrape_queue), daemon=True)
        self.scrape_thread.start()
        self.master.after(100, self._check_thread)

    def _check_thread(self):
        if self.scrape_thread and self.scrape_thread.is_alive(): self.master.after(100, self._check_thread)
        else:
            if self.is_running: self.log_queue.put("--- Crawl finished ---")
            if self.run_started_at:
                self._elapsed_at_stop = int((datetime.now() - self.run_started_at).total_seconds())
                self.run_started_at = None
            self.is_running = False; self.scrape_btn.config(state=NORMAL); self.stop_btn.config(state=DISABLED); self._update_stats()

    def stop_scraping(self):
        if self.is_running: self.is_running = False; self.log_queue.put("--- Sending stop signal ---"); self.stop_btn.config(state=DISABLED)
    def clear_results(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        self._all_results_cache.clear()
        self._seen_items.clear()
        self.filter_var.set("")
        self.run_started_at = None
        self._elapsed_at_stop = 0
        self.pages_crawled = 0
        self.queue_size = 0
        self._update_stats()
        self.log_queue.put("--- Cleared results ---")
    def show_context_menu(self, event):
        if iid := self.tree.identify_row(event.y):
            self.tree.selection_set(iid)
            menu = ttk.Menu(self, tearoff=0)
            if item := self.tree.item(iid):
                vals = item.get('values') or []
                link = ""
                if len(vals) > 6 and vals[6]:
                    link = vals[6]
                elif len(vals) > 8 and vals[8]:
                    link = vals[8]
                if link:
                    menu.add_command(label="Open Link in Browser", command=lambda: webbrowser.open_new_tab(link))
                menu.add_command(label="Copy row to clipboard", command=lambda vals=vals: self.copy_row_to_clipboard(vals))
                if len(vals) > 6 and vals[6]: # Link
                    menu.add_command(label="Add to Watchdog (Monitor Price)", command=lambda: self._quick_watch(vals[6], vals[2]))
            menu.post(event.x_root, event.y_root)

    def _quick_watch(self, url, price):
        # Clean price
        try:
            p = float(re.sub(r'[^\d.]', '', str(price)))
            target = p * 0.9 # Alert on 10% drop
            self.db.add_watch_item(url, str(target), target, "price")
            messagebox.showinfo("Watchdog", f"Monitoring {url} for price drop below {target}")
        except:
             # Fallback to keyword
             self.db.add_watch_item(url, "Out of Stock", 0, "keyword")
             messagebox.showinfo("Watchdog", "Monitoring page for changes (Price parsing failed).")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gemini Scraper")
    parser.add_argument("--server", action="store_true", help="Run in API Server mode (Headless)")
    parser.add_argument("--port", type=int, default=5000, help="Port for API Server (default: 5000)")
    args = parser.parse_args()

    if args.server:
        try:
            from server import start_server
            print(f"Starting API Server on port {args.port}...")
            start_server(args.port)
        except ImportError as e:
            print(f"Failed to load server module: {e}")
            sys.exit(1)
    else:
        root = ttk.Window(themename="superhero")
        ScraperGUI(root)
        root.mainloop()
