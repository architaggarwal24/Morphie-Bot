"""Generate public/ (the files Cloudflare serves directly) from the Flask templates and static folder.

    python scripts/build_public.py          write public/
    python scripts/build_public.py --check  exit 1 if public/ is out of date (used by the test-suite)

The page has only two Jinja expressions (the CSS and JS URLs), so rendering it is a plain substitution. Cloudflare
serves these files before the Worker runs, so the page needs no Python at all; `_headers` re-applies the same
security headers the Flask app adds to its own responses.
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
OUT = ROOT / "public"

HEADERS = """/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: no-referrer
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  Content-Security-Policy: script-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'
"""


def render_index() -> str:
    html = (SRC / "templates" / "chatbot.html").read_text(encoding="utf-8")
    html = html.replace("{{ url_for('static', filename='app.css') }}", "/static/app.css")
    html = html.replace("{{ url_for('static', filename='app.js') }}", "/static/app.js")
    if "{{" in html or "{%" in html:
        raise SystemExit("chatbot.html contains Jinja this script doesn't know how to render; extend build_public.py.")
    return html


def expected_files() -> dict[str, bytes]:
    files = {
        "index.html": render_index().encode("utf-8"),
        "_headers": HEADERS.encode("utf-8"),
    }
    for path in sorted((SRC / "static").rglob("*")):
        if path.is_file():
            files["static/" + path.relative_to(SRC / "static").as_posix()] = path.read_bytes()
    return files


def main() -> int:
    files = expected_files()
    if "--check" in sys.argv:
        for name, data in files.items():
            target = OUT / name
            if not target.exists() or target.read_bytes() != data:
                print(f"public/{name} is out of date; run: python scripts/build_public.py")
                return 1
        return 0
    if OUT.exists():
        shutil.rmtree(OUT)
    for name, data in files.items():
        target = OUT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    print(f"Wrote {len(files)} files to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
