"""Guards on the Cloudflare deployment files, so a refactor can't silently break `pywrangler deploy`."""

import json
import re
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _jsonc(path):
    text = re.sub(r"^\s*//.*$", "", path.read_text(encoding="utf-8"), flags=re.M)  # whole-line comments only
    return json.loads(text)


def test_wrangler_config_points_at_the_worker_entry_and_enables_python_workers():
    cfg = _jsonc(ROOT / "wrangler.jsonc")
    assert (ROOT / cfg["main"]).is_file() and cfg["main"] == "src/worker.py"
    assert "python_workers" in cfg["compatibility_flags"]
    assert cfg["d1_databases"][0]["binding"] == "DB"
    assert cfg["assets"]["directory"] == "./public" and (ROOT / "public").is_dir()


def test_the_worker_pins_no_llm_provider_or_key_so_every_visitor_brings_their_own():
    cfg = _jsonc(ROOT / "wrangler.jsonc")
    assert not {"LLM_PROVIDER", "LLM_MODEL", "MISTRAL_API_KEY", "OPENAI_API_KEY"} & set(cfg.get("vars", {}))


def test_no_secret_is_committed_in_wrangler_vars():
    cfg = _jsonc(ROOT / "wrangler.jsonc")
    secretish = [k for k in cfg.get("vars", {}) if re.search(r"KEY|SECRET|TOKEN|PASSWORD", k)]
    assert secretish == []


def test_every_module_the_worker_imports_lives_under_src_so_it_gets_bundled():
    worker = (ROOT / "src" / "worker.py").read_text(encoding="utf-8")
    assert "from app import app" in worker and "wsgi.entrypoint(app)" in worker
    for name in ("app.py", "config.py"):
        assert (ROOT / "src" / name).is_file() and not (ROOT / name).exists()
    assert (ROOT / "src" / "morphie").is_dir() and not (ROOT / "morphie").exists()


def test_worker_dependencies_exclude_packages_that_cannot_run_in_pyodide():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    names = {re.split(r"[<>=!~ ]", d)[0].lower() for d in deps}
    assert {"flask", "pypdf", "python-docx"} <= names
    assert not names & {"requests", "httpx", "mistralai", "aiohttp"}
    assert "requests" in (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()  # still used for local runs


def test_the_d1_migration_creates_every_table_the_app_uses():
    conn = sqlite3.connect(":memory:")
    conn.executescript((ROOT / "migrations" / "0001_init.sql").read_text(encoding="utf-8"))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"documents", "chunks", "conversation_messages", "rate_buckets"} <= tables


def test_public_assets_are_in_sync_with_the_templates_and_static_files():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_public.py"), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout


def test_the_static_page_has_no_jinja_left_and_points_at_root_relative_assets():
    html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    assert "{{" not in html and "{%" not in html
    assert 'href="/static/app.css"' in html and 'src="/static/app.js"' in html


def test_the_static_headers_match_the_flask_apps_security_headers():
    import app as app_module

    flask_csp = app_module.app.test_client().get("/status").headers["Content-Security-Policy"]
    assert f"Content-Security-Policy: {flask_csp}" in (ROOT / "public" / "_headers").read_text(encoding="utf-8")


def test_the_source_never_imports_requests_or_the_mistral_sdk_directly():
    offenders = []
    for path in (ROOT / "src").rglob("*.py"):
        if path.name == "net.py":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.match(r"\s*(import|from)\s+(requests|httpx|mistralai)\b", line):
                offenders.append(f"{path.relative_to(ROOT)}: {line.strip()}")
    assert offenders == []


def test_nothing_in_src_needs_threads_on_the_worker_path():
    source = (ROOT / "src" / "app.py").read_text(encoding="utf-8")
    # The only Thread use is the non-Workers branch of /chat/stream.
    assert source.count("threading.Thread(") == 1
    assert source.index("if IS_WORKERS:", source.index("def generate")) < source.index("threading.Thread(")
