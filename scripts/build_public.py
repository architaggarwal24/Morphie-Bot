"""Build public/ (the files Cloudflare serves directly, and Flask serves locally) from the React app in web/.

    python scripts/build_public.py          npm install (if needed) + vite build into public/
    python scripts/build_public.py --check  exit 1 if public/ is missing, broken, or its headers drift from Flask's

public/ is committed, so deploying never needs Node. `_headers` (source: web/public/_headers) re-applies the same
security headers the Flask app adds to its own responses.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
OUT = ROOT / "public"

CSP = "script-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'"


def problems() -> list[str]:
    found = []
    index = OUT / "index.html"
    if not index.is_file():
        return ["public/index.html is missing; run: python scripts/build_public.py"]
    html = index.read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
    if not any(r.endswith(".js") for r in refs) or not any(r.endswith(".css") for r in refs):
        found.append("public/index.html does not reference a built JS and CSS bundle")
    for ref in refs:
        if not (OUT / ref.lstrip("/")).is_file():
            found.append(f"public/index.html references {ref}, which does not exist")
    if re.search(r"<script\b[^>]*>(?!\s*</script>)\s*\S", html):
        found.append("public/index.html contains an inline <script>; the CSP would block it")
    if "/src/main.tsx" in html:
        found.append("public/index.html is the unbuilt dev page")
    headers = OUT / "_headers"
    if not headers.is_file() or f"Content-Security-Policy: {CSP}" not in headers.read_text(encoding="utf-8"):
        found.append("public/_headers is missing or its CSP differs from the Flask app's")
    src_headers = WEB / "public" / "_headers"
    if headers.is_file() and src_headers.is_file() and headers.read_bytes() != src_headers.read_bytes():
        found.append("public/_headers differs from web/public/_headers; rebuild")
    return found


def main() -> int:
    if "--check" in sys.argv:
        issues = problems()
        for issue in issues:
            print(issue)
        return 1 if issues else 0
    npm = shutil.which("npm")
    if not npm:
        print("npm was not found. Install Node.js 20+ to build the web UI.")
        return 1
    if not (WEB / "node_modules").is_dir():
        subprocess.run([npm, "install"], cwd=WEB, check=True)
    subprocess.run([npm, "run", "build"], cwd=WEB, check=True)
    issues = problems()
    for issue in issues:
        print(issue)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
