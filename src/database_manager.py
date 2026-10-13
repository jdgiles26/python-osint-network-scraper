import sqlite3
import json
from datetime import datetime
import os
import threading

class DatabaseManager:
    def __init__(self, db_path="scraper_data.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # Results table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    timestamp TEXT,
                    title TEXT,
                    price TEXT,
                    rating TEXT,
                    shipping TEXT,
                    link TEXT,
                    image_url TEXT,
                    source_url TEXT,
                    entities TEXT,
                    match_score REAL
                )
            ''')
            
            # Sessions/History table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    timestamp TEXT,
                    keyword TEXT,
                    mode TEXT,
                    total_items INTEGER
                )
            ''')
            
            # Watchlist table for monitoring
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT,
                    keyword TEXT,
                    target_price REAL,
                    mode TEXT,
                    last_check TEXT,
                    status TEXT
                )
            ''')
            
            conn.commit()
            conn.close()

    def save_result(self, session_id, item):
        """
        Save a single scrape result to the database.
        """
        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # Serialize entities dict to JSON string if present
            entities_str = json.dumps(item.get("Entities", {})) if item.get("Entities") else ""
            
            cursor.execute('''
                INSERT INTO results (
                    session_id, timestamp, title, price, rating, shipping, 
                    link, image_url, source_url, entities, match_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session_id,
                datetime.now().isoformat(),
                item.get("Title", ""),
                item.get("Price", ""),
                item.get("Rating", ""),
                item.get("Shipping", ""),
                item.get("Link", ""),
                item.get("ImageURL", ""),
                item.get("SourceURL", ""),
                entities_str,
                item.get("Match", 0)
            ))
            conn.commit()
            conn.close()

    def create_session(self, session_id, keyword, mode):
        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO sessions (session_id, timestamp, keyword, mode, total_items)
                VALUES (?, ?, ?, ?, 0)
            ''', (session_id, datetime.now().isoformat(), keyword, mode))
            conn.commit()
            conn.close()

    def update_session_count(self, session_id, count):
        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute('UPDATE sessions SET total_items = ? WHERE session_id = ?', (count, session_id))
            conn.commit()
            conn.close()
            
    def get_history(self):
        """Returns list of past scrape sessions."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM sessions ORDER BY timestamp DESC')
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_results_for_session(self, session_id):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM results WHERE session_id = ?', (session_id,))
        rows = cursor.fetchall()
        conn.close()
        
        # Convert back to list of dicts
        results = []
        columns = ["id", "session_id", "timestamp", "title", "price", "rating", "shipping", "link", "image_url", "source_url", "entities", "match_score"]
        for row in rows:
            mapped = dict(zip(columns, row))
            # Deserialize entities
            if mapped["entities"]:
                try:
                    mapped["entities"] = json.loads(mapped["entities"])
                except:
                    mapped["entities"] = {}
            else:
                mapped["entities"] = {}
            
            # Map back to internal keys Expected by GUI
            results.append({
                "Match": mapped["match_score"],
                "Title": mapped["title"],
                "Price": mapped["price"],
                "Rating": mapped["rating"],
                "Shipping": mapped["shipping"],
                "Entities": mapped["entities"],
                "Link": mapped["link"],
                "ImageURL": mapped["image_url"],
                "SourceURL": mapped["source_url"]
            })
        return results

    # --- Watchlist Operations ---
    def add_watch_item(self, url, keyword, target_price=0.0, mode="price"):
        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO watchlist (url, keyword, target_price, mode, last_check, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (url, keyword, target_price, mode, datetime.now().isoformat(), "active"))
            conn.commit()
            conn.close()

    def get_watchlist(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM watchlist')
        rows = cursor.fetchall()
        conn.close()
        return rows

    def delete_watch_item(self, item_id):
        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM watchlist WHERE id = ?', (item_id,))
            conn.commit()
            conn.close()

    def update_watch_timestamp(self, item_id):
        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute('UPDATE watchlist SET last_check = ? WHERE id = ?', (datetime.now().isoformat(), item_id))
            conn.commit()
            conn.close()
