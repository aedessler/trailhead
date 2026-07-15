"""
app.py — the Streamlit user interface.

Run it with:   streamlit run app.py
(or just double-click run.command)

All the real work lives in core.py; this file is only the screen layout.
"""

import json
import os

import streamlit as st

import core

# Quick-add keyword chips shown under the Keywords box. Edit this list to match
# the tags you use most — clicking a chip adds that word to the Keywords field.
SUGGESTED_KEYWORDS = ["climate", "satellites", "methods", "policy", "data", "modeling"]

# The Help tab renders this Markdown file. It lives next to app.py so you can edit
# the documentation without touching the code; changes show on the next rerun.
HELP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "HELP.md")

# Make sure the database table exists before anything else.
core.init_db()


# Back up the database once per app launch. @st.cache_resource caches the result
# for the life of the process, so this runs once at startup, not on every rerun.
@st.cache_resource
def _startup_backup():
    return core.backup_database()


_last_backup_path = _startup_backup()


def _vis_graph(entry_id: int) -> dict | None:
    """One entry's neighborhood as vis.js node/edge dicts, or None if empty.

    Color marks the ring (purple center, teal neighbors, pale outer ring);
    SIZE shows similarity to the center entry. The neighbors' similarity
    scores are rescaled to fill the size range so differences stay visible
    even when all the raw scores are close together.
    """
    nodes, edges = core.map_graph(entry_id)
    if not edges:
        return None

    colors = {0: "#7b2d8b", 1: "#2f6f6a", 2: "#9dc3c0"}
    others = [n["center_score"] for n in nodes if n["level"] > 0]
    lo, hi = (min(others), max(others)) if others else (0.0, 1.0)

    def _size(n: dict) -> float:
        if n["level"] == 0:
            return 34
        if hi == lo:
            return 20
        return 10 + 20 * (n["center_score"] - lo) / (hi - lo)

    vis_nodes = []
    for n in nodes:
        full = n["title"] or n["url"]
        label = full if len(full) <= 40 else full[:37] + "…"
        vis_nodes.append({
            "id": n["id"], "label": label,
            "title": f"{full} — {n['center_score']:.0%} similar to center",
            "size": _size(n),
            "color": colors.get(n["level"], "#9dc3c0"),
        })
    vis_edges = [
        {"from": e["a"], "to": e["b"], "width": 1 + 3 * e["score"],
         "color": "#cccccc", "title": f"similarity {e['score']:.0%}"}
        for e in edges
    ]
    return {"nodes": vis_nodes, "edges": vis_edges}


# Precompute the neighborhood of EVERY entry (for instant recentering) plus
# each entry's details (for the map's side panel), so clicks on the map never
# need a server round-trip. Cached on the database file's modification time,
# so it rebuilds only after an add/edit/delete.
@st.cache_data
def _map_payload(db_mtime: float) -> dict:
    graphs, details = {}, {}
    for e in core.all_entries():
        g = _vis_graph(e["id"])
        if g:
            graphs[str(e["id"])] = g  # string keys to match JS object lookup
        details[str(e["id"])] = {
            "title": e["title"], "url": e["url"],
            "summary": e["summary"], "keywords": e["keywords"],
            "notes": e["notes"],
        }
    return {"graphs": graphs, "details": details}


def _render_map(entry_id: int) -> None:
    """Draw an interactive map of an entry and its most-related neighbors.

    The center entry is highlighted, ringed by its 5 most-related entries, each
    of which is connected to *its* 5 most-related. Nodes can be dragged; hover
    a node for its full title, or an edge for the similarity score. Clicking a
    node redraws the map centered on that entry and shows its summary in a
    side panel (handled entirely in the browser — every neighborhood and
    entry's details are embedded in the map's HTML).
    """
    # Imported here (not at top) so the library only loads when a map is
    # actually drawn, matching core.py's lazy-import style.
    from pyvis.network import Network

    payload = _map_payload(os.path.getmtime(core.DB_PATH))
    graph = payload["graphs"].get(str(entry_id))
    if graph is None:
        st.info("Not enough entries in the library to draw a map yet.")
        return

    net = Network(
        height="600px", width="100%", bgcolor="#ffffff", font_color="#333333",
        cdn_resources="in_line", notebook=False,
    )
    # Straight edges: vis.js's default "smooth" curves can bow two edges apart
    # until one pair of nodes looks connected by multiple lines. (set_options
    # replaces pyvis's defaults wholesale, so the "dot" shape — normally
    # pyvis's default — must be restated here or nodes render as ellipses.)
    net.set_options("""
    const options = {
      "nodes": {"shape": "dot"},
      "edges": {"smooth": false},
      "physics": {"barnesHut": {"springLength": 150}}
    }
    """)
    for n in graph["nodes"]:
        net.add_node(n["id"], label=n["label"], title=n["title"],
                     size=n["size"], color=n["color"])
    for e in graph["edges"]:
        net.add_edge(e["from"], e["to"], width=e["width"],
                     color=e["color"], title=e["title"])

    # pyvis's HTML defines global `network`, `nodes`, and `edges` variables.
    # This appended script (a) swaps the datasets when a node is clicked, and
    # (b) shows the clicked entry's details in a panel overlaid on the map,
    # Connected-Papers style. The panel is built with textContent (never
    # innerHTML), so titles/summaries can't inject markup. The "</" escape in
    # the JSON keeps a literal "</script>" inside a summary from ending the
    # script block early.
    map_js = """
<script type="text/javascript">
  const TRAILHEAD_MAPS = __GRAPHS__;
  const TRAILHEAD_DETAILS = __DETAILS__;

  // --- Details panel, in its own column to the RIGHT of the map (so it
  // never covers the graph). The map shrinks while the panel is open and
  // re-expands when it's closed. ---
  const _mapbox = document.getElementById("mynetwork");
  const _row = _mapbox.parentNode;
  _row.style.display = "flex";
  // pyvis's HTML uses Bootstrap, whose .card class sets flex-direction:
  // column — restate "row" or the panel stacks under the map instead.
  _row.style.flexDirection = "row";
  _row.style.alignItems = "stretch";
  _mapbox.style.flex = "1 1 auto";
  _mapbox.style.width = "auto";
  _mapbox.style.minWidth = "0";
  const panel = document.createElement("div");
  panel.style.cssText =
    "flex:0 0 250px; position:relative; height:600px; overflow-y:auto;" +
    "background:#ffffff; border:1px solid #dddddd; border-radius:8px;" +
    "padding:12px 14px; margin-left:8px; font-size:13px; line-height:1.45;" +
    "box-sizing:border-box;";
  // Tell vis.js the map container changed size, then refit the view.
  function resizeMap() {
    network.setSize("100%", "600px");
    network.redraw();
    network.fit();
  }
  const closeBtn = document.createElement("div");
  closeBtn.textContent = "\\u2715";
  closeBtn.style.cssText =
    "position:absolute; top:6px; right:10px; cursor:pointer; color:#999999;";
  closeBtn.onclick = function () { panel.style.display = "none"; resizeMap(); };
  const titleLink = document.createElement("a");
  titleLink.target = "_blank";
  titleLink.rel = "noopener";
  titleLink.style.cssText =
    "display:block; font-weight:bold; margin-right:14px;" +
    "margin-bottom:6px; color:#1a6b64; text-decoration:none;";
  const kwDiv = document.createElement("div");
  kwDiv.style.cssText = "color:#888888; font-size:12px; margin-bottom:6px;";
  const sumDiv = document.createElement("div");
  sumDiv.style.cssText = "color:#333333; white-space:pre-wrap;";
  const notesDiv = document.createElement("div");
  notesDiv.style.cssText =
    "color:#666666; font-size:12px; margin-top:6px; white-space:pre-wrap;";
  // "Map" button at the bottom of the panel: recenters the map on the entry
  // being shown. Hidden while the shown entry already IS the center.
  const mapBtn = document.createElement("div");
  mapBtn.textContent = "\\ud83d\\uddfa Map";
  mapBtn.style.cssText =
    "display:none; margin-top:10px; padding:6px 12px; background:#2f6f6a;" +
    "color:#ffffff; border-radius:6px; cursor:pointer; font-size:13px;" +
    "text-align:center; user-select:none;";
  panel.append(closeBtn, titleLink, kwDiv, sumDiv, notesDiv, mapBtn);
  _row.appendChild(panel);

  let currentCenter = __CENTER__;
  let selectedId = currentCenter;

  function showDetails(id) {
    const d = TRAILHEAD_DETAILS[String(id)];
    if (!d) return;
    selectedId = id;
    titleLink.textContent = (d.title || d.url) + " \\u2197";
    titleLink.href = d.url;
    kwDiv.textContent = d.keywords ? "Keywords: " + d.keywords : "";
    sumDiv.textContent = d.summary || "(no summary)";
    notesDiv.textContent = d.notes ? "Notes: " + d.notes : "";
    mapBtn.style.display =
      (id === currentCenter || !TRAILHEAD_MAPS[String(id)])
        ? "none" : "block";
    const wasHidden = panel.style.display === "none";
    panel.style.display = "block";
    if (wasHidden) resizeMap();
  }
  showDetails(currentCenter);
  resizeMap();

  // Clicking a node only shows its details; the map itself doesn't change
  // until the panel's Map button is pressed.
  network.on("click", function (params) {
    if (!params.nodes.length) return;
    showDetails(params.nodes[0]);
  });

  mapBtn.onclick = function () {
    const g = TRAILHEAD_MAPS[String(selectedId)];
    if (!g) return;
    currentCenter = selectedId;
    nodes.clear(); edges.clear();
    nodes.add(g.nodes); edges.add(g.edges);
    mapBtn.style.display = "none";
    network.once("stabilized", function () {
      network.fit({animation: true});
    });
  };
</script>
"""
    map_js = (
        map_js
        .replace("__GRAPHS__", json.dumps(payload["graphs"]).replace("</", "<\\/"))
        .replace("__DETAILS__", json.dumps(payload["details"]).replace("</", "<\\/"))
        .replace("__CENTER__", str(entry_id))
    )
    html = net.generate_html().replace("</body>", map_js + "</body>")
    st.iframe(html, height=620)
    st.caption(
        "Dot size = similarity to the center entry. Click any node to read "
        "its summary in the panel; the panel's title opens the saved link, "
        "and its Map button recenters the map on that entry."
    )


def _open_related_entry(entry_id: int, view: str, parent_id: int) -> bool:
    """Navigate to a related saved entry inside Search or Browse.

    Each view keeps its own history stack so following related entries can be
    undone with a Back button. False means the entry disappeared since the
    related list was drawn (for example, another session deleted it).
    """
    entry = core.get_entry(entry_id)
    if entry is None:
        return False

    if view == "search":
        current_results = st.session_state.get("search_results")
        if current_results is not None:
            history = list(st.session_state.get("search_nav_history", []))
            history.append({
                "results": [dict(result) for result in current_results],
                "was_exact": st.session_state.get("search_was_exact", False),
            })
            st.session_state["search_nav_history"] = history
        st.session_state["search_results"] = [entry]
        st.session_state["search_was_exact"] = False
        return True

    # In Browse, preserve the parent as an intermediate stop when the click came
    # from the full library. Back returns to that entry, then to the full list.
    history = list(st.session_state.get("browse_nav_history", []))
    current_focus = st.session_state.get("browse_focus_id")
    if current_focus is None:
        history.extend([None, parent_id])
    else:
        history.append(current_focus)
    st.session_state["browse_nav_history"] = history
    st.session_state["browse_focus_id"] = entry_id
    return True


def _render_related_links(entry_id: int, view: str) -> None:
    """Draw related entries as in-app navigation rather than external links."""
    related = core.related_entries(entry_id, top_k=5)
    if not related:
        return

    st.caption("🔗 Related links")
    for rel in related:
        title = rel["title"] or rel["url"]
        if st.button(
            f"→ {title} · {rel['score']:.0%}",
            key=f"{view}_related_{entry_id}_{rel['id']}",
            help="Open this saved entry inside Trailhead",
            type="tertiary",
        ):
            if _open_related_entry(rel["id"], view, entry_id):
                st.rerun()
            else:
                st.warning("That saved entry no longer exists.")


st.set_page_config(page_title="Trailhead", page_icon="🧭", layout="centered")
st.title("🧭 Trailhead")

entry_tab, search_tab, browse_tab, help_tab = st.tabs(
    ["➕ Add a link", "🔎 Search", "📚 Browse all", "❓ Help"]
)


# ---------------------------------------------------------------------------
# Entry mode
# ---------------------------------------------------------------------------

with entry_tab:
    st.subheader("Add a link")

    # Show a one-time confirmation after a save cleared the form.
    if st.session_state.pop("just_saved", False):
        st.success("Saved!")

    # The URL box lives in a form so pressing Enter triggers Fetch & Summarize.
    # Text inputs inside a form can't be reliably cleared by deleting their
    # session_state key, so we bump this counter after each save to give the form
    # a fresh key — which resets the box to empty.
    round_n = st.session_state.get("entry_round", 0)
    with st.form(f"fetch_form_{round_n}"):
        url = st.text_input(
            "Paste a URL", key=f"entry_url_{round_n}", placeholder="https://..."
        )
        fetch_clicked = st.form_submit_button("Fetch & Summarize", type="primary")

    if fetch_clicked:
        if not url.strip():
            st.warning("Please paste a URL first.")
        elif core.get_entry_by_url(url.strip()):
            # Already saved — open it for editing instead of fetching a duplicate.
            st.session_state["edit_existing"] = core.get_entry_by_url(url.strip())
            st.session_state.pop("pending", None)
            st.session_state["pending_round"] = (
                st.session_state.get("pending_round", 0) + 1
            )
            st.rerun()
        else:
            st.session_state.pop("edit_existing", None)
            try:
                with st.spinner("Fetching page..."):
                    title, text = core.fetch_page(url.strip())
                with st.spinner("Summarizing..."):
                    summary = core.summarize(text)
                with st.spinner("Suggesting keywords..."):
                    try:
                        suggested = core.suggest_keywords(summary)
                    except Exception:
                        suggested = []  # keywords are optional; don't fail the entry
                # Stash the results so they survive the rerun after the button.
                st.session_state["pending"] = {
                    "url": url.strip(),
                    "title": title,
                    "summary": summary,
                    "manual": False,
                    "suggested_keywords": suggested,
                }
                st.session_state["pending_round"] = (
                    st.session_state.get("pending_round", 0) + 1
                )
            except Exception as exc:
                # Don't dead-end: fall back to manual entry so the user can still
                # save the link with their own summary/notes (or paste page text).
                # A 403/401/429 means the site is actively blocking automated
                # access (common for academic publishers behind Cloudflare) — that
                # needs manual entry, not a JS-render retry, so say so plainly.
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in (401, 403, 429):
                    reason = (
                        "this site blocks automated access, so it can't be fetched "
                        "here"
                    )
                else:
                    reason = "it may need JavaScript to load"
                st.warning(
                    f"Couldn't automatically read this page ({exc}) — {reason}. "
                    "You can enter the details yourself below, or paste the page's "
                    "text and have it summarized."
                )
                st.session_state["pending"] = {
                    "url": url.strip(),
                    "title": "",
                    "summary": "",
                    "manual": True,
                }
                st.session_state["pending_round"] = (
                    st.session_state.get("pending_round", 0) + 1
                )

    # If the entered URL is already saved, show an inline editor for that entry
    # instead of creating a duplicate.
    edit_existing = st.session_state.get("edit_existing")
    if edit_existing:
        st.divider()
        st.info("This link is already in your library — editing the existing entry.")
        epr = st.session_state.get("pending_round", 0)
        e_title = st.text_input(
            "Title", value=edit_existing["title"], key=f"dup_title_{epr}"
        )
        e_url = st.text_input(
            "URL", value=edit_existing["url"], key=f"dup_url_{epr}"
        )
        e_summary = st.text_area(
            "Summary", value=edit_existing["summary"], key=f"dup_summary_{epr}", height=160
        )
        e_keywords = st.text_input(
            "Keywords (comma-separated)",
            value=edit_existing["keywords"],
            key=f"dup_kw_{epr}",
        )
        e_notes = st.text_area(
            "Notes", value=edit_existing["notes"], key=f"dup_notes_{epr}", height=80
        )
        save_col, cancel_col = st.columns(2)
        if save_col.button("💾 Save changes", type="primary", key="dup_save"):
            with st.spinner("Saving..."):
                core.update_entry(
                    edit_existing["id"], e_title, e_summary, e_notes, e_keywords,
                    url=e_url.strip(),
                )
            st.session_state.pop("edit_existing", None)
            st.session_state["entry_round"] = (
                st.session_state.get("entry_round", 0) + 1
            )
            st.session_state["just_saved"] = True
            st.rerun()
        if cancel_col.button("Cancel", key="dup_cancel"):
            st.session_state.pop("edit_existing", None)
            st.session_state["entry_round"] = (
                st.session_state.get("entry_round", 0) + 1
            )
            st.rerun()

    # If we have a fetched-and-summarized page waiting, show the editable form.
    pending = st.session_state.get("pending")
    if pending:
        st.divider()
        pr = st.session_state.get("pending_round", 0)

        # After any fetch attempt, offer to (re)summarize text the user pastes in.
        # The automatic fetch can fail outright (manual=True), or "succeed" on a
        # bot-verification page (HTTP 200 with junk) — in both cases pasting the real
        # page text and re-summarizing fixes it. The original URL stays attached via
        # `pending`. The box + button live in a form so Cmd+Enter also submits.
        with st.expander(
            "📝 Page blocked or summary looks wrong? Paste the page's text to summarize"
        ):
            with st.form(f"paste_form_{pr}"):
                pasted = st.text_area(
                    "Paste page text here", key=f"paste_text_{pr}", height=200
                )
                paste_submitted = st.form_submit_button("Summarize pasted text")
            if paste_submitted:
                if not pasted.strip():
                    st.warning("Paste some text first.")
                else:
                    ok = False
                    try:
                        with st.spinner("Summarizing..."):
                            pending["summary"] = core.summarize(pasted.strip())
                            pending["title"] = core.suggest_title(pasted.strip())
                        try:
                            with st.spinner("Suggesting keywords..."):
                                pending["suggested_keywords"] = core.suggest_keywords(
                                    pending["summary"]
                                )
                        except Exception:
                            pending["suggested_keywords"] = []
                        ok = True
                    except Exception as exc:
                        st.error(f"Couldn't summarize the pasted text: {exc}")
                    # Rerun OUTSIDE the try (st.rerun raises internally, which a broad
                    # except would otherwise swallow). New round → Title/Summary boxes
                    # re-init from the updated pending content.
                    if ok:
                        st.session_state["pending"] = pending
                        st.session_state["pending_round"] = (
                            st.session_state.get("pending_round", 0) + 1
                        )
                        st.rerun()

        if pending.get("manual"):
            st.caption("Or just write your own summary/notes below.")
        else:
            st.caption("Review and edit before saving:")

        # Editable fields use a changing key (pending_round) so they reliably
        # re-initialize from the latest pending content — the same trick used for
        # the URL box. (Popping a static key + value= is unreliable in Streamlit.)
        st.text_input("Title", value=pending["title"], key=f"save_title_{pr}")
        st.text_area(
            "Summary (you can edit this)",
            value=pending["summary"],
            key=f"save_summary_{pr}",
            height=160,
        )
        # Quick-add chips. Prefer the LLM's per-page suggestions; fall back to the
        # fixed list if it produced none. These buttons run BEFORE the text box
        # below is created, so we can safely update its value in session_state,
        # then it renders with the new text. Clicking a chip appends (no dupes).
        chips = pending.get("suggested_keywords") or SUGGESTED_KEYWORDS
        if pending.get("suggested_keywords"):
            st.caption("Suggested keywords (click to add):")
        else:
            st.caption("Quick add keywords:")
        chip_cols = st.columns(len(chips))
        for col, word in zip(chip_cols, chips):
            if col.button(word, key=f"chip_{pr}_{word}"):
                current = st.session_state.get(f"save_kw_{pr}", "")
                parts = [p.strip() for p in current.split(",") if p.strip()]
                if word not in parts:
                    parts.append(word)
                st.session_state[f"save_kw_{pr}"] = ", ".join(parts)

        st.text_input(
            "Keywords (comma-separated, optional)",
            key=f"save_kw_{pr}",
            placeholder="type your own, or use the buttons above",
        )
        st.text_area("Notes (optional)", key=f"save_notes_{pr}", height=80)

        if st.button("💾 Save to library", type="primary"):
            # Need at least a summary or some notes — otherwise there's nothing
            # meaningful to embed for search.
            has_text = (
                st.session_state.get(f"save_summary_{pr}", "").strip()
                or st.session_state.get(f"save_notes_{pr}", "").strip()
            )
            if not has_text:
                st.warning("Please add a summary or some notes before saving.")
            else:
                with st.spinner("Saving... (preparing the summary for search)"):
                    core.add_entry(
                        url=pending["url"],
                        title=st.session_state.get(f"save_title_{pr}", ""),
                        summary=st.session_state.get(f"save_summary_{pr}", ""),
                        notes=st.session_state.get(f"save_notes_{pr}", ""),
                        keywords=st.session_state.get(f"save_kw_{pr}", ""),
                    )
                # Clear everything (including the URL box) and rerun so the form
                # is blank and ready for the next link without a page reload.
                for k in (
                    "pending", f"paste_text_{pr}",
                    f"save_title_{pr}", f"save_summary_{pr}",
                    f"save_kw_{pr}", f"save_notes_{pr}",
                ):
                    st.session_state.pop(k, None)
                # Bump the form key so the URL box comes back empty next run.
                st.session_state["entry_round"] = (
                    st.session_state.get("entry_round", 0) + 1
                )
                st.session_state["just_saved"] = True
                st.rerun()


# ---------------------------------------------------------------------------
# Search mode
# ---------------------------------------------------------------------------

with search_tab:
    st.subheader("Find similar links")
    st.caption("Type a topic, or paste a URL to find saved links most like it.")

    # A form so pressing Enter in the search box runs the search, just like the button.
    with st.form("search_form"):
        query = st.text_input("Search", key="search_query", placeholder="e.g. satellite climate data")
        mode = st.radio(
            "Search by",
            ["Meaning", "Exact text"],
            horizontal=True,
            help=(
                "Meaning ranks saved links by how related their topic is (and "
                "accepts a URL to paste). Exact text finds every entry that "
                "literally contains your words — handy for names like 'Moore'."
            ),
        )
        search_clicked = st.form_submit_button("Search", type="primary")

    top_k = st.slider(
        "How many results?",
        min_value=1,
        max_value=25,
        value=5,
        help="Only applies to Meaning search; Exact text shows every match.",
    )

    if search_clicked:
        # A new explicit search starts a fresh navigation trail. Related-link
        # clicks below build their own history from these new results.
        st.session_state.pop("search_nav_history", None)
        if not query.strip():
            st.warning("Please enter a search term.")
            st.session_state.pop("search_results", None)
        else:
            exact = mode == "Exact text"
            try:
                with st.spinner("Searching..."):
                    if exact:
                        results = core.text_search(query.strip())
                    else:
                        results = core.search(query.strip(), top_k=top_k)
            except Exception as exc:
                st.error(f"Search failed: {exc}")
                results = []
            # Stash results so they survive the reruns triggered by Edit/Save/
            # Cancel buttons below — otherwise the list vanishes (the form isn't
            # re-submitted on those reruns) and the edit form never renders.
            st.session_state["search_results"] = results
            st.session_state["search_was_exact"] = exact

    results = st.session_state.get("search_results")
    if results is not None:
        search_history = st.session_state.get("search_nav_history", [])
        if search_history:
            if st.button(
                "← Back to previous results",
                key="search_related_back",
                type="tertiary",
            ):
                history = list(search_history)
                previous = history.pop()
                st.session_state["search_results"] = previous["results"]
                st.session_state["search_was_exact"] = previous["was_exact"]
                if history:
                    st.session_state["search_nav_history"] = history
                else:
                    st.session_state.pop("search_nav_history", None)
                st.rerun()
            st.caption("Viewing a saved entry selected from Related links.")

        exact = st.session_state.get("search_was_exact", False)
        if not results:
            if exact:
                st.info("No saved links contain that text.")
            else:
                st.info("No matches yet — add some links first.")
        elif exact:
            st.caption(f"Found {len(results)} matching link(s).")
        for r in results:
                rid = r["id"]
                # Separate key prefix ("sedit") so a result here doesn't share
                # edit state with the same entry shown in the Browse tab.
                editing = st.session_state.get(f"sediting_{rid}", False)
                with st.container(border=True):
                    if editing:
                        # --- Edit form (mirrors the Browse tab editor) ---
                        new_title = st.text_input(
                            "Title", value=r["title"], key=f"sedit_title_{rid}"
                        )
                        new_url = st.text_input(
                            "URL", value=r["url"], key=f"sedit_url_{rid}"
                        )
                        new_summary = st.text_area(
                            "Summary", value=r["summary"], key=f"sedit_summary_{rid}", height=160
                        )
                        new_keywords = st.text_input(
                            "Keywords (comma-separated)", value=r["keywords"], key=f"sedit_kw_{rid}"
                        )
                        new_notes = st.text_area(
                            "Notes", value=r.get("notes", ""), key=f"sedit_notes_{rid}", height=80
                        )

                        def _clear_search_edit_state(_rid=rid):
                            for k in (
                                f"sediting_{_rid}", f"sedit_title_{_rid}",
                                f"sedit_url_{_rid}", f"sedit_summary_{_rid}",
                                f"sedit_kw_{_rid}", f"sedit_notes_{_rid}",
                            ):
                                st.session_state.pop(k, None)

                        save_col, cancel_col = st.columns(2)
                        if save_col.button("💾 Save changes", key=f"ssavedit_{rid}", type="primary"):
                            with st.spinner("Saving..."):
                                core.update_entry(
                                    rid, new_title, new_summary, new_notes, new_keywords,
                                    url=new_url.strip(),
                                )
                            # Refresh the cached result in place so the card shows
                            # the edits (the cached list isn't re-fetched on rerun).
                            r.update(
                                url=new_url.strip(),
                                title=new_title,
                                summary=new_summary,
                                keywords=new_keywords,
                                notes=new_notes,
                            )
                            _clear_search_edit_state()
                            st.rerun()
                        if cancel_col.button("Cancel", key=f"scanceledit_{rid}"):
                            _clear_search_edit_state()
                            st.rerun()
                    else:
                        # --- Read-only view ---
                        st.markdown(f"**[{r['title']}]({r['url']})**")
                        if "score" in r:
                            if r.get("keyword_match"):
                                st.caption(f"🏷 keyword match · similarity: {r['score']:.0%}")
                            else:
                                st.caption(f"Similarity: {r['score']:.0%}")
                        st.write(r["summary"])
                        if r["keywords"]:
                            st.caption(f"Keywords: {r['keywords']}")

                        edit_col, map_col = st.columns(2)
                        if edit_col.button("✏️ Edit", key=f"sedit_{rid}"):
                            st.session_state[f"sediting_{rid}"] = True
                            st.rerun()
                        map_on = st.session_state.get(f"smap_{rid}", False)
                        if map_col.button(
                            "✖ Hide map" if map_on else "🗺 Map",
                            key=f"smapbtn_{rid}",
                        ):
                            st.session_state[f"smap_{rid}"] = not map_on
                            st.rerun()
                        if map_on:
                            _render_map(rid)

                        _render_related_links(rid, "search")


# ---------------------------------------------------------------------------
# Browse mode (handy for managing the library)
# ---------------------------------------------------------------------------

with browse_tab:
    st.subheader("Everything in your library")
    all_browse_entries = core.all_entries()
    browse_focus_id = st.session_state.get("browse_focus_id")
    focused_entry = (
        next(
            (entry for entry in all_browse_entries if entry["id"] == browse_focus_id),
            None,
        )
        if browse_focus_id is not None
        else None
    )

    # Recover gracefully if a focused entry was deleted in another session.
    if browse_focus_id is not None and focused_entry is None:
        st.session_state.pop("browse_focus_id", None)
        st.session_state.pop("browse_nav_history", None)
        browse_focus_id = None

    if focused_entry is not None:
        browse_history = st.session_state.get("browse_nav_history", [])
        previous_is_library = bool(browse_history) and browse_history[-1] is None
        back_label = (
            "← Back to all entries" if previous_is_library
            else "← Back to previous entry"
        )
        if st.button(back_label, key="browse_related_back", type="tertiary"):
            history = list(browse_history)
            previous = history.pop() if history else None
            if previous is None:
                st.session_state.pop("browse_focus_id", None)
            else:
                st.session_state["browse_focus_id"] = previous
            if history:
                st.session_state["browse_nav_history"] = history
            else:
                st.session_state.pop("browse_nav_history", None)
            st.rerun()
        st.caption("Viewing a saved entry selected from Related links.")
        entries = [focused_entry]
    else:
        entries = all_browse_entries
        st.caption(f"{len(entries)} saved link(s)")
    if _last_backup_path:
        import os as _os
        st.caption(f"🛟 Auto-backup this session: backups/{_os.path.basename(_last_backup_path)}")

    for e in entries:
        eid = e["id"]
        editing = st.session_state.get(f"editing_{eid}", False)
        showing_map = st.session_state.get(f"map_{eid}", False)

        # Collapsed by default: each row shows only the title until clicked. Keep
        # it expanded while editing or showing the map so they stay visible.
        with st.expander(
            e["title"] or e["url"],
            expanded=editing or showing_map or focused_entry is not None,
        ):
            if editing:
                # --- Edit form ---
                new_title = st.text_input("Title", value=e["title"], key=f"edit_title_{eid}")
                new_url = st.text_input("URL", value=e["url"], key=f"edit_url_{eid}")
                new_summary = st.text_area(
                    "Summary", value=e["summary"], key=f"edit_summary_{eid}", height=160
                )
                new_keywords = st.text_input(
                    "Keywords (comma-separated)", value=e["keywords"], key=f"edit_kw_{eid}"
                )
                new_notes = st.text_area(
                    "Notes", value=e["notes"], key=f"edit_notes_{eid}", height=80
                )

                def _clear_edit_state(_eid=eid):
                    # Drop the editing flag and the field values so the form
                    # reloads from the database next time it's opened.
                    for k in (
                        f"editing_{_eid}", f"edit_title_{_eid}", f"edit_url_{_eid}",
                        f"edit_summary_{_eid}", f"edit_kw_{_eid}", f"edit_notes_{_eid}",
                    ):
                        st.session_state.pop(k, None)

                save_col, cancel_col = st.columns(2)
                if save_col.button("💾 Save changes", key=f"savedit_{eid}", type="primary"):
                    with st.spinner("Saving..."):
                        core.update_entry(
                            eid, new_title, new_summary, new_notes, new_keywords,
                            url=new_url.strip(),
                        )
                    _clear_edit_state()
                    st.rerun()
                if cancel_col.button("Cancel", key=f"canceledit_{eid}"):
                    _clear_edit_state()
                    st.rerun()
            else:
                # --- Read-only view ---
                st.markdown(f"[Open link ↗]({e['url']})")
                st.write(e["summary"])
                if e["keywords"]:
                    st.caption(f"Keywords: {e['keywords']}")
                if e["notes"]:
                    st.caption(f"Notes: {e['notes']}")

                _render_related_links(eid, "browse")

                edit_col, map_col, del_col = st.columns(3)
                if edit_col.button("✏️ Edit", key=f"edit_{eid}"):
                    st.session_state[f"editing_{eid}"] = True
                    st.rerun()
                map_on = st.session_state.get(f"map_{eid}", False)
                if map_col.button(
                    "✖ Hide map" if map_on else "🗺 Map", key=f"mapbtn_{eid}"
                ):
                    st.session_state[f"map_{eid}"] = not map_on
                    st.rerun()
                if del_col.button("🗑 Delete", key=f"del_{eid}"):
                    core.delete_entry(eid)
                    if st.session_state.get("browse_focus_id") == eid:
                        st.session_state.pop("browse_focus_id", None)
                        st.session_state.pop("browse_nav_history", None)
                    st.rerun()
                if map_on:
                    _render_map(eid)


# ---------------------------------------------------------------------------
# Help mode (how to use the app)
# ---------------------------------------------------------------------------

with help_tab:
    st.subheader("How to use Trailhead")
    # Load the documentation fresh on each run so edits to HELP.md appear without
    # restarting. Read it here (not at startup) for the same reason.
    try:
        with open(HELP_PATH, encoding="utf-8") as f:
            st.markdown(f.read())
    except OSError:
        st.warning(
            f"Couldn't load the help file. Expected it at `{HELP_PATH}`. "
            "Create or restore `HELP.md` next to the app to show help here."
        )
