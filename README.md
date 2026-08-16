# 🧭 Trailhead

**Version 2.1.2**

Trailhead is a personal Mac app for building a searchable library of web
links. You **add a link**, the app fetches the page and has an LLM summarize it,
and you **search** your library later by meaning (not just exact words) to
rediscover what you saved — each summary a trailhead back into a source you
explored. You can save **images** the same way — upload a figure or screenshot,
or paste the address of one on the web, and the LLM describes what it shows so
it's findable by meaning too. An
interactive **🗺 map** shows how any entry connects to its nearest neighbors,
so you can also wander your library visually.

It's written in Python with a browser-based UI (Streamlit) that you launch from 
a double-click icon.

[Watch a video](https://youtu.be/DJs1ohaFMf4?si=fbTl67AvTPnoB19d) that shows how to set up and use the app

---

## What it does

The app has four tabs:

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

#### 🖼 Adding an image

Open **"Or add an image"** on the same tab to save a figure, chart, or
screenshot instead of a page. The **Image from** toggle picks where it comes
from:

- **A file on this Mac** — choose a `.png`, `.jpg`, `.gif`, or `.webp` file.
- **A web address** — paste the address of the picture itself (right-click an
  image in your browser ▸ *Copy Image Address*). It previews as you paste, and
  the file is downloaded and saved locally like any other, so it stays yours
  even if the original page changes or disappears. If you leave **Source link**
  blank, that address becomes the entry's link.

Either way, optionally paste the **source link** it came from, then click
**Describe & add image**: the LLM looks at the picture and writes a description
of what it shows, then suggests a title and keywords. You review and edit all of
it before saving, exactly as with a link.

That description is what makes the image searchable — the search index is built
from it, so later you can find a figure by describing its content rather than
remembering its filename. The original file is copied into an `images/` folder
next to the app; the database stores only its name.

Pasting the address of a *page* rather than an image gets a message saying so.
Formats Trailhead doesn't store (SVG, TIFF, BMP) are refused rather than saved
under a misleading name, and a download is abandoned past 25 MB.

Saved images appear as thumbnails wherever the entry does, in both Search and
Browse, with a **🖥 Open on this Mac** button underneath. That hands the real
file to Preview, so you can see it full size, zoom into a figure's axis labels,
or copy it into something else — the things a thumbnail scaled to fit a card
can't do. It works because the app and the browser window showing it are the
same computer; if you ever served Trailhead to another machine, the picture
would open on the machine running the app rather than on yours.

### 🔎 Search

Type a topic and press **Enter** or click **Search**. The **Search by** toggle
picks how matching works:

**Meaning** (default)
- Results are ranked by **meaning** using a local embedding model, so related
  pages show up even if they don't share the exact words.
- Pages whose **keywords match your search term are pushed to the top** and
  labeled `🏷 keyword match`. You can also paste a **URL** to find saved links
  most like that page (this uses pure meaning-similarity).
- The five best matches show first. **Show More Results** at the bottom of the
  list reveals five more each time you click it, up to 25.

**Exact text**
- Finds **every** entry that contains your words (case-insensitive) anywhere in
  the title, summary, notes, keywords, or URL — handy for names or specific
  terms, e.g. *Jones*, even when buried in a summary. The count above the list is
  the full total; **Show More Results** walks through them five at a time, with
  no 25-result ceiling.
- **Multiple words are AND-ed:** each word must appear somewhere in the entry,
  but in any order and not necessarily next to each other — so `weather climate`
  finds entries that mention both *weather* and *climate*.
- **Wildcards:** `*` matches any run of characters and `?` matches exactly one,
  so `clim*` finds *climate* and *climatology* and `wom?n` finds *woman* and
  *women*. Wildcards apply per word, so `clim* polic*` requires both a *clim…*
  and a *polic…* word. A literal `%` or `_` is treated as plain text.

Each result lists up to **5 🔗 Related links** — the entries most similar in
meaning to that result, with a similarity score. Click one to open that saved
entry **inside Trailhead**, where you can follow its related links in turn; a
Back control returns to the previous entry or search results. The main result
title still opens the original source page. A **🗺 Map** button draws an
interactive graph of the result's neighborhood (see below).

### 📚 Browse all
- Every saved link appears as a compact, collapsible row (click to expand).
- Each expanded entry also lists up to **5 🔗 Related links** — the most
  semantically similar entries in your library, each with a similarity score.
  Clicking one opens that saved entry inside Trailhead instead of opening its
  source page; use Back to retrace your path or return to the full library.
- Each entry has **✏️ Edit** (change the URL/title/summary/keywords/notes — the
  search index is rebuilt automatically), **🗺 Map**, and **🗑 Delete**.

### 🗺 Map

Both Search results and Browse entries have a **🗺 Map** button that draws an
interactive graph of the entry's neighborhood: the entry itself (purple),
its 5 most-related entries (teal), and each of *their* 5 most-related (pale
outer ring). **Dot size shows how similar each entry is to the one at the
center.** Drag nodes around, scroll to zoom, hover a node for its full title
or an edge for the similarity score.

**Click any node** to show that entry in a **details panel beside the map** —
its summary, keywords, and notes (the map itself doesn't change). **Click the
panel's title to open the saved link** in a new tab, or press the panel's
**🗺 Map button to recenter the map on that entry** and wander through your
library's neighborhoods (recentering is instant — every neighborhood is
precomputed). The ✕ dismisses the panel and the map widens to use the freed
space. Click the map button on the entry again to hide the whole map.

### 🛟 Backup
- Lists every database snapshot you currently have — name, when it was made, and
  size — with the one from this session marked, plus how much space `images/`
  and `backups/` are using.
- Shows whether your saved images are mirrored and healthy, and reports anything
  the app restored or repaired at launch. **🔍 Verify all images** runs a full
  checksum pass on demand.
- Beside it, **🗑 Clear N stale backup copy(s)** removes mirrored files whose
  original is gone from `images/` *and* that no entry refers to — the residue of
  earlier cleanups that kept the backup copy. A file an entry still needs is
  never swept up, even with its original missing; that case is reported as a
  warning instead, since the mirror is the only thing holding it.
- Names the model that built your search vectors, and warns if it stops matching
  the one in use (see **Versions** below for why that matters).
- Holds the **🧹 unused image file(s)** cleanup panel, and the instructions for
  restoring a snapshot.
- The explanatory text comes from **`BACKUP.md`** next to the app, the same way
  the Help tab uses `HELP.md`.

### ❓ Help
- Shows the built-in instructions for using the app, rendered right in the
  browser so you never have to leave it.
- The text comes from **`HELP.md`** next to the app — edit that file to change
  what's shown, and the update appears on the next launch.
- If `HELP.md` is missing, the tab explains how to restore it instead of
  failing.

---

## LLMs

Summaries, titles, and keyword suggestions come from the **TAMU AI** platform
or **OpenAI** — or you can turn the LLM off entirely with
**`none`**. 

### Running without an LLM (`none`)

If you choose not to use an LLM, then **no API key is needed**.  In this mode the app still fetches pages, computes embeddings, and searches your library exactly as usual; it just leaves the **summary, title, and keyword suggestions blank** for you to fill in by hand in the editable form before
saving. (Searching by a **URL** still works too — it matches on the page's raw
text instead of a generated summary.) This is handy if you have no key, want to
stay fully offline, or simply prefer writing your own summaries.

---

# Getting it running

Before you start, you have to **get an API key for your chosen provider** (skip if using `none`):
   - TAMU (current default): [chat.tamu.ai](https://chat.tamu.ai) → Settings → API Key
   - OpenAI: [platform.openai.com/api-keys](https://platform.openai.com/api-keys)

The easiest way to do the rest of the install is the **`install.command`** script — double-click it in Finder (or run `./install.command` in Terminal). It walks you through everything:

1. **Choose your LLM provider**
2. **Paste your API key** when asked (or this is skipped if you choose `none`)
3. **Build the Python environment** — creates `~/.venvs/trailhead` and installs
   the packages, or offers to reinstall it if one already exists.

> If macOS blocks `install.command` ("unidentified developer"), right-click it →
> **Open** the first time, or run `chmod +x install.command` in Terminal.

---

## Running it

Double-click **`run.command`** in Finder.

- Before launching, the script verifies the Python virtual
  environment is intact and **reinstalls** it if anything is
  missing, so a missing, half-finished, or damaged install is repaired instead of
  crashing.
- The app opens in your default web browser. Closing the Terminal window quits it.
- It runs on a fixed port (8501) and **won't start a second copy** — if Trailhead
  is already running, launching again just reopens it in your browser instead of
  spawning another window/process.

> If macOS blocks `run.command` ("unidentified developer"), right-click it →
> **Open** the first time, or run `chmod +x run.command` in Terminal.

### Why the Python environment lives outside this folder

The environment is **not** kept inside the project. It lives at
`~/.venvs/trailhead` on your Mac. This is deliberate.

This project folder sits in `~/Documents`, which **iCloud Drive syncs**. A Python
environment is over a gigabyte spread across many thousands of tiny files, and
iCloud cannot keep up with that. Keeping the environment in `~/.venvs` (which 
iCloud does not touch) avoids this entirely. You don't need to do anything — 
`run.command` creates and uses it there automatically. If you ever want a clean 
rebuild, just delete that folder and relaunch; it will be recreated on the next 
launch.

### Optional: a Dock icon
Open **Automator** → new **Application** → add a **Run Shell Script** action
with the path to wherever this folder lives, e.g.:
`open "$HOME/Documents/trailhead/run.command"` — then save it as an app
and drag it to your Dock. (Use `$HOME` rather than `~` — a `~` inside quotes
doesn't expand, so the command would fail.)

---

## Costs & performance

- Each **summary**, generated **title** (for pasted text), and **keyword
  suggestion** is an LLM call. With OpenAI these cost a small amount per call (a
  funded account is required); TAMU AI is free for eligible university users.
  With `LLM_PROVIDER = "none"` there are **no LLM calls at all** (you write the
  summaries yourself).
- Adding an **image** costs one vision call to describe it (plus the usual
  cheap text calls for its title and keywords). A shrunken copy is sent for
  that call, so a huge screenshot doesn't cost extra — your saved file keeps
  its original resolution.
- **Search and the 🗺 map are free** — they run on the local embedding model
  and the similarity scores already stored in your library, no API calls.
- The **first** summary/search of a session takes a few extra seconds while the
  embedding model loads into memory; everything after that is fast.

---

## Your data & backups

- All your links live in a single SQLite file, `library.db`, in this folder.
- **Every time the app launches**, it makes a timestamped, consistent copy into a
  `backups/` folder and keeps the 5 most recent. The **Backup tab** lists them
  all and marks the one made this session. If the database gets corrupted,
  restore to the latest backup.
- **To restore:** quit the app, copy the snapshot you want from `backups/` back
  into this folder, and rename it to `library.db` (replacing the current one).
- **Saved images live in `images/`, not in the database** — that keeps
  `library.db` small, so the every-launch backup stays fast. It also means the
  `.db` snapshots do *not* contain your pictures, so keep the `images/` folder
  with the project when you move or copy it.
- **Images are mirrored into `backups/images/` on every launch.** Only files
  that aren't already there get copied, so the usual launch costs nothing. A
  `manifest.json` alongside them records each file's size and SHA-256.
- **Damaged or missing pictures are repaired automatically.** Each launch checks
  every image's size against that manifest; anything missing or the wrong size
  is restored from the mirror and reported in the Backup tab. The **🔍 Verify
  all images** button there does a full checksum pass on demand, which also
  catches damage that happens to preserve the file's length. If both copies
  disagree with the manifest, the app reports the file as damaged and changes
  nothing rather than guessing which one is good.
- The mirror is only ever added to, never trimmed to match `images/` — so an
  emptied or lost `images/` folder is recovered from it instead of erasing it.
  Deleting `backups/images/` is harmless; it rebuilds on the next launch.
- **Deleting an entry leaves its image file in place.** That's deliberate: if
  deleting also erased the picture, restoring an older snapshot would bring
  back entries whose images were gone. (If a file does go missing, the app shows
  a small "image file missing" note rather than breaking.)
- Those leftovers collect over time, so the Backup tab shows a **"unused image
  file(s)"** panel with a cleanup button when there are any. By default it
  clears `images/` but keeps the mirrored copies, so the pictures stay
  recoverable and older snapshots still restore correctly. A checkbox deletes
  the backup copies too — that one is permanent, so it always asks first.
- ⚠️ The mirror roughly **doubles the space images take** inside this folder,
  and it sits on the same disk as the originals. It protects against an
  accidental delete or a corrupted file, **not** against losing the drive or the
  folder — see the next bullet for that.
- Keeping this folder in iCloud, Dropbox, or Google Drive is a good way to get
  your library and its backups off the machine. (The Python environment is the
  one thing that must stay out of a synced folder — see
  [Why the Python environment lives outside this folder](#why-the-python-environment-lives-outside-this-folder).)

---

## How it works (files)

| File | Role |
|---|---|
| `app.py` | The UI: the Add / Search / Browse / Help tabs and the 🗺 map. Presentation only. |
| `core.py` | The engine: fetch page, summarize, suggest title & keywords, embed, store/search/edit, map, back up. |
| `library.db` | Your saved links (SQLite, created automatically). |
| `images/` | Saved image files (created automatically; the database stores only their names). |
| `backups/` | Timestamped database snapshots (created automatically; images are *not* inside them). |
| `backups/images/` | Mirrored copies of your image files, plus a `manifest.json` of sizes and checksums used to detect and repair damage. |
| `HELP.md` | The text shown on the Help tab — edit it to change what's shown. |
| `BACKUP.md` | The explanatory text shown at the bottom of the Backup tab. |
| `requirements.txt` | The Python packages. |
| `.env` | Your API key (keep confidential). |
| `.streamlit/config.toml` | Streamlit settings (quiets startup logs). |
| `install.command` | Guided setup: pick provider, save key, build the environment. |
| `run.command` | The double-click launcher. |

Under the hood: pages are fetched with `requests` (sending a full browser-like
header set to get past naive bot filters; Google Drive share links are rewritten
to their direct-download form first) and cleaned with `trafilatura` (PDFs are
detected — by content type, extension, or `%PDF` magic bytes — and their text
pulled with `pypdf`);
summaries/keywords use the OpenAI-compatible chat API (image descriptions go
through the same API, as a vision call); semantic search uses
`sentence-transformers` (`all-MiniLM-L6-v2`) with cosine similarity computed in
`numpy`; the relatedness map is drawn with `pyvis` (an interactive vis.js
network embedded in the page).

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

---

## Testing the engine without the UI
```
source ~/.venvs/trailhead/bin/activate
python core.py
```
This fetches a test page and prints an LLM summary — a quick way to confirm your
API key and internet access work. (With `LLM_PROVIDER = "none"` the summary line
is intentionally blank, since no LLM is called.)

---

## Running on Windows

The app itself is plain, cross-platform Python — `app.py` and `core.py` run on
Windows unchanged. The only Mac-specific piece is the `run.command` launcher.
To run Trailhead on Windows you need two things: **Python installed**, and a
**`run.bat`** launcher in place of `run.command`.

**1. Install Python.** Windows doesn't ship with Python. Install Python 3.x from
[python.org/downloads](https://www.python.org/downloads/) and — important — tick
**"Add python.exe to PATH"** on the first screen of the installer.

**2. Add the API key** to the `.env` file: copy
`.env.example` to `.env` and paste your real key in the right place. (`python-dotenv` reads `.env`
the same way on every OS.) 

**3. Create `run.bat`** in this folder (next to `app.py`) with the following
contents. It's the Windows twin of `run.command`: it builds a private Python
environment on first launch, self-repairs it if a package is missing, then
starts the app.

```bat
@echo off
REM Double-click this file to launch the Trailhead app on Windows.
REM On the FIRST run it creates a private Python environment and installs the
REM needed packages (a few minutes). After that, launches are fast.

REM Move into the folder this script lives in, regardless of where it's run from.
cd /d "%~dp0"

REM The virtual environment lives OUTSIDE this folder, in %USERPROFILE%\.venvs,
REM on purpose. If this project sits under a OneDrive-synced Documents folder,
REM OneDrive can't keep up with the thousands of tiny files in a Python
REM environment and will half-sync them, silently breaking it. Keeping the venv
REM in a non-synced location (which OneDrive doesn't touch) avoids that.
set "VENV_DIR=%USERPROFILE%\.venvs\trailhead"

REM Create the environment the first time only.
if not exist "%VENV_DIR%" (
    echo First-time setup: creating Python environment...
    python -m venv "%VENV_DIR%"
)
call "%VENV_DIR%\Scripts\activate.bat"

REM Verify the environment is intact before launching. If the key package can't
REM be imported, (re)install everything so a broken environment self-repairs.
python -c "import streamlit, pyvis" >nul 2>&1
if errorlevel 1 (
    echo Installing packages (this can take a few minutes)...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
)

REM Quiet down the embedding library's noisy (harmless) startup messages.
set TRANSFORMERS_VERBOSITY=error
set TRANSFORMERS_NO_ADVISORY_WARNINGS=1
set HF_HUB_DISABLE_PROGRESS_BARS=1
set TOKENIZERS_PARALLELISM=false

REM Launch the app. Streamlit opens it in your default web browser.
echo Starting the app... (close this window to quit)
streamlit run app.py --server.port 8501
```

**4. Launch** by double-clicking `run.bat` (or running it from a Command Prompt).
The first launch installs everything (a few minutes, including the one-time
~80 MB embedding model); later launches are fast. The app opens in your default
browser, and closing the Command Prompt window quits it.

> **Notes & differences from the Mac launcher:**
> - **`python` vs `python3`:** Windows uses `python`. If that's not found, use
>   the `py` launcher (`py -m venv ...`) or re-run the installer with "Add to
>   PATH" checked.
> - **The venv path is `%USERPROFILE%\.venvs\trailhead`** — the same
>   outside-the-synced-folder idea as on Mac (see above), just guarding against
>   **OneDrive** instead of iCloud. For a clean rebuild, delete that folder and
>   relaunch.
> - **No duplicate-launch guard.** The Mac script uses `lsof` to avoid starting a
>   second copy; the reliable Windows equivalent is fiddly, so it's omitted. Just
>   don't double-launch — if you do, close the extra window.
> - **`sentence-transformers`/`torch` install fine on Windows** (CPU wheels via
>   pip) — no extra steps, just a larger first-time download.

---

## Versions

The version shows under the title in the app, and lives in exactly one place in
the code: `__version__` at the top of `core.py`. Everything else reads it from
there — never write the number into a second file, or the two will drift.

To cut a release: bump `__version__`, update the number at the top of this file,
commit, then tag it so the old version stays downloadable.

```bash
git tag -a v2.2 -m "Trailhead 2.2" && git push origin v2.2
```

GitHub builds a downloadable zip for every tag, so "send me version 2" is a
link: `https://github.com/aedessler/trailhead/archive/refs/tags/v2.1.1.zip`.

Bump the **minor** part (2.0 → 2.1) for a new feature, the **major** part for a
release big enough that you'd tell someone about it, and add a **third** part
(2.1 → 2.1.1) for fixes and tightening that don't change what the app does.
Version 2 is the one that added saved images, the backup mirror, and the Backup
tab; 2.1 added saving an image straight from a web address; 2.1.1 pinned the
embedding model and made the library record which model built it; 2.1.2 added
opening a saved image in Preview and deleting an entry from a search result,
and stopped the Add tab's messages from shifting the page as they come and go.

> **Why the embedding model is pinned.** Semantic search only works because
> every entry was turned into numbers by the *same* model — two models place the
> same text in different spots, so a library holding both ranks badly with
> nothing to show for it. The app therefore loads the model from its local cache
> and never checks Hugging Face for a newer one, and the database records the
> model's name and a fingerprint of its output so a mismatch becomes a warning
> instead of a silent decline. If you ever do switch models deliberately, every
> entry has to be re-embedded — it's all or nothing.

> Your `library.db` doesn't need a version of its own — `init_db()` checks the
> table's columns on every launch and adds anything missing, so an older library
> upgrades itself.

---

## License

Licensed under the [MIT License](LICENSE).
