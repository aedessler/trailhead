#### 🛟 How this works

All your links live in a single `library.db` file in the app folder. **Every
time the app launches** it saves a timestamped copy into `backups/` and keeps
the 5 most recent — the list above is exactly what you have right now.

**To restore one:** quit Trailhead, open the app folder, copy the snapshot you
want out of `backups/`, and rename the copy to `library.db` (replacing the one
that's there). Start the app again and you're on that version.

---

#### 🖼 Images are handled separately

Saved pictures live in the **`images/` folder**, not inside `library.db`. That
keeps the database small so the every-launch backup stays fast — but it also
means the `.db` snapshots above **do not contain your pictures**. Keep `images/`
with the project when you move or copy it.

They get their own backup instead: every launch, any new picture is copied into
`backups/images/`, alongside a `manifest.json` recording each file's size and
checksum. Each launch also checks the images you already have, and **anything
missing or damaged is put back from that copy automatically** — you'll see a
note above when that happens. **🔍 Verify all images** runs a deeper check on
demand, comparing full checksums rather than just file sizes, which catches
damage that happens to leave the file the same length.

If a file and its backup copy *both* disagree with the manifest, the app reports
it as damaged and changes nothing, rather than guessing which one is good.

---

#### 🧹 Cleaning up unused images

Deleting an entry leaves its image file behind on purpose — that way, restoring
an older snapshot always finds every picture it refers to. Those leftovers add
up, so when there are any you'll get a **🧹 unused image file(s)** panel above.

By default, cleaning up clears `images/` but **keeps the backup copy**, so the
picture stays recoverable and older snapshots still restore correctly. Tick
**Also delete the backup copies** to reclaim the space for good — that one can't
be undone.

Do that a few times and `backups/images/` fills with copies that have nothing
left to protect. **🗑 Clear N stale backup copy(s)**, beside the verify button,
removes exactly those: mirrored files whose original is gone from `images/`
*and* that no entry refers to. A picture an entry still needs is never touched,
even when its original has vanished — that's the one case where a copy with no
original is the mirror doing its job, and you'll see a warning about it instead.

---

#### 🧠 What built your search vectors

Semantic search works by turning every entry into a list of numbers with a small
model that runs on your Mac. Those numbers are only comparable with each other
if the *same* model made all of them — two different models place the same text
in different spots, so a library holding both would rank badly with nothing to
show for it.

So the library records which model built it, along with a fingerprint of that
model's output, and checks both on every launch. Nothing appears unless they
stop matching, in which case you get a warning at the top of the app. The fix is
always the same: re-do every entry with the new model, or go back to the old one.

---

> ⚠️ The backup copies sit on the **same disk** as the originals. They protect
> you from an accidental delete, a bad cleanup, or a corrupted file — **not**
> from losing the drive or the folder. Keeping the whole Trailhead folder in
> iCloud, Dropbox, or Google Drive covers that.
