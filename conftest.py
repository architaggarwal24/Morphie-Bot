import os
import sys
import tempfile

# Ensure `import app`, `import config`, `from morphie...` resolve
# regardless of where pytest is invoked from.
sys.path.insert(0, os.path.dirname(__file__))

# Importing `app` builds the whole application (it opens the vector store and
# reads the secret file), so every path it touches is redirected to a temp
# location *before* anything imports app.py / config.py. Running the suite must
# never read or modify real user data in the project's data/ folder.
_TMP = tempfile.gettempdir()
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key-not-for-production-0123456789abcdef")
os.environ.setdefault("SECRET_KEY_FILE", os.path.join(_TMP, "morphie_bot_test_secret"))
os.environ.setdefault("RAG_VECTOR_STORE_PATH", os.path.join(_TMP, "morphie_bot_test_rag", "rag.sqlite3"))
os.environ.setdefault("RAG_UPLOAD_DIR", os.path.join(_TMP, "morphie_bot_test_rag", "documents"))
# The suite fires many requests from one address; rate limiting has its own tests.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
# Tests must be independent of whatever is in the developer's own .env file.
for _name in ("LLM_PROVIDER", "LLM_MODEL", "MISTRAL_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY"):
    os.environ.pop(_name, None)
