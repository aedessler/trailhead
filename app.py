"""
app.py — the Streamlit user interface.

Run it with:   streamlit run app.py
(or just double-click run.command)

All the real work lives in core.py; this file is only the screen layout.
"""

import streamlit as st

import core

# Quick-add keyword chips shown under the Keywords box. Edit this list to match
# the tags you use most — clicking a chip adds that word to the Keywords field.
SUGGESTED_KEYWORDS = ["climate", "satellites", "methods", "policy", "data", "modeling"]

# Make sure the database table exists before anything else.
core.init_db()


# Back up the database once per app launch. @st.cache_resource caches the result
# for the life of the process, so this runs once at startup, not on every rerun.
@st.cache_resource
def _startup_backup():
    return core.backup_database()


_last_backup_path = _startup_backup()

st.set_page_config(page_title="Link Library", page_icon="🔖", layout="centered")
st.title("🔖 Link Library")

entry_tab, search_tab, browse_tab = st.tabs(["➕ Add a link", "🔎 Search", "📚 Browse all"])


# ---------------------------------------------------------------------------
# Entry mode
# ---------------------------------------------------------------------------

with entry_tab:
    st.subheader("Add a link")

    # Show a one-time confirmation after a save cleared the form.
    if st.session_state.pop("just_saved", False):
        st.success("Saved! The form is cleared — ready for your next link.")

    # A form so that pressing Enter in the URL box is the same as clicking the
    # button (Streamlit submits a form when you press Enter in one of its fields).
    with st.form("fetch_form"):
        url = st.text_input("Paste a URL", key="entry_url", placeholder="https://...")
        fetch_clicked = st.form_submit_button("Fetch & Summarize", type="primary")

    if fetch_clicked:
        if not url.strip():
            st.warning("Please paste a URL first.")
        else:
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
            except Exception as exc:
                # Don't dead-end: fall back to manual entry so the user can still
                # save the link with their own summary/notes (or paste page text).
                st.warning(
                    f"Couldn't automatically read this page ({exc}) — it may need "
                    "JavaScript to load. You can enter the details yourself below, "
                    "or paste the page's text and have it summarized."
                )
                st.session_state["pending"] = {
                    "url": url.strip(),
                    "title": "",
                    "summary": "",
                    "manual": True,
                }

    # If we have a fetched-and-summarized page waiting, show the editable form.
    pending = st.session_state.get("pending")
    if pending:
        st.divider()

        # If automatic reading failed, offer to summarize text the user pastes in.
        if pending.get("manual"):
            with st.expander("📋 Paste the page's text to summarize it (optional)"):
                pasted = st.text_area("Paste page text here", key="paste_text", height=160)
                if st.button("Summarize pasted text"):
                    if pasted.strip():
                        with st.spinner("Summarizing..."):
                            pending["summary"] = core.summarize(pasted.strip())
                        with st.spinner("Suggesting keywords..."):
                            try:
                                pending["suggested_keywords"] = core.suggest_keywords(
                                    pending["summary"]
                                )
                            except Exception:
                                pending["suggested_keywords"] = []
                        st.session_state["pending"] = pending
                        # Drop the box's stored value so it reloads with the new summary.
                        st.session_state.pop("save_summary", None)
                        st.rerun()
                    else:
                        st.warning("Paste some text first.")
            st.caption("Or just write your own summary/notes below.")
        else:
            st.caption("Review and edit before saving:")

        st.text_input("Title", value=pending["title"], key="save_title")
        st.text_area(
            "Summary (you can edit this)",
            value=pending["summary"],
            key="save_summary",
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
            if col.button(word, key=f"chip_{word}"):
                current = st.session_state.get("save_keywords", "")
                parts = [p.strip() for p in current.split(",") if p.strip()]
                if word not in parts:
                    parts.append(word)
                st.session_state["save_keywords"] = ", ".join(parts)

        st.text_input(
            "Keywords (comma-separated, optional)",
            key="save_keywords",
            placeholder="type your own, or use the buttons above",
        )
        st.text_area("Notes (optional)", key="save_notes", height=80)

        if st.button("💾 Save to library", type="primary"):
            # Need at least a summary or some notes — otherwise there's nothing
            # meaningful to embed for search.
            has_text = (
                st.session_state.get("save_summary", "").strip()
                or st.session_state.get("save_notes", "").strip()
            )
            if not has_text:
                st.warning("Please add a summary or some notes before saving.")
            else:
                with st.spinner("Saving... (preparing the summary for search)"):
                    core.add_entry(
                        url=pending["url"],
                        title=st.session_state["save_title"],
                        summary=st.session_state["save_summary"],
                        notes=st.session_state.get("save_notes", ""),
                        keywords=st.session_state.get("save_keywords", ""),
                    )
                # Clear everything (including the URL box) and rerun so the form
                # is blank and ready for the next link without a page reload.
                for k in (
                    "pending", "save_title", "save_summary", "save_keywords",
                    "save_notes", "paste_text", "entry_url",
                ):
                    st.session_state.pop(k, None)
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
        search_clicked = st.form_submit_button("Search", type="primary")

    top_k = st.slider("How many results?", min_value=1, max_value=25, value=10)

    if search_clicked:
        if not query.strip():
            st.warning("Please enter a topic or URL.")
        else:
            try:
                with st.spinner("Searching..."):
                    results = core.search(query.strip(), top_k=top_k)
            except Exception as exc:
                st.error(f"Search failed: {exc}")
                results = []

            if not results:
                st.info("No matches yet — add some links first.")
            for r in results:
                with st.container(border=True):
                    st.markdown(f"**[{r['title']}]({r['url']})**")
                    if r.get("keyword_match"):
                        st.caption(f"🏷 keyword match · similarity: {r['score']:.0%}")
                    else:
                        st.caption(f"Similarity: {r['score']:.0%}")
                    st.write(r["summary"])
                    if r["keywords"]:
                        st.caption(f"Keywords: {r['keywords']}")


# ---------------------------------------------------------------------------
# Browse mode (handy for managing the library)
# ---------------------------------------------------------------------------

with browse_tab:
    st.subheader("Everything in your library")
    entries = core.all_entries()
    st.caption(f"{len(entries)} saved link(s)")
    if _last_backup_path:
        import os as _os
        st.caption(f"🛟 Auto-backup this session: backups/{_os.path.basename(_last_backup_path)}")

    for e in entries:
        eid = e["id"]
        editing = st.session_state.get(f"editing_{eid}", False)

        # Collapsed by default: each row shows only the title until clicked. Keep
        # it expanded while editing so the form stays visible.
        with st.expander(e["title"] or e["url"], expanded=editing):
            if editing:
                # --- Edit form ---
                new_title = st.text_input("Title", value=e["title"], key=f"edit_title_{eid}")
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
                        f"editing_{_eid}", f"edit_title_{_eid}", f"edit_summary_{_eid}",
                        f"edit_kw_{_eid}", f"edit_notes_{_eid}",
                    ):
                        st.session_state.pop(k, None)

                save_col, cancel_col = st.columns(2)
                if save_col.button("💾 Save changes", key=f"savedit_{eid}", type="primary"):
                    with st.spinner("Saving..."):
                        core.update_entry(
                            eid, new_title, new_summary, new_notes, new_keywords
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

                edit_col, del_col = st.columns(2)
                if edit_col.button("✏️ Edit", key=f"edit_{eid}"):
                    st.session_state[f"editing_{eid}"] = True
                    st.rerun()
                if del_col.button("🗑 Delete", key=f"del_{eid}"):
                    core.delete_entry(eid)
                    st.rerun()
