"""Cloudflare Workers entry point (Python Workers).

Cloudflare runs the Flask app through its built-in WSGI server. Everything else (settings, D1, the provider) is
set up per request by `_WorkersBootstrap` in app.py. Nothing here runs when you start the app locally with
`python src/app.py`.
"""

from workers import wsgi

from app import app

Default = wsgi.entrypoint(app)
