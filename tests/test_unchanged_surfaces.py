import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import database_manager
import osint_helper


def test_dorks_and_apply_dork_stay_put():
    assert set(osint_helper.DORKS) == {"files", "configs", "social", "login", "directory", "email_lists"}
    assert osint_helper.apply_dork("acme", "files") == "acme (ext:pdf OR ext:docx OR ext:xlsx OR ext:pptx OR ext:txt)"
    assert osint_helper.apply_dork("acme", "not-a-dork") == "acme"


def test_start_sh_bytes_stay_put():
    digest = hashlib.sha256((ROOT / "start.sh").read_bytes()).hexdigest()
    assert digest == "31b6cd1a6a952aecce53c3b5292e61fed20618f1f46fc09fcb808968c24b431a"


def test_entities_round_trip_uses_the_current_truthy_rule(tmp_path):
    db = database_manager.DatabaseManager(str(tmp_path / "scrape.db"))
    db.save_result("s1", {"Entities": {"email": ["ada@example.com"]}, "Title": "Example", "SourceURL": "https://example.com/a"})
    db.save_result("s1", {"Entities": {}, "Title": "Empty"})
    rows = {row["Title"]: row["Entities"] for row in db.get_results_for_session("s1")}
    assert rows["Example"] == {"email": ["ada@example.com"]}
    assert rows["Empty"] == {}
    with sqlite3.connect(tmp_path / "scrape.db") as conn:
        stored = [row[0] for row in conn.execute("SELECT entities FROM results ORDER BY id")]
    assert stored[0] == json.dumps({"email": ["ada@example.com"]})
    assert stored[1] == ""


def test_package_import_and_legacy_src_path_imports():
    package = subprocess.run([sys.executable, "-c", "import src.domain.graph"], cwd=ROOT, capture_output=True, text=True)
    assert package.returncode == 0, package.stderr
    legacy = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, 'src'); import osint_helper; import database_manager"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert legacy.returncode == 0, legacy.stderr
