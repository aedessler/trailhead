"""
core.py — the engine for the Link Summarizer & Semantic Search app.

This module has NO user interface. It does four things:
  1. Fetch a web page and extract its readable text.
  2. Summarize that text with the TAMU LLM (OpenAI-compatible endpoint).
  3. Turn text into an embedding vector with a small local model.
  4. Store/search entries in a local SQLite database.

Keeping the logic here (separate from app.py) means you can test the whole
pipeline from a plain terminal without launching the web UI. See the
`if __name__ == "__main__"` block at the bottom for a quick smoke test.
"""

import glob
import os
import re
import sqlite3
from datetime import datetime, timezone

import numpy as np
import requests
import trafilatura
from dotenv import load_dotenv
from openai import OpenAI

# Load keys from the .env file. override=True makes the .env file authoritative,
# so it wins over any stale key that may already be exported in your shell
# (e.g. an old OPENAI_API_KEY in ~/.zshrc).
load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Which LLM provider to use for summaries. Flip this between "openai" and "tamu".
# (Embeddings/search always run locally and are unaffected by this switch.)
LLM_PROVIDER = "tamu"

# --- OpenAI (api.openai.com) ---
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_MODEL = "gpt-4o"
OPENAI_KEY_ENV = "OPENAI_API_KEY"  # env var / .env name that holds the key

# --- TAMU AI (OpenAI-compatible endpoint) ---
TAMU_BASE_URL = "https://chat-api.tamu.ai/openai"
TAMU_MODEL = "protected.Claude Sonnet 4.6"
TAMU_KEY_ENV = "TAMU_AI_API_KEY"


def _provider_config() -> tuple[str, str, str]:
    """Return (base_url, model, key_env_var) for the selected LLM_PROVIDER."""
    if LLM_PROVIDER == "openai":
        return OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_KEY_ENV
    if LLM_PROVIDER == "tamu":
        return TAMU_BASE_URL, TAMU_MODEL, TAMU_KEY_ENV
    raise RuntimeError(
        f"LLM_PROVIDER is '{LLM_PROVIDER}', but must be 'openai' or 'tamu'."
    )

# Local embedding model. Small (~80 MB), runs offline, downloaded once on first
# use and then cached by sentence-transformers under ~/.cache.
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"

# Where the SQLite database lives — next to this file, so it travels with the app.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library.db")

# Cap how much page text we send to the LLM, to stay fast and within limits.
MAX_CHARS_FOR_SUMMARY = 12000


# ---------------------------------------------------------------------------
# 1. Fetching web pages
# ---------------------------------------------------------------------------

# A realistic browser header set. Some sites return junk or block requests that
# only send a python-requests (or bare User-Agent) signature, so we mimic the
# full set of headers a real Chrome browser sends. This won't defeat JavaScript
# challenges (Cloudflare et al.), but it gets past naive bot filters that only
# sniff for missing headers.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


# Google Drive "view" links (…/file/d/<ID>/view) serve a JavaScript shell, not
# the file itself, so fetching them yields no readable text. Match the file ID so
# we can rewrite them to a direct-download URL that returns the actual bytes.
_DRIVE_FILE_RE = re.compile(r"drive\.google\.com/file/d/([^/]+)")
_DRIVE_OPEN_RE = re.compile(r"drive\.google\.com/open\?id=([^&]+)")


def _normalize_url(url: str) -> str:
    """Rewrite known wrapper URLs to a fetchable direct-download form.

    Currently handles Google Drive share links, turning the JavaScript "view"
    page into the direct-download endpoint so the normal (PDF) fetch path works.
    Other URLs pass through unchanged.
    """
    match = _DRIVE_FILE_RE.search(url) or _DRIVE_OPEN_RE.search(url)
    if match:
        return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
    return url


def fetch_page(url: str) -> tuple[str, str]:
    """Download `url` and return (title, clean_text).

    Uses trafilatura to strip navigation, ads, and boilerplate so the LLM only
    sees the actual article content. Raises a ValueError if no usable text was
    found (e.g. a page rendered entirely by JavaScript).
    """
    url = _normalize_url(url)
    response = requests.get(url, headers=_BROWSER_HEADERS, timeout=30)
    response.raise_for_status()

    # PDFs aren't HTML — trafilatura can't read them. Detect a PDF by the
    # server's Content-Type, the URL path ending in .pdf, or the file's magic
    # bytes (%PDF) — the last catches downloads served as octet-stream, e.g.
    # Google Drive. Then extract its text layer so the rest of the pipeline works.
    content_type = response.headers.get("Content-Type", "").lower()
    path = url.split("?", 1)[0].lower()
    if (
        "application/pdf" in content_type
        or path.endswith(".pdf")
        or response.content[:5] == b"%PDF-"
    ):
        return _extract_pdf(response.content, url)

    html = response.text

    # Extract the main readable text.
    text = trafilatura.extract(html, include_comments=False, include_tables=False)

    # Extract a title (falls back to the URL if none is found).
    title = url
    metadata = trafilatura.extract_metadata(html)
    if metadata and metadata.title:
        title = metadata.title

    if not text or not text.strip():
        raise ValueError(
            "Could not extract readable text from this page. It may rely on "
            "JavaScript to render its content."
        )

    return title, text.strip()


def _extract_pdf(data: bytes, url: str) -> tuple[str, str]:
    """Extract (title, text) from raw PDF bytes.

    Reads the PDF's text layer page by page. Raises ValueError if there's no
    extractable text (e.g. a scanned, image-only PDF), so callers fall back to
    manual entry just as they do for JavaScript-only pages.
    """
    # Imported here (not at top) so the parser only loads when a PDF is actually
    # fetched, matching the lazy-import style used for sentence-transformers.
    import io
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)

    # PDF metadata sometimes carries a title; fall back to the URL otherwise.
    title = url
    meta = reader.metadata
    if meta and meta.title and meta.title.strip():
        title = meta.title.strip()

    if not text.strip():
        raise ValueError(
            "This PDF has no extractable text — it may be a scanned image. "
            "You can paste the text or enter a summary yourself below."
        )
    return title, text.strip()


# ---------------------------------------------------------------------------
# 2. Summarizing with the TAMU LLM
# ---------------------------------------------------------------------------

# Build the OpenAI client once, lazily, so importing this module doesn't require
# the API key to be set (handy for running search-only or tests).
_llm_client: OpenAI | None = None


def _get_llm_client() -> OpenAI:
    global _llm_client
    if _llm_client is None:
        base_url, _, key_env = _provider_config()
        api_key = os.environ.get(key_env)
        if not api_key:
            raise RuntimeError(
                f"{key_env} is not set. Put it in a .env file or export it in your "
                f"shell (provider is currently '{LLM_PROVIDER}')."
            )
        _llm_client = OpenAI(base_url=base_url, api_key=api_key)
    return _llm_client


def summarize(text: str, model: str | None = None) -> str:
    """Summarize page text in 3-5 sentences using the selected LLM provider."""
    client = _get_llm_client()
    if model is None:
        _, model, _ = _provider_config()
    snippet = text[:MAX_CHARS_FOR_SUMMARY]

    response = client.chat.completions.create(
        model=model,
        stream=False,  # TAMU streams Claude models unless explicitly told not to
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a concise summarizer. Summarize the web page the "
                    "user provides in 3-5 sentences. Focus on the main topics, "
                    "themes, and takeaways so the summary is useful for later "
                    "semantic search. Do not add preamble like 'This page'. "
                    "After the summary, identify the author(s) of the content "
                    "and add a final line in exactly this format: "
                    "'Authors: <comma-separated names>'. If no author can be "
                    "determined from the text, write 'Authors: Unknown'."
                ),
            },
            {"role": "user", "content": snippet},
        ],
    )
    return response.choices[0].message.content.strip()


def suggest_title(text: str, model: str | None = None) -> str:
    """Ask the LLM for a short, descriptive title for the given text.

    Useful when there's no page title to extract (e.g. text pasted from a PDF).
    """
    client = _get_llm_client()
    if model is None:
        _, model, _ = _provider_config()

    response = client.chat.completions.create(
        model=model,
        stream=False,  # TAMU streams Claude models unless explicitly told not to
        messages=[
            {
                "role": "system",
                "content": (
                    "You write concise, descriptive titles. Reply with ONLY a "
                    "title (no quotes, no surrounding text, under 12 words) for "
                    "the content the user provides."
                ),
            },
            {"role": "user", "content": text[:4000]},
        ],
    )
    return response.choices[0].message.content.strip().strip('"')


def suggest_keywords(summary: str, n: int = 6, model: str | None = None) -> list[str]:
    """Ask the LLM for a few short topical keywords describing the content.

    Returns a list of lowercase tags (possibly empty if parsing fails). Callers
    should treat failure gracefully — keywords are a convenience, not required.
    """
    client = _get_llm_client()
    if model is None:
        _, model, _ = _provider_config()

    response = client.chat.completions.create(
        model=model,
        stream=False,  # TAMU streams Claude models unless explicitly told not to
        messages=[
            {
                "role": "system",
                "content": (
                    "You extract concise topical keywords. Return ONLY a "
                    "comma-separated list of 4-6 short tags (1-3 words each), "
                    "lowercase, no numbering, no quotes, no other text."
                ),
            },
            {"role": "user", "content": summary[:4000]},
        ],
    )
    raw = response.choices[0].message.content.strip()

    keywords: list[str] = []
    for piece in raw.replace("\n", ",").split(","):
        kw = piece.strip().strip(".;-\"' ").lower()
        if kw and len(kw) <= 30 and kw not in keywords:
            keywords.append(kw)
    return keywords[:n]


# ---------------------------------------------------------------------------
# 3. Local embeddings (for semantic search)
# ---------------------------------------------------------------------------

_embed_model = None  # loaded lazily; importing sentence-transformers is slow


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        # Imported here (not at top) so the module loads fast and the heavy
        # ML import only happens when embeddings are actually needed.
        from sentence_transformers import SentenceTransformer

        _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    return _embed_model


def embed(text: str) -> np.ndarray:
    """Turn text into a normalized float32 vector."""
    model = _get_embed_model()
    # normalize_embeddings=True makes cosine similarity == a simple dot product.
    vector = model.encode(text, normalize_embeddings=True)
    return np.asarray(vector, dtype=np.float32)


# ---------------------------------------------------------------------------
# 4. SQLite storage + search
# ---------------------------------------------------------------------------


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the entries table if it doesn't exist. Safe to call every run."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                url        TEXT,
                title      TEXT,
                summary    TEXT,
                notes      TEXT,
                keywords   TEXT,
                embedding  BLOB,
                created_at TEXT
            )
            """
        )


BACKUP_DIR = os.path.join(os.path.dirname(DB_PATH), "backups")


def backup_database(keep: int = 10) -> str | None:
    """Make a timestamped, consistent copy of the database in ./backups.

    Uses SQLite's online backup API so the copy is safe even if a write were in
    progress. Keeps only the most recent `keep` backups. Returns the path of the
    backup created, or None if there's no database to back up yet.
    """
    if not os.path.exists(DB_PATH):
        return None  # nothing saved yet — nothing to back up

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"library-{stamp}.db")

    source = sqlite3.connect(DB_PATH)
    try:
        target = sqlite3.connect(dest)
        try:
            with target:
                source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    # Prune oldest backups beyond the keep limit (names sort chronologically).
    existing = sorted(glob.glob(os.path.join(BACKUP_DIR, "library-*.db")))
    for old in existing[:-keep]:
        try:
            os.remove(old)
        except OSError:
            pass

    return dest


def add_entry(
    url: str,
    title: str,
    summary: str,
    notes: str = "",
    keywords: str = "",
) -> int:
    """Save one entry. The embedding is computed from summary + keywords + notes
    so that your own tags and notes also influence search results.

    Returns the new row's id.
    """
    text_to_embed = "\n".join(p for p in (summary, keywords, notes) if p)
    vector = embed(text_to_embed)

    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO entries (url, title, summary, notes, keywords, embedding, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                title,
                summary,
                notes,
                keywords,
                vector.tobytes(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return cursor.lastrowid


def all_entries() -> list[dict]:
    """Return every saved entry (without the raw embedding), newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, url, title, summary, notes, keywords, created_at "
            "FROM entries ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def update_entry(
    entry_id: int,
    title: str,
    summary: str,
    notes: str = "",
    keywords: str = "",
) -> None:
    """Update an entry's editable fields and recompute its search embedding.

    The embedding is rebuilt from summary + keywords + notes (same recipe as
    add_entry) so edits to your tags/notes are reflected in future searches.
    """
    text_to_embed = "\n".join(p for p in (summary, keywords, notes) if p)
    vector = embed(text_to_embed)

    with _connect() as conn:
        conn.execute(
            """
            UPDATE entries
            SET title = ?, summary = ?, notes = ?, keywords = ?, embedding = ?
            WHERE id = ?
            """,
            (title, summary, notes, keywords, vector.tobytes(), entry_id),
        )


def get_entry_by_url(url: str) -> dict | None:
    """Return the saved entry with this exact URL, or None if it isn't saved."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, url, title, summary, notes, keywords, created_at "
            "FROM entries WHERE url = ?",
            (url,),
        ).fetchone()
    return dict(row) if row else None


def delete_entry(entry_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))


def search(query: str, top_k: int = 5) -> list[dict]:
    """Find the entries most similar in meaning to `query`.

    `query` can be a topic phrase OR a URL. If it looks like a URL we fetch and
    summarize it first, then search with that summary. Returns a list of dicts
    each with the entry fields plus a 'score' (cosine similarity, 0-1) and a
    'keyword_match' flag. Entries whose keywords match the query are ranked
    above all non-matches; ties (and non-matches) are ordered by 'score'.
    """
    query_text = query.strip()
    is_url = query_text.lower().startswith(("http://", "https://"))
    if is_url:
        _, page_text = fetch_page(query_text)
        query_text = summarize(page_text)
        # A URL query has no meaningful keyword term to match against.
        keyword_query = ""
    else:
        keyword_query = query.strip().lower()

    query_vec = embed(query_text)

    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, url, title, summary, notes, keywords, embedding, created_at "
            "FROM entries"
        ).fetchall()

    if not rows:
        return []

    # Reconstruct the stored vectors into one matrix and score them all at once.
    matrix = np.vstack(
        [np.frombuffer(row["embedding"], dtype=np.float32) for row in rows]
    )
    # Vectors are normalized, so the dot product IS the cosine similarity.
    scores = matrix @ query_vec

    results = []
    for row, score in zip(rows, scores):
        entry = {k: row[k] for k in row.keys() if k != "embedding"}
        entry["score"] = float(score)

        # Keyword match: the query matches one of the entry's stored keywords if
        # the query phrase contains a keyword, or a keyword contains the query.
        kws = [k.strip().lower() for k in (row["keywords"] or "").split(",") if k.strip()]
        entry["keyword_match"] = bool(keyword_query) and any(
            keyword_query in kw or kw in keyword_query for kw in kws
        )
        results.append(entry)

    # Keyword matches first, then by semantic similarity within each group.
    results.sort(key=lambda e: (e["keyword_match"], e["score"]), reverse=True)
    return results[:top_k]


# ---------------------------------------------------------------------------
# Quick headless smoke test:  python core.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    print("DB ready at:", DB_PATH)

    test_url = "https://en.wikipedia.org/wiki/Texas_A%26M_University"
    print(f"\nFetching: {test_url}")
    title, text = fetch_page(test_url)
    print("Title:", title)
    print("Chars extracted:", len(text))

    print(f"\nSummarizing with provider '{LLM_PROVIDER}'...")
    print(summarize(text))
