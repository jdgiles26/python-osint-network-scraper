from flask import Flask, request, jsonify
import threading
import queue
import time
from main import scrape_controller, DEFAULT_HEADERS

app = Flask(__name__)

@app.route('/scrape', methods=['POST'])
def handle_scrape():
    """
    Endpoint to trigger a scrape job.
    Expects JSON body with:
    - urls: list of strings (optional if keyword provided)
    - keyword: string (optional if urls provided)
    - mode: "shopping" | "osint" | "custom" (default: shopping)
    - max_pages: int (default: 1)
    - ... other config keys supported by scrape_controller
    """
    data = request.json or {}
    
    # Defaults
    config = {
        "urls": data.get("urls", []),
        "keyword": data.get("keyword", ""),
        "focus_keyword": data.get("keyword", ""),
        "focus_action": data.get("action", "balanced"),
        "focus_price": data.get("focus_price", True),
        "focus_reviews": data.get("focus_reviews", True),
        "focus_shipping": data.get("focus_shipping", True),
        "smart_mode": data.get("smart_mode", True),
        "css_selector": data.get("css_selector", ""),
        "osint_mode": data.get("mode") == "osint",
        "scrape_images": data.get("scrape_images", True),
        "keyword_hits_mode": False,
        "keyword_hits_limit": int(data.get("keyword_hits_limit", 120)),
        "max_pages": int(data.get("max_pages", 5)),
        "user_agent": DEFAULT_HEADERS['User-Agent'],
        "use_ai": data.get("use_ai", False),
        "api_key": data.get("api_key", ""),
        "is_running_check": lambda: True, # Always run until finished
        "page_timeout": 20,
        "delay": 0.5,
        "allow_external": False,
        "dork_type": data.get("dork_type")
    }

    if config["osint_mode"] and config["keyword"]:
        config["keyword_hits_mode"] = True

    if not config["urls"] and not config["keyword"]:
        return jsonify({"error": "Must provide 'urls' or 'keyword'"}), 400

    log_queue = queue.Queue()
    scrape_queue = queue.Queue()
    results = []
    logs = []

    # Run scraper in a separate thread
    scraper_thread = threading.Thread(
        target=scrape_controller, 
        args=(config, log_queue, scrape_queue)
    )
    scraper_thread.start()
    
    # Collect results - simple synchronous wait for MVP
    # In a real production app, this should be async with job IDs, but for this task:
    # We wait until the thread dies or a reasonable timeout
    
    max_duration = 60 # seconds hard limit for API request
    start_time = time.time()
    
    while scraper_thread.is_alive():
        if time.time() - start_time > max_duration:
            break
            
        # Drain queues
        try:
            while True:
                log = log_queue.get_nowait()
                logs.append(log)
        except queue.Empty:
            pass
            
        try:
            while True:
                item = scrape_queue.get_nowait()
                results.append(item)
        except queue.Empty:
            pass
            
        time.sleep(0.1)

    # One final drain
    try:
        while not scrape_queue.empty(): results.append(scrape_queue.get_nowait())
        while not log_queue.empty(): logs.append(log_queue.get_nowait())
    except: pass

    return jsonify({
        "status": "completed" if not scraper_thread.is_alive() else "timeout",
        "count": len(results),
        "results": results,
        "logs": logs[-10:] # Return last 10 logs
    })

def start_server(port=5000):
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    start_server()
