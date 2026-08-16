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

import base64
import glob
import hashlib
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
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

# The app's version, and the ONLY place it is written down — app.py, the README
# and the git tag all take their number from here, because a version string
# copied into a second file always drifts out of step with the first.
# Bump the minor part for new features and fixes, the major part for a release
# big enough that you'd tell someone about it. Tag each release in git to match
# (`git tag -a v2.0`), so an old version stays downloadable.
__version__ = "2.2"

# Which LLM provider to use for summaries: "openai", "tamu", or "none".
# "none" skips all LLM calls (summary/title/keywords come back empty for you to
# fill in by hand). Embeddings/search always run locally and are unaffected.
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
        f"LLM_PROVIDER is '{LLM_PROVIDER}', but must be 'openai', 'tamu', or "
        "'none'."
    )

# Local embedding model. Small (~80 MB), runs offline, downloaded once on first
# use and then cached by sentence-transformers under ~/.cache. Every later run
# loads that cached copy and never contacts the network — see _get_embed_model()
# for why that matters beyond speed.
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"

# Where the SQLite database lives — next to this file, so it travels with the app.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library.db")

# Saved image files live beside the database, in their own folder. The database
# stores only the FILENAME, so the whole project folder can be moved or renamed
# without breaking anything.
IMAGE_DIR = os.path.join(os.path.dirname(DB_PATH), "images")

# Cap how much page text we send to the LLM, to stay fast and within limits.
MAX_CHARS_FOR_SUMMARY = 12000

# Longest edge (pixels) of the copy sent to the vision model. Big screenshots
# cost a lot of tokens for no extra insight, so shrink a COPY for the API call
# while the saved file keeps its original resolution.
MAX_IMAGE_EDGE_FOR_LLM = 1568

# Ceiling on an image downloaded from a URL. A mistyped address can point at
# something enormous, and unlike a file picker there's no dialog showing what
# you're about to pull in — so the download stops rather than filling memory.
MAX_IMAGE_BYTES = 25 * 1024 * 1024


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


# The image formats the app stores. save_image() only trusts these extensions,
# so the file picker's list and the URL fetcher's checks both derive from here
# rather than repeating the set in three places that could drift apart.
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")

# What a server's Content-Type maps to on disk, and what Pillow's detected
# format maps to when the server doesn't say (or says something unhelpful like
# application/octet-stream, which plenty of CDNs do).
_CONTENT_TYPE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
_PIL_FORMAT_EXTENSIONS = {
    "PNG": ".png",
    "JPEG": ".jpg",
    "GIF": ".gif",
    "WEBP": ".webp",
}


def _sniff_image_extension(data: bytes) -> str | None:
    """The file extension for these bytes, judged by content — None if not an image.

    Used when the server's Content-Type is missing or wrong. Pillow reads the
    magic bytes, which is the only claim about a downloaded file worth
    believing. Formats the app doesn't store (BMP, TIFF, SVG…) return None
    rather than being saved under a lying .png extension.
    """
    try:
        import io

        from PIL import Image

        return _PIL_FORMAT_EXTENSIONS.get(Image.open(io.BytesIO(data)).format or "")
    except Exception:
        return None


def fetch_image(url: str) -> tuple[bytes, str]:
    """Download an image from `url` and return (bytes, filename).

    The mirror image of an upload: callers get exactly what a file picker gives
    them, so saving and describing take the identical path from there on.

    Raises ValueError with an explanation the user can act on — the common
    mistake is pasting the address of the *page* containing an image rather than
    the image itself, which is worth naming rather than reporting as a bad file.
    """
    url = _normalize_url(url.strip())
    response = requests.get(url, headers=_BROWSER_HEADERS, timeout=30, stream=True)
    response.raise_for_status()

    declared = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if declared.startswith("text/"):
        raise ValueError(
            "That address is a web page, not an image file. Right-click the "
            "image itself and choose 'Copy Image Address', then paste that."
        )

    # Streamed with a running total, so an address that turns out to point at
    # something huge is abandoned partway rather than after it's all in memory.
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_IMAGE_BYTES:
            response.close()
            raise ValueError(
                f"That image is bigger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB, "
                "so it wasn't downloaded."
            )
    data = b"".join(chunks)
    if not data:
        raise ValueError("That address returned an empty file.")

    extension = _CONTENT_TYPE_EXTENSIONS.get(declared) or _sniff_image_extension(data)
    if extension is None:
        raise ValueError(
            "That address didn't return a picture in a format Trailhead saves "
            f"({', '.join(IMAGE_EXTENSIONS)}). Save it to your computer and "
            "upload the file instead."
        )

    # Only the extension of this name is kept by save_image(), but the rest of
    # it becomes the fallback title in the review form, so a real filename from
    # the URL beats a generic one.
    name = os.path.basename(url.split("?", 1)[0]) or "image"
    if not name.lower().endswith(extension):
        name = f"{os.path.splitext(name)[0] or 'image'}{extension}"
    return data, name


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
    if LLM_PROVIDER == "none":
        return ""  # no LLM configured — the user writes the summary by hand
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


def _image_data_uri(data: bytes) -> str:
    """Shrink an image and return it as a base64 data URI for the vision API.

    Anything larger than MAX_IMAGE_EDGE_FOR_LLM is scaled down and re-encoded as
    PNG; the caller's original bytes are untouched. If the image can't be parsed
    (or Pillow is somehow unavailable) the original bytes are sent as-is, which
    still works for normal-sized files.
    """
    mime = "image/png"
    try:
        import io

        from PIL import Image  # ships with Streamlit; no extra dependency

        img = Image.open(io.BytesIO(data))
        if max(img.size) > MAX_IMAGE_EDGE_FOR_LLM:
            img.thumbnail((MAX_IMAGE_EDGE_FOR_LLM, MAX_IMAGE_EDGE_FOR_LLM))
        # Flatten transparency/palette modes onto white so PNG encoding is safe.
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        data = buffer.getvalue()
    except Exception:
        pass  # fall back to the bytes we were given

    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def summarize_image(data: bytes, model: str | None = None) -> str:
    """Describe what an image shows, for later semantic search.

    Takes the raw bytes of an image file and returns a few sentences describing
    it. Both supported providers use vision-capable models, and both accept the
    OpenAI-style "image_url" content block with a base64 data URI.
    """
    if LLM_PROVIDER == "none":
        return ""  # no LLM configured — the user writes the description by hand
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
                    "You describe images so they can be found later by a "
                    "semantic search. In 3-5 sentences, say what the image "
                    "shows: the subject, the kind of figure (chart, map, "
                    "photo, diagram, screenshot), what any axes or labels "
                    "measure, and the main takeaway a reader would draw from "
                    "it. Transcribe a title or caption if one is visible. Do "
                    "not add preamble like 'This image'."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image."},
                    {
                        "type": "image_url",
                        "image_url": {"url": _image_data_uri(data)},
                    },
                ],
            },
        ],
    )
    return response.choices[0].message.content.strip()


def suggest_title(text: str, model: str | None = None) -> str:
    """Ask the LLM for a short, descriptive title for the given text.

    Useful when there's no page title to extract (e.g. text pasted from a PDF).
    """
    if LLM_PROVIDER == "none":
        return ""  # no LLM configured — caller falls back to the page title
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
    if LLM_PROVIDER == "none":
        return []  # no LLM configured — the user adds their own keywords
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

        # Load from the local cache and don't contact Hugging Face at all. The
        # obvious reason is speed — the model is already on disk, so the network
        # round-trip only ever confirmed that. The real reason is that every
        # vector in library.db was produced by the cached copy: if a newer
        # revision were ever published and quietly downloaded, new embeddings
        # would land in a different vector space than the old ones and search
        # would degrade with no error to explain it. Pinning to what's cached
        # keeps the whole library comparable.
        #
        # The fallback covers the one case where there's nothing to load from:
        # a first run (or a cleared cache), where the model does need fetching.
        try:
            _embed_model = SentenceTransformer(EMBED_MODEL_NAME, local_files_only=True)
        except Exception:
            _embed_model = SentenceTransformer(EMBED_MODEL_NAME)

        # Now that it's loaded, fingerprinting it is nearly free. Wrapped
        # because this is a diagnostic: one that could stop you searching would
        # be worse than not having it.
        try:
            _fingerprint_model(_embed_model)
        except Exception:
            pass
    return _embed_model


def embed(text: str) -> np.ndarray:
    """Turn text into a normalized float32 vector."""
    model = _get_embed_model()
    # normalize_embeddings=True makes cosine similarity == a simple dot product.
    vector = model.encode(text, normalize_embeddings=True)
    return np.asarray(vector, dtype=np.float32)


# ---------------------------------------------------------------------------
# 3b. The embedding-model stamp
# ---------------------------------------------------------------------------
#
# A stored vector is a bare list of floats: nothing in it records which model
# produced it. That matters because two models put the same text in different
# places, so mixing vintages inside one library makes search quietly worse with
# no error to explain it. Swapping to a model of a *different* width at least
# crashes when the vectors are stacked; a retrained model of the same width
# doesn't even do that. So the library records what built its vectors, and the
# app checks that record against the model in use.

# A fixed sentence pushed through the model to fingerprint it. Comparing the
# name alone would miss the dangerous case — same name, retrained weights —
# because only the output reveals that.
EMBED_PROBE_TEXT = "Trailhead identifies its embedding model with this sentence."

# Cosine similarity at or above this counts as the same model. Deliberately not
# an equality test: the same model on a different Mac, or under a newer torch,
# can differ in the last few bits, and that must not read as a model change. A
# genuinely different model lands nowhere near this.
_PROBE_MATCH_FLOOR = 0.999

# Filled in the first time the model is loaded in this process; read by
# embedding_health(), which is called far too often to load a model itself.
_probe_verdict: dict | None = None


def _meta_get(conn: sqlite3.Connection, key: str) -> bytes | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _meta_set(conn: sqlite3.Connection, key: str, value: bytes) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _stored_dim(conn: sqlite3.Connection) -> int | None:
    """How wide the vectors in the table actually are, from one blob's length.

    Reads a length rather than a vector, so this stays cheap enough to call on
    every launch, and it reports the truth on disk rather than what the stamp
    claims — which is the whole point of having something to compare.
    """
    row = conn.execute(
        "SELECT LENGTH(embedding) AS n FROM entries "
        "WHERE embedding IS NOT NULL LIMIT 1"
    ).fetchone()
    return row["n"] // 4 if row and row["n"] else None


def _fingerprint_model(model) -> None:
    """Record the loaded model's fingerprint, or check it against the stored one.

    Called once per process, right after the model loads, because that's when a
    probe costs a few milliseconds instead of a five-second model load. A
    library with no fingerprint yet gets one written here.

    Nothing in here may raise: this is a diagnostic, and a diagnostic that can
    break searching is worse than no diagnostic at all.
    """
    global _probe_verdict
    with _connect() as conn:
        stored_text = _meta_get(conn, "embed_probe_text")
        stored = _meta_get(conn, "embed_probe")

        # Re-embed the sentence that was STORED, not the current constant, so
        # that editing EMBED_PROBE_TEXT later can't make every existing library
        # look as though its model changed.
        text = stored_text.decode() if stored_text else EMBED_PROBE_TEXT
        vector = np.asarray(
            model.encode(text, normalize_embeddings=True), dtype=np.float32
        )

        if stored is None:
            _meta_set(conn, "embed_probe_text", text.encode())
            _meta_set(conn, "embed_probe", vector.tobytes())
            _meta_set(conn, "embed_dim", str(int(vector.shape[0])).encode())
            _meta_set(conn, "embed_model", EMBED_MODEL_NAME.encode())
            return

        previous = np.frombuffer(stored, dtype=np.float32)
        if previous.shape != vector.shape:
            _probe_verdict = {
                "kind": "dimension",
                "message": (
                    f"The model in use produces {vector.shape[0]}-number vectors, "
                    f"but this library's are {previous.shape[0]}. Searching will "
                    "fail outright until every entry is re-embedded."
                ),
            }
            return

        similarity = float(previous @ vector)
        if similarity < _PROBE_MATCH_FLOOR:
            _probe_verdict = {
                "kind": "weights",
                "message": (
                    f"'{EMBED_MODEL_NAME}' still has its old name but no longer "
                    "produces the vectors this library was built with, so it has "
                    "been retrained or replaced. Search still runs, but entries "
                    "saved before now rank badly. Re-embed every entry to fix it."
                ),
            }


def embedding_health() -> dict:
    """What built this library's vectors, and whether that still matches.

    Cheap by design — it reads the stamp and one blob length, never a model —
    so the app can call it on every rerun. The retrained-weights case can only
    be judged once the model has actually been loaded, so it appears here after
    the first search or save rather than at launch.
    """
    with _connect() as conn:
        model = _meta_get(conn, "embed_model")
        dim = _meta_get(conn, "embed_dim")
        (entries,) = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
        actual = _stored_dim(conn)

    model = model.decode() if model else None
    dim = int(dim) if dim else None

    problem = None
    if model and model != EMBED_MODEL_NAME:
        problem = {
            "kind": "model",
            "message": (
                f"This library's search vectors were built by '{model}', but the "
                f"app is set to '{EMBED_MODEL_NAME}'. Entries saved from now on "
                "won't be comparable with the older ones. Either set "
                "EMBED_MODEL_NAME back, or re-embed every entry."
            ),
        }
    elif dim and actual and dim != actual:
        problem = {
            "kind": "dimension",
            "message": (
                f"This library's stamp says {dim}-number vectors but the stored "
                f"ones are {actual}. Search will fail until every entry is "
                "re-embedded."
            ),
        }
    elif _probe_verdict:
        problem = _probe_verdict

    return {
        "model": model,
        "dim": dim or actual,
        "entries": entries,
        "problem": problem,
    }


# ---------------------------------------------------------------------------
# 4. SQLite storage + search
# ---------------------------------------------------------------------------


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def save_image(data: bytes, original_name: str = "") -> str:
    """Save image bytes into ./images and return the stored FILENAME.

    The name is generated rather than taken from the upload: an uploaded name
    could collide with an existing file or contain path separators. Only the
    extension is borrowed from it. Returning a bare filename (not a full path)
    keeps the database portable if the project folder moves.
    """
    extension = os.path.splitext(original_name)[1].lower()
    if extension not in IMAGE_EXTENSIONS:
        extension = ".png"

    os.makedirs(IMAGE_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"img-{stamp}-{secrets.token_hex(3)}{extension}"
    with open(os.path.join(IMAGE_DIR, filename), "wb") as handle:
        handle.write(data)
    return filename


def image_path_for(filename: str | None) -> str | None:
    """Full path to a saved image, or None if it's missing/not set.

    Callers use the None to show a placeholder instead of crashing: an image
    file can go missing for reasons outside the app's control (the images folder
    wasn't copied along with the project, a manual delete, a cleanup run).
    """
    if not filename:
        return None
    full = os.path.join(IMAGE_DIR, filename)
    return full if os.path.exists(full) else None


def open_image_externally(filename: str | None) -> str | None:
    """Hand a saved image to the computer's own viewer (Preview on a Mac).

    Returns None once the viewer has been launched, or a short sentence saying
    why it couldn't be — nothing here raises, because failing to open a picture
    must not cost you the tab you were reading.

    This works because the app and the browser window showing it are the same
    computer, which is how Trailhead is meant to be run. If you ever serve it to
    another machine, the picture opens on the machine running the app, not on
    the one you're sitting at.
    """
    if not filename:
        return "There's no image on that entry."
    path = image_path_for(filename)
    if not path:
        return f"That image file is no longer in images/ ({filename})."

    # The path is about to be handed to the operating system, so confirm it
    # really is one of our own files first. save_image() only ever generates
    # names that sit directly in images/, but the name travels through the
    # database, and a row that arrived some other way (a hand-edited library, a
    # merge from elsewhere) could point outside the folder — in which case this
    # would obligingly open whatever it found there.
    resolved = os.path.realpath(path)
    if os.path.dirname(resolved) != os.path.realpath(IMAGE_DIR):
        return "That file isn't inside the images/ folder, so it wasn't opened."

    if sys.platform == "darwin":
        command = ["open", resolved]
    elif os.name == "nt":
        try:
            os.startfile(resolved)  # type: ignore[attr-defined]  # Windows only
        except OSError as exc:
            return f"The computer wouldn't open it ({exc})."
        return None
    else:
        command = ["xdg-open", resolved]

    # No shell is involved (the command is a list), so a filename can't turn
    # into anything executable. The timeout is a backstop: these launchers hand
    # off to the viewer and exit immediately, so one that hasn't returned in ten
    # seconds is stuck, and waiting on it would freeze the app for everyone.
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=10)
    except FileNotFoundError:
        return f"This computer has no '{command[0]}' command, so it wasn't opened."
    except subprocess.TimeoutExpired:
        return "The image viewer didn't respond, so it may not have opened."
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode(errors="replace").strip()
        return f"The computer wouldn't open it{f' ({detail})' if detail else ''}."
    return None


def _atomic_write(path: str, data: bytes) -> None:
    """Write bytes so a reader never sees a half-finished file.

    The data goes to a temporary neighbour and is then renamed into place;
    os.replace is atomic within a filesystem. Without this, a crash or a full
    disk partway through a backup copy would leave a truncated file that still
    *looks* like a good backup — worse than having none.
    """
    temp = f"{path}.tmp"
    with open(temp, "wb") as handle:
        handle.write(data)
    os.replace(temp, path)


def _sha256(path: str) -> str:
    """Hex SHA-256 of a file, read in chunks so a big image can't fill memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_names(folder: str) -> set[str]:
    """Image filenames in a folder, ignoring dotfiles, temps, and the manifest.

    A folder that doesn't exist gives an empty set rather than an error, which
    is what makes a missing ./images or a missing backup mirror a harmless
    no-op everywhere downstream instead of a special case in each caller.
    """
    try:
        return {
            name
            for name in os.listdir(folder)
            if not name.startswith(".")
            and not name.endswith(".tmp")
            and name != IMAGE_MANIFEST_NAME
        }
    except OSError:
        return set()


def _referenced_images() -> set[str]:
    """Every image filename some entry still points at."""
    with _connect() as conn:
        return {
            row["image_path"]
            for row in conn.execute(
                "SELECT image_path FROM entries WHERE image_path IS NOT NULL"
            )
            if row["image_path"]
        }


def unused_images() -> list[str]:
    """Image files in ./images that no entry refers to.

    Deleting an entry deliberately leaves its image file behind (see
    delete_entry), so orphans build up over time. This finds them; removing
    them is a separate, explicit step.
    """
    return sorted(_image_names(IMAGE_DIR) - _referenced_images())


def unused_backup_images() -> list[str]:
    """Mirrored copies in ./backups/images that no entry refers to.

    Listed separately from unused_images() because the two are cleaned on
    different terms: clearing ./images is recoverable while the mirror still
    holds the picture, but clearing the mirror is permanent.
    """
    return sorted(_image_names(IMAGE_BACKUP_DIR) - _referenced_images())


def backup_only_images() -> list[str]:
    """Mirrored copies whose original is gone from ./images AND that no entry
    refers to.

    "In the mirror but not in ./images" on its own is NOT a safe thing to
    delete — that set also contains any picture an entry still needs whose
    original went missing, which is the exact case the mirror exists to survive.
    Requiring the file to be unreferenced as well removes that risk: nothing
    points at these, and no original is left for them to protect. See
    stranded_backup_images() for the ones deliberately excluded.
    """
    return sorted(
        _image_names(IMAGE_BACKUP_DIR) - _image_names(IMAGE_DIR) - _referenced_images()
    )


def stranded_backup_images() -> list[str]:
    """Mirrored copies of pictures that entries still need but ./images has lost.

    These are the mirror doing its job, and they must never be swept up by a
    cleanup. Seeing any is a symptom rather than a chore: verify_images() puts
    referenced files back on every launch, so a file staying stranded means that
    restore couldn't happen — a damaged mirror copy, a full disk, or a folder
    that can't be written to.
    """
    return sorted(
        (_image_names(IMAGE_BACKUP_DIR) - _image_names(IMAGE_DIR))
        & _referenced_images()
    )


def _remove_image(folder: str, name: str) -> int | None:
    """Delete one image file. Returns the bytes freed, or None if it couldn't be.

    Returns None rather than 0 for failure so that a legitimately empty file
    still counts as removed.
    """
    full = os.path.join(folder, name)
    try:
        size = os.path.getsize(full)
        os.remove(full)
    except OSError:
        return None  # already gone or not removable; skip it
    return size


def delete_backup_only_images() -> tuple[int, int]:
    """Delete the mirrored copies that no original and no entry needs.

    Returns (files removed, bytes freed). Permanent — these are last copies, so
    only ever call it on an explicit user request. The manifest entry goes with
    each file, so the next launch doesn't look for something deliberately gone.
    """
    manifest = _load_manifest()
    removed = freed = 0
    names = backup_only_images()
    for name in names:
        size = _remove_image(IMAGE_BACKUP_DIR, name)
        if size is not None:
            removed += 1
            freed += size
            manifest.pop(name, None)
    if removed:
        _save_manifest(manifest)
    return removed, freed


def delete_unused_images(include_backups: bool = False) -> tuple[int, int]:
    """Delete every orphaned image file. Returns (files removed, bytes freed).

    By default only ./images is cleared, so the pictures are still recoverable
    from the backup mirror. Pass include_backups=True to remove the mirrored
    copies as well — that one cannot be undone.

    Only ever call this on an explicit user request: an older database snapshot
    may still reference these files, so removing them can break a restore.
    """
    removed = freed = 0

    def _drop(folder: str, name: str) -> None:
        nonlocal removed, freed
        size = _remove_image(folder, name)
        if size is not None:
            removed += 1
            freed += size

    for name in unused_images():
        _drop(IMAGE_DIR, name)

    if include_backups:
        manifest = _load_manifest()
        stale = unused_backup_images()
        for name in stale:
            _drop(IMAGE_BACKUP_DIR, name)
            manifest.pop(name, None)
        if stale:
            _save_manifest(manifest)

    return removed, freed


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
                image_path TEXT,
                embedding  BLOB,
                created_at TEXT
            )
            """
        )
        # CREATE TABLE IF NOT EXISTS won't touch a table that already exists, so
        # libraries created before images were supported need the new column
        # added explicitly. Checking first keeps this safe to run every launch.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(entries)")}
        if "image_path" not in columns:
            conn.execute("ALTER TABLE entries ADD COLUMN image_path TEXT")

        # Facts about the library itself rather than any one entry — currently
        # which model built its search vectors. See the embedding-model stamp
        # section for why that's worth recording.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value BLOB)"
        )
        # A library written before stamping has vectors with no record of what
        # made them. The model configured right now is the only defensible
        # guess — nothing else is knowable after the fact — so write that, and
        # let the fingerprint fill itself in the first time the model loads.
        if _meta_get(conn, "embed_model") is None:
            _meta_set(conn, "embed_model", EMBED_MODEL_NAME.encode())
            existing = _stored_dim(conn)
            if existing:
                _meta_set(conn, "embed_dim", str(existing).encode())


BACKUP_DIR = os.path.join(os.path.dirname(DB_PATH), "backups")

# Saved pictures are mirrored here. They can't live inside the .db snapshots
# (that would make the every-launch backup copy the whole image library), so
# they get their own append-only copy alongside them. The manifest records each
# file's size and hash so damage — not just absence — can be detected.
IMAGE_BACKUP_DIR = os.path.join(BACKUP_DIR, "images")
IMAGE_MANIFEST_NAME = "manifest.json"
IMAGE_MANIFEST_PATH = os.path.join(IMAGE_BACKUP_DIR, IMAGE_MANIFEST_NAME)


def backup_database(keep: int = 5) -> str | None:
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


def list_backups() -> list[dict]:
    """Every database snapshot in ./backups, newest first.

    Uses the same glob pattern backup_database() writes and prunes with, so
    this listing can't drift from what the rotation actually keeps. The
    timestamped names sort chronologically, so reversing gives newest first.
    """
    snapshots = []
    for path in sorted(
        glob.glob(os.path.join(BACKUP_DIR, "library-*.db")), reverse=True
    ):
        try:
            info = os.stat(path)
        except OSError:
            continue  # vanished between the glob and the stat; just skip it
        snapshots.append(
            {
                "path": path,
                "name": os.path.basename(path),
                "size": info.st_size,
                "modified": datetime.fromtimestamp(info.st_mtime),
            }
        )
    return snapshots


def folder_size(path: str) -> int:
    """Total bytes of everything under a folder, or 0 if it isn't there.

    Recursive because ./backups now contains the image mirror as a subfolder.
    """
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _load_manifest() -> dict:
    """The image manifest: {filename: {"size": int, "sha256": str}}.

    Returns {} when it's absent or unreadable. A damaged manifest must degrade
    to "nothing can be verified", never to an error: it is only a helper for
    checking the real files, and losing it must not stop the app from starting.
    """
    try:
        with open(IMAGE_MANIFEST_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_manifest(manifest: dict) -> bool:
    """Write the manifest atomically. False if it couldn't be written."""
    try:
        _atomic_write(
            IMAGE_MANIFEST_PATH,
            json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"),
        )
        return True
    except OSError:
        return False


def backup_images() -> dict:
    """Mirror ./images into ./backups/images, copying only what's new.

    Image files are immutable — save_image() invents a unique name and never
    overwrites one — so "a file of that name is already mirrored" is enough to
    skip it. The usual launch therefore costs two directory listings and no
    file reads at all.

    This function ONLY copies; it never deletes from the mirror. That is the
    load-bearing rule: a tool that *synced* the two folders would delete the
    backup to match a lost or emptied ./images, destroying exactly what it
    exists to protect. An absent mirror is likewise not an error — it is simply
    rebuilt, since ./images is the source of truth and the mirror is derived.

    Returns {"copied", "total", "failed"}.
    """
    live = _image_names(IMAGE_DIR)
    mirrored = _image_names(IMAGE_BACKUP_DIR)
    manifest = _load_manifest()

    new = sorted(live - mirrored)
    # Mirrored already but absent from the manifest, i.e. the manifest was lost
    # or corrupted. Re-recording costs two hashes per file, so only redo the
    # entries actually missing rather than rebuilding the whole thing.
    unrecorded = sorted((live & mirrored) - set(manifest))

    if not new and not unrecorded:
        return {"copied": 0, "total": len(mirrored), "failed": []}

    try:
        os.makedirs(IMAGE_BACKUP_DIR, exist_ok=True)
    except OSError:
        return {"copied": 0, "total": len(mirrored), "failed": new + unrecorded}

    copied, failed = 0, []
    for name in new:
        try:
            with open(os.path.join(IMAGE_DIR, name), "rb") as handle:
                data = handle.read()
            _atomic_write(os.path.join(IMAGE_BACKUP_DIR, name), data)
        except OSError:
            failed.append(name)
            continue
        manifest[name] = {
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        copied += 1

    for name in unrecorded:
        # Only record a hash that can be justified. With no manifest to
        # arbitrate, two copies that disagree mean one of them is damaged and
        # there is no way to tell which — recording either would certify a
        # corrupt file as good, which is worse than admitting we can't check it.
        try:
            live_file = os.path.join(IMAGE_DIR, name)
            live_hash = _sha256(live_file)
            if live_hash == _sha256(os.path.join(IMAGE_BACKUP_DIR, name)):
                manifest[name] = {
                    "size": os.path.getsize(live_file),
                    "sha256": live_hash,
                }
        except OSError:
            failed.append(name)

    if not _save_manifest(manifest):
        failed.append(IMAGE_MANIFEST_NAME)

    return {"copied": copied, "total": len(mirrored) + copied, "failed": failed}


def _matches(path: str, record: dict, deep: bool) -> bool:
    """Does a file match its manifest record? Size always, contents when deep."""
    try:
        if os.path.getsize(path) != record.get("size"):
            return False
        return _sha256(path) == record.get("sha256") if deep else True
    except OSError:
        return False


def _copy_into_place(src: str, dest: str) -> bool:
    """Copy a mirrored image back into ./images. False if it can't be done."""
    try:
        with open(src, "rb") as handle:
            data = handle.read()
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        _atomic_write(dest, data)
        return True
    except OSError:
        return False


def verify_images(deep: bool = False) -> dict:
    """Check saved images against the backup mirror, repairing what it safely can.

    deep=False (run at every launch) compares sizes only — stat calls, no
    reading — which catches a truncated or zeroed file essentially for free.
    deep=True (the Verify button) hashes every file, so it also catches damage
    that happens to preserve the length.

    Repairs happen only where the right answer is unambiguous: a file that is
    missing from ./images but present in the mirror gets restored, and a file
    whose contents disagree with the manifest is replaced when the mirrored
    copy is the one the manifest describes. If both copies disagree with the
    manifest, nothing is touched and the file is reported as damaged — silently
    overwriting one unverified copy with another could destroy the good one.

    Returns {"checked", "restored", "repaired", "damaged", "unverifiable"}.
    """
    manifest = _load_manifest()
    referenced = _referenced_images()
    result = {
        "checked": 0,
        "restored": [],
        "repaired": [],
        "damaged": [],
        "unverifiable": [],
    }

    for name in sorted(referenced | set(manifest)):
        result["checked"] += 1
        live = os.path.join(IMAGE_DIR, name)
        mirror = os.path.join(IMAGE_BACKUP_DIR, name)
        record = manifest.get(name)

        if not os.path.exists(live):
            if name not in referenced:
                # An orphan that a cleanup removed on purpose. Restoring it
                # would undo the user's cleanup on the very next launch.
                continue
            if os.path.exists(mirror) and _copy_into_place(mirror, live):
                result["restored"].append(name)
            else:
                result["damaged"].append(name)  # gone from both copies
            continue

        if not record:
            result["unverifiable"].append(name)
        elif not _matches(live, record, deep):
            # Always hash the mirror before trusting it here: this overwrites a
            # real file, so a size match alone isn't good enough.
            if os.path.exists(mirror) and _matches(mirror, record, True) \
                    and _copy_into_place(mirror, live):
                result["repaired"].append(name)
            else:
                result["damaged"].append(name)

    return result


def add_entry(
    url: str,
    title: str,
    summary: str,
    notes: str = "",
    keywords: str = "",
    image_path: str | None = None,
) -> int:
    """Save one entry. The embedding is computed from summary + keywords + notes
    so that your own tags and notes also influence search results.

    `image_path` is the filename returned by save_image() for a saved picture,
    or None for an ordinary link. Because the embedding comes from the summary,
    an image described by summarize_image() is searchable just like a page.

    Returns the new row's id.
    """
    text_to_embed = "\n".join(p for p in (summary, keywords, notes) if p)
    vector = embed(text_to_embed)

    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO entries
                (url, title, summary, notes, keywords, image_path, embedding, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                title,
                summary,
                notes,
                keywords,
                image_path,
                vector.tobytes(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return cursor.lastrowid


def all_entries() -> list[dict]:
    """Return every saved entry (without the raw embedding), newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, url, title, summary, notes, keywords, image_path, created_at "
            "FROM entries ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_entry(entry_id: int) -> dict | None:
    """Return one saved entry by id (without its raw embedding), if it exists."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, url, title, summary, notes, keywords, image_path, created_at "
            "FROM entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
    return dict(row) if row else None


def update_entry(
    entry_id: int,
    title: str,
    summary: str,
    notes: str = "",
    keywords: str = "",
    url: str | None = None,
) -> None:
    """Update an entry's editable fields and recompute its search embedding.

    The embedding is rebuilt from summary + keywords + notes (same recipe as
    add_entry) so edits to your tags/notes are reflected in future searches.
    Pass `url` to also correct the saved link; leave it None to keep the URL
    unchanged.
    """
    text_to_embed = "\n".join(p for p in (summary, keywords, notes) if p)
    vector = embed(text_to_embed)

    with _connect() as conn:
        if url is None:
            conn.execute(
                """
                UPDATE entries
                SET title = ?, summary = ?, notes = ?, keywords = ?, embedding = ?
                WHERE id = ?
                """,
                (title, summary, notes, keywords, vector.tobytes(), entry_id),
            )
        else:
            conn.execute(
                """
                UPDATE entries
                SET url = ?, title = ?, summary = ?, notes = ?, keywords = ?,
                    embedding = ?
                WHERE id = ?
                """,
                (url, title, summary, notes, keywords, vector.tobytes(), entry_id),
            )


def get_entry_by_url(url: str) -> dict | None:
    """Return the saved entry with this exact URL, or None if it isn't saved."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, url, title, summary, notes, keywords, image_path, created_at "
            "FROM entries WHERE url = ?",
            (url,),
        ).fetchone()
    return dict(row) if row else None


def delete_entry(entry_id: int) -> None:
    """Delete an entry's row — but NOT its image file, on purpose.

    Image files are append-only. The ./backups snapshots contain only the
    database, so if deleting an entry also deleted its picture, restoring an
    older snapshot would resurrect rows whose images no longer exist. Leaving
    the file means any restored snapshot always finds every image it refers to.
    The cost is orphaned files, which unused_images()/delete_unused_images()
    clean up on an explicit request.
    """
    with _connect() as conn:
        conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))


def related_entries(entry_id: int, top_k: int = 5) -> list[dict]:
    """Entries most semantically similar to the given one (excluding itself).

    Reuses the stored embeddings, so this is the same cosine-similarity math as
    `search` but with an existing entry's vector as the query. Returns up to
    `top_k` dicts with id, url, title and a 'score' (cosine similarity, 0-1).
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, url, title, embedding FROM entries"
        ).fetchall()

    target = next((r for r in rows if r["id"] == entry_id), None)
    if target is None or len(rows) < 2:
        return []

    target_vec = np.frombuffer(target["embedding"], dtype=np.float32)
    others = [r for r in rows if r["id"] != entry_id]
    matrix = np.vstack(
        [np.frombuffer(r["embedding"], dtype=np.float32) for r in others]
    )
    # Vectors are normalized, so the dot product IS the cosine similarity.
    scores = matrix @ target_vec

    ranked = sorted(zip(others, scores), key=lambda p: p[1], reverse=True)
    return [
        {"id": r["id"], "url": r["url"], "title": r["title"], "score": float(s)}
        for r, s in ranked[:top_k]
    ]


def map_graph(
    entry_id: int, top_k: int = 5, depth: int = 2
) -> tuple[list[dict], list[dict]]:
    """Build the node/edge lists for an entry's relatedness map.

    Breadth-first from `entry_id`: level 1 is its `top_k` most-related entries,
    level 2 is each of *their* `top_k` most-related, and so on out to `depth`.
    (Bump `depth` to 3 if you ever want one more ring.)

    Returns (nodes, edges):
      nodes — dicts of {id, url, title, level, center_score}, where level is
              the ring the entry first appeared in (0 = the center entry
              itself) and center_score is its cosine similarity to the center
              entry (1.0 for the center) — used to size the map's dots;
      edges — dicts of {a, b, score}, deduplicated as undirected pairs, since
              outer rings often link back to entries already on the map.
    """
    with _connect() as conn:
        center = conn.execute(
            "SELECT id, url, title FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
    if center is None:
        return [], []

    nodes = {entry_id: {"id": entry_id, "url": center["url"],
                        "title": center["title"], "level": 0}}
    edges: list[dict] = []
    seen_pairs: set[tuple[int, int]] = set()

    frontier = [entry_id]
    for level in range(1, depth + 1):
        next_frontier = []
        for node_id in frontier:
            for rel in related_entries(node_id, top_k=top_k):
                if rel["id"] not in nodes:
                    nodes[rel["id"]] = {"id": rel["id"], "url": rel["url"],
                                        "title": rel["title"], "level": level}
                    next_frontier.append(rel["id"])
                pair = tuple(sorted((node_id, rel["id"])))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    edges.append({"a": pair[0], "b": pair[1],
                                  "score": rel["score"]})
        frontier = next_frontier

    # Score every node against the CENTER entry (outer-ring nodes were found
    # via their ring-1 parent, so their edge score isn't similarity to the
    # center). The map uses this to size each dot.
    ids = list(nodes)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT id, embedding FROM entries "
            f"WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        ).fetchall()
    vecs = {r["id"]: np.frombuffer(r["embedding"], dtype=np.float32)
            for r in rows}
    center_vec = vecs[entry_id]
    for nid, node in nodes.items():
        node["center_score"] = (
            1.0 if nid == entry_id else float(vecs[nid] @ center_vec)
        )

    return list(nodes.values()), edges


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
        # With an LLM, search on the page's summary; with no LLM, fall back to the
        # raw page text (truncated) so URL-as-query search still works. This query
        # text is transient — nothing raw is stored.
        if LLM_PROVIDER == "none":
            query_text = page_text[:MAX_CHARS_FOR_SUMMARY]
        else:
            query_text = summarize(page_text)
        # A URL query has no meaningful keyword term to match against.
        keyword_query = ""
    else:
        keyword_query = query.strip().lower()

    query_vec = embed(query_text)

    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, url, title, summary, notes, keywords, image_path, "
            "embedding, created_at FROM entries"
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


def _term_regex(term: str) -> re.Pattern:
    """Compile one search word into a case-insensitive substring regex.

    Glob wildcards: * matches any run of characters, ? matches exactly one.
    Every other character (including a literal % or _) is matched as plain text.
    """
    escaped = re.escape(term.lower())
    pattern = escaped.replace(r"\*", ".*").replace(r"\?", ".")
    return re.compile(pattern)


def text_search(query: str) -> list[dict]:
    """Find entries whose text matches every word in `query` (case-insensitive).

    Unlike `search`, this does no embedding or semantic ranking — it's a plain
    "find these words" lookup across every text field (url, title, summary,
    notes, keywords). It returns *all* matches, newest first, so a name like
    "Moore" surfaces wherever it appears, even if it isn't one of the keywords.

    Multiple words are combined with an implicit AND: each word must appear
    somewhere in the entry, but not next to each other or in any set order. So
    "moore climate" finds entries that contain both "moore" and "climate"
    anywhere in their text.

    Each word may use glob wildcards:
      *  matches any run of characters (including none) — e.g. "clim*"
      ?  matches exactly one character                  — e.g. "wom?n"
    """
    terms = [_term_regex(word) for word in query.split()]
    if not terms:
        return []

    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, url, title, summary, notes, keywords, image_path, created_at "
            "FROM entries ORDER BY id DESC"
        ).fetchall()

    results = []
    for row in rows:
        # One searchable blob per entry so a word can match in any field.
        blob = " ".join(
            (row[field] or "")
            for field in ("url", "title", "summary", "notes", "keywords")
        ).lower()
        if all(rx.search(blob) for rx in terms):
            results.append(dict(row))
    return results


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
