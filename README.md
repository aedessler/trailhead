# 🧭 Trailhead

Trailhead is a small personal Mac app for building a searchable library of web
links. You **add a link**, the app fetches the page and has an LLM summarize it,
and you **search** your library later by meaning (not just exact words) to
rediscover what you saved — each summary a trailhead back into a source you
explored.

No Xcode, no Swift — it's Python with a browser-based UI (Streamlit) that you
launch from a double-click icon.

---

## What it does

The app has three tabs:

### ➕ Add a link
1. Paste a URL and click **Fetch & Summarize** (or just press **Enter**).
2. The app downloads the page, extracts the readable article text, and asks the
   LLM for a short summary.
3. It also suggests a handful of **keywords** for the page (shown as clickable
   chips — click any to add it to the Keywords box).
4. Review/edit the **Title**, **Summary**, **Keywords**, and optional **Notes**,
   then click **💾 Save to library**. The form clears automatically so you can
   add the next link without reloading.

If a page can't be read automatically (some sites render entirely with
JavaScript), the app doesn't dead-end: it lets you **type your own summary**, or
**paste the page's text** and have the LLM summarize that instead.

### 🔎 Search
- Type a topic (or paste a URL) and press **Enter** or click **Search**.
- Results are ranked by **meaning** using a local embedding model, so related
  pages show up even if they don't share the exact words.
- Pages whose **keywords match your search term are pushed to the top** and
  labeled `🏷 keyword match`. Searching by URL uses pure meaning-similarity.
- Use the slider to choose how many results to show.

### 📚 Browse all
- Every saved link appears as a compact, collapsible row (click to expand).
- Each entry has **✏️ Edit** (change the title/summary/keywords/notes — the
  search index is rebuilt automatically) and **🗑 Delete**.

---

## Choosing your LLM provider

Summaries and keyword suggestions can come from **OpenAI** (default) or the
**TAMU AI** platform. Switch by editing one line near the top of `core.py`:

```python
LLM_PROVIDER = "openai"   # or "tamu"
```

Both providers' code stays in place — you only flip this switch and supply the
matching key (below). Search and embeddings always run **locally** on your Mac
and are free, offline, and unaffected by this switch.

---

## One-time setup

1. **Get an API key for your chosen provider:**
   - OpenAI (default): [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
   - TAMU: [chat.tamu.ai](https://chat.tamu.ai) → Settings → API Key
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

> If macOS blocks `run.command` ("unidentified developer"), right-click it →
> **Open** the first time, or run `chmod +x run.command` in Terminal.

### Optional: a Dock icon
Open **Automator** → new **Application** → add a **Run Shell Script** action with:
`open "/Users/adessler/Desktop/data app/run.command"` — then save it as an app
and drag it to your Dock.

---

## Costs & performance

- Each **summary** and the **keyword suggestions** are LLM calls (a fraction of a
  cent each with OpenAI's `gpt-4o`). A funded API account is required.
- **Search is free** — it runs the local embedding model, no API calls.
- The **first** summary/search of a session takes a few extra seconds while the
  embedding model loads into memory; everything after that is fast.

---

## Your data & backups

- All your links live in a single SQLite file, `library.db`, in this folder.
- **Every time the app launches**, it makes a timestamped, consistent copy into a
  `backups/` folder and keeps the 10 most recent. The Browse tab shows which
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
| `core.py` | The engine: fetch page, summarize, suggest keywords, embed, store/search/edit, back up. |
| `library.db` | Your saved links (SQLite, created automatically). |
| `backups/` | Timestamped database snapshots (created automatically). |
| `requirements.txt` | The Python packages. |
| `.env` | Your API key (never shared/committed). |
| `.streamlit/config.toml` | Streamlit settings (quiets startup logs). |
| `run.command` | The double-click launcher. |

Under the hood: pages are fetched with `requests` and cleaned with
`trafilatura`; summaries/keywords use the OpenAI-compatible chat API; semantic
search uses `sentence-transformers` (`all-MiniLM-L6-v2`) with cosine similarity
computed in `numpy`.

---

## Testing the engine without the UI
```
source .venv/bin/activate
python core.py
```
This fetches a test page and prints an LLM summary — a quick way to confirm your
API key and internet access work.
