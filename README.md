# 🧭 Trailhead

Trailhead is a small personal Mac app for building a searchable library of web
links. You **add a link**, the app fetches the page and has an LLM summarize it,
and you **search** your library later by meaning (not just exact words) to
rediscover what you saved — each summary a trailhead back into a source you
explored.

It's written in Python with a browser-based UI (Streamlit) that you launch from 
a double-click icon.

---

## What it does

The app has three tabs:

### ➕ Add a link
1. Paste a URL and click **Fetch & Summarize** (or just press **Enter**).
2. The app downloads the page, extracts the readable article text, and asks the
   LLM for a short summary. The summary ends with an **`Authors:`** line naming
   the content's author(s) (or `Authors: Unknown` when none can be determined).
   **PDF links work too** — the app pulls the text
   straight out of the PDF and summarizes it like any other page. **Google Drive
   share links** work as well: a `…/file/d/<ID>/view` link is automatically
   rewritten to fetch the underlying file (the file must be shared with "anyone
   with the link"; very large files that trigger Drive's virus-scan page can't be
   read automatically).
3. It also suggests a handful of **keywords** for the page (shown as clickable
   chips — click any to add it to the Keywords box).
4. Review/edit the **Title**, **Summary**, **Keywords**, and optional **Notes**,
   then click **💾 Save to library**. The form clears automatically so you can
   add the next link without reloading.

If you enter a URL that's **already in your library**, the app skips fetching and
opens an inline editor for the existing entry (pre-filled), so you update it
instead of creating a duplicate.

If a page can't be read automatically — some sites render entirely with
JavaScript, scanned/image-only PDFs have no text to pull, and many academic
publishers (e.g. World Scientific, ScienceDirect, Springer) **block automated
access** behind anti-bot protection — the app doesn't dead-end. The warning tells
you which case it is. You can **type your own summary**, or **paste the page's text** and
click *Summarize pasted text* (or press **⌘+Enter** in the box) — the LLM then
fills in the title, summary, and suggested keywords for you.

### 🔎 Search
- Type a topic (or paste a URL) and press **Enter** or click **Search**.
- Results are ranked by **meaning** using a local embedding model, so related
  pages show up even if they don't share the exact words.
- Pages whose **keywords match your search term are pushed to the top** and
  labeled `🏷 keyword match`. Searching by URL uses pure meaning-similarity.
- Use the slider to choose how many results to show (defaults to 5).
- Each result lists up to **5 🔗 Related links** — the entries most similar in
  meaning to that result, with a similarity score, so you can jump to neighbors
  in your library.

### 📚 Browse all
- Every saved link appears as a compact, collapsible row (click to expand).
- Each expanded entry also lists up to **5 🔗 Related links** — the most
  semantically similar entries in your library, each with a similarity score.
- Each entry has **✏️ Edit** (change the title/summary/keywords/notes — the
  search index is rebuilt automatically) and **🗑 Delete**.

---

## Choosing your LLM provider

Summaries, titles, and keyword suggestions can come from the **TAMU AI** platform
(current default) or **OpenAI**. Switch by editing one line near the top of
`core.py`:

```python
LLM_PROVIDER = "tamu"   # or "openai"
```

You can also change which model each provider uses, e.g.:

```python
TAMU_MODEL = "protected.Claude Sonnet 4.6"   # e.g. protected.gpt-4o, protected.Claude Opus 4.7
OPENAI_MODEL = "gpt-4o"
```

Both providers' code stays in place — you only flip the switch and supply the
matching key (below). Search and embeddings always run **locally** on your Mac
and are free, offline, and unaffected by this switch.

---

## One-time setup

1. **Get an API key for your chosen provider:**
   - TAMU (current default): [chat.tamu.ai](https://chat.tamu.ai) → Settings → API Key
   - OpenAI: [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. **Add the key:** copy `.env.example` to `.env`:
   ```
   cp ".env.example" ".env"
   ```
   then edit `.env` and paste your real key on the matching line
   (`OPENAI_API_KEY=...` or `TAMU_AI_API_KEY=...`).
3. That's it — the first launch installs everything else automatically.

> **Note on shell environment variables:** the `.env` file always wins, even if
> you have an old `OPENAI_API_KEY`/`TAMU_AI_API_KEY` exported in your shell
> (e.g. in `~/.zshrc`). So the key shown in `.env` is the one that's used.

---

## Running it

Double-click **`run.command`** in Finder.

- The **first** launch builds a private Python environment and downloads the
  packages (a few minutes — including a one-time ~80 MB embedding model). This
  environment lives in a `.venv` folder and does not affect your system Python.
- Every launch after that is fast.
- The app opens in your default web browser. Closing the Terminal window quits it.
- It runs on a fixed port (8501) and **won't start a second copy** — if Trailhead
  is already running, launching again just reopens it in your browser instead of
  spawning another window/process.

> If macOS blocks `run.command` ("unidentified developer"), right-click it →
> **Open** the first time, or run `chmod +x run.command` in Terminal.

### Optional: a Dock icon
Open **Automator** → new **Application** → add a **Run Shell Script** action with:
`open "/Users/adessler/Desktop/data app/run.command"` — then save it as an app
and drag it to your Dock.

---

## Costs & performance

- Each **summary**, generated **title** (for pasted text), and **keyword
  suggestion** is an LLM call. With OpenAI these cost a small amount per call (a
  funded account is required); TAMU AI is free for eligible university users.
- **Search is free** — it runs the local embedding model, no API calls.
- The **first** summary/search of a session takes a few extra seconds while the
  embedding model loads into memory; everything after that is fast.

---

## Your data & backups

- All your links live in a single SQLite file, `library.db`, in this folder.
- **Every time the app launches**, it makes a timestamped, consistent copy into a
  `backups/` folder and keeps the 5 most recent. The Browse tab shows which
  backup was made this session.
- **To restore:** quit the app, copy the snapshot you want from `backups/` back
  into this folder, and rename it to `library.db` (replacing the current one).
- ⚠️ Don't put the live `library.db` inside iCloud/Dropbox/Google Drive — cloud
  sync can corrupt a database that's being written to. It's fine to keep *copies*
  of backups in the cloud or on an external drive for off-machine safety.

---

## How it works (files)

| File | Role |
|---|---|
| `app.py` | The UI: the Add / Search / Browse tabs. Presentation only. |
| `core.py` | The engine: fetch page, summarize, suggest title & keywords, embed, store/search/edit, back up. |
| `library.db` | Your saved links (SQLite, created automatically). |
| `backups/` | Timestamped database snapshots (created automatically). |
| `requirements.txt` | The Python packages. |
| `.env` | Your API key (never shared/committed). |
| `.streamlit/config.toml` | Streamlit settings (quiets startup logs). |
| `run.command` | The double-click launcher. |

Under the hood: pages are fetched with `requests` (sending a full browser-like
header set to get past naive bot filters; Google Drive share links are rewritten
to their direct-download form first) and cleaned with `trafilatura` (PDFs are
detected — by content type, extension, or `%PDF` magic bytes — and their text
pulled with `pypdf`);
summaries/keywords use the OpenAI-compatible chat API; semantic search uses
`sentence-transformers` (`all-MiniLM-L6-v2`) with cosine similarity computed in
`numpy`.

---

## Troubleshooting

- **"Incorrect API key" / 401 error when summarizing.** The key is invalid or
  expired. Regenerate it at your provider, paste the new value into `.env`, and
  **restart the app**. Remember `.env` overrides any key exported in your shell.
- **"Couldn't automatically read this page."** Either the site **blocks
  automated access** (a 403/401/429 — common with academic publishers behind
  Cloudflare, like World Scientific or ScienceDirect), the page is JavaScript-only,
  or it's a scanned/image-only PDF with no text layer. The warning says which.
  Header-spoofing alone can't get past publisher bot protection, so use the manual
  fallback: paste the text and click *Summarize pasted text*, or write your own
  summary/notes.
- **A code change didn't show up.** The app doesn't auto-reload (the file watcher
  is off to keep the terminal quiet). Quit and relaunch `run.command`.
- **Edited the API key/model but nothing changed.** Those are read at startup —
  restart the app after editing `.env` or `core.py`.
- **TAMU + a Claude model returns odd/empty output.** Claude models on TAMU
  stream by default; the app already requests non-streaming, so make sure you're
  on the current `core.py`.

---

## Testing the engine without the UI
```
source .venv/bin/activate
python core.py
```
This fetches a test page and prints an LLM summary — a quick way to confirm your
API key and internet access work.
