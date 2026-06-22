Trailhead is your personal, searchable library of web links. You **add a link**,
the app fetches the page and has an LLM summarize it, and later you **search**
your library — by meaning *or* by exact words — to rediscover what you saved.

---

#### ➕ Add a link
1. Paste a URL and click **Fetch & Summarize** (or press **Enter**). PDF links
   and **Google Drive** share links work too — the app pulls the text and
   summarizes it like any other page.
2. The summary ends with an **`Authors:`** line. The app also suggests
   **keywords** as clickable chips — click any to add it to the Keywords box.
3. Review/edit the **Title**, **Summary**, **Keywords**, and optional **Notes**,
   then click **💾 Save to library**. The form clears so you can add the next one.

*Already saved that URL?* The app skips fetching and opens an inline editor for
the existing entry, so you update it instead of creating a duplicate.

*Page can't be read automatically?* Some sites are JavaScript-only, some PDFs are
scanned images, and many academic publishers block automated access. When that
happens you can **type your own summary**, or **paste the page's text** and click
*Summarize pasted text* (or press **⌘+Enter**) to have the LLM fill things in.

---

#### 🔎 Search
Pick a mode with the **Search by** toggle:

- **Meaning** *(default)* — ranks links by how related their **topic** is, using a
  local embedding model, so related pages surface even when they don't share your
  exact words. Entries whose **keywords** match your term jump to the top
  (`🏷 keyword match`). You can also paste a **URL** to find saved links most like
  that page. The slider sets how many results to show.
- **Exact text** — finds **every** entry that contains your words
  (case-insensitive) anywhere in the title, summary, notes, keywords, or URL.
  Best for names or specific terms — e.g. searching *Jones* finds it even when
  it's buried in a summary and isn't one of the keywords.

  **Multiple words must all appear**, but they can be anywhere in the entry and
  in any order — so `weather climate` finds entries that mention both *weather* and
  *climate*, even if those words are far apart.

  **Wildcards** match partial words:

  | Type this | Meaning | Matches |
  |---|---|---|
  | `*` | any run of characters (including none) | `clim*` → *climate*, *climatology* |
  | `?` | exactly one character | `wom?n` → *woman*, *women* |

  Wildcards work per word, so `clim* polic*` finds entries containing both a
  *clim…* word and a *polic…* word. A literal `%` or `_` is treated as plain text.

Each result lists up to **5 🔗 Related links** so you can hop to neighbors in your
library.

---

#### 📚 Browse all
Every saved link appears as a collapsible row (click to expand). Each entry has
**✏️ Edit** (change title/summary/keywords/notes — the search index rebuilds
automatically) and **🗑 Delete**, plus its own **🔗 Related links**.

---

#### 🛟 Your data & backups
All your links live in a single `library.db` file in the app folder. **Every
launch** the app saves a timestamped copy into `backups/` and keeps the 5 most
recent (the Browse tab shows this session's backup). To restore, quit the app,
copy a snapshot from `backups/` back into the folder, and rename it to
`library.db`.

> Searching and embeddings run **locally and free**. Only summaries, generated
> titles, and keyword suggestions make an LLM call. For setup, providers, and
> troubleshooting, see the **README**.
