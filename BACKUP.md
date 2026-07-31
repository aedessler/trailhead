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

---

> ⚠️ The backup copies sit on the **same disk** as the originals. They protect
> you from an accidental delete, a bad cleanup, or a corrupted file — **not**
> from losing the drive or the folder. For that, keep a copy of the whole
> Trailhead folder somewhere else.

> ⚠️ Don't put the live `library.db` inside iCloud, Dropbox, or Google Drive —
> cloud sync can corrupt a database while it's being written to. Keeping
> *copies* of your backups in the cloud is fine, and is a good idea.
