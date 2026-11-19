# Archive and storage vaults

The Archive keeps finished clips after the working folders have moved on, and
can push their video bytes onto an external device. This document is the
contract: the on-disk layout, the vault container format, the state machine and
the failure rules. The user-facing summary is in `LOCAL-SETUP.md`; the page is
`/archive` (`dashboard/src/components/Archive.jsx`).

## Why a separate store

`Storage/videos/<job_id>/` is a render workspace. It is swept after
`JOB_RETENTION_SECONDS`, trimmed by `OUTPUT_MAX_GB`, and its contents are
allowed to change while a job runs. Keeping an archival copy there would mean a
file could disappear long after the user pressed "archive".

Archiving therefore **moves** the chosen video and its poster into
`Storage/archive/files/<id>/` first, and only then records the clip. The sweep
walks the sibling directories (`videos`, `thumbnails`, `uploads`, `downloads`)
and never descends into `archive/`.

## Index

`Storage/archive/archive.db` is a small SQLite database (Python's stdlib
`sqlite3`, WAL mode). The pipeline has no other local database, so this adds no
dependency and stays next to the data it describes.

`items` holds one row per archived clip: its source (`job_id`, `clip_index`),
editorial fields (title, hook, tags, Facebook/YouTube copy, platform marks,
posted time, duration, score, render time), file facts (size, poster
dimensions, SHA-256), and its location (local file names, or vault id + entry
offset). Indices cover state, vault and archive time so the page's filters,
sort and paging are one bounded query.

`vaults` is the registry of known containers. `foreign_vaults` is a transient
list of valid containers found on a connected device that this index does not
know; the page offers to adopt them. `settings` holds the auto-archive rule.

A clip is unique on `(job_id, clip_index)`, so pressing archive twice cannot
duplicate it. Unarchiving deletes the row; a later archive creates a new id.

## Vault container

A vault is one file. Creating it preallocates the whole size (writes bytes, not
just the EOF), so the space is genuinely occupied even while the vault is
empty. Only that file is unavailable to other programs; the rest of the device
is untouched.

```
offset 0                 magic "OSVAULT1\n" + u32 JSON length + manifest
offset 1 MiB (DATA_START) entry 0: 4 KiB header + payload, aligned to 4 KiB
                          entry 1: ...
                          ... up to capacity
```

The manifest is a JSON object:

```json
{
  "format": 1,
  "id": "<uuid>",
  "name": "Backup SSD",
  "key": "<32 hex chars>",
  "capacity": 107374182400,
  "data_start": 1048576,
  "next": 12345678,
  "free": [[offset, length], ...],
  "created_at": 1730000000
}
```

The 1 MiB header region is written padded, so manifest updates are a single
seek/write/fsync and cannot leave a half-written JSON document behind. The
key identifies the vault to the install; it is **not** encryption.

An entry header is also padded JSON:

```json
{"id": "<archive item id>", "name": "Clip title", "size": 5242880,
 "sha256": "...", "created_at": 1730000000, "deleted": false,
 "alloc": 5251072}
```

`alloc` is the padded size (header + payload). It is what the free list records:
deleting an entry rewrites its header with `deleted: true` and returns that
exact range. Allocation is first-fit over the free ranges (merged after every
release), then append at `next`; if neither fits, the push fails with a "vault
is full" message and the local file stays.

Payload is written **before** the entry header and the manifest is updated
**after** the entry is complete and fsynced. A crash mid-push therefore leaves
only unreferenced bytes at `next`, which the next allocation overwrites.

## State machine

Items:

```
archive_clip  ->  local
local + push  ->  pushing
pushing + ok  ->  vaulted        (local video deleted; poster kept)
pushing + err ->  local          (error says why; file stays)
vaulted + restore -> local       (hash-checked copy back; vault space freed)
vaulted + delete, vault connected    -> row deleted
vaulted + delete, vault disconnected -> pending_delete
pending_delete + vault reconnects    -> row deleted
local + unarchive -> row deleted (video/poster back in the job folder)
```

Vaults:

```
create -> creating -> ready
ready + grow -> expanding -> ready
ready/error + delete -> deleted (container and its items removed)
creating + delete -> deleting -> removed
```

Only one worker thread touches containers (`archive-worker`). HTTP handlers
change a row's state and wake it; the page polls every 2.5 s while something is
moving. A second worker can never be started, so two pushes cannot allocate the
same range.

## Verified move

`_push_one` computes the padded need, reads the manifest, allocates, copies the
source while hashing, writes the entry header, rewrites the manifest, fsyncs,
then updates SQLite and deletes the local file. Because the entry header is
written last, the stored SHA-256 is the hash of exactly the bytes on disk.

`restore` copies the range back while hashing and compares it to the stored
hash before removing the vault entry. A mismatch deletes the partial local file
and leaves the vault entry intact.

`return to gallery` (unarchive) works for a local **or** a connected vaulted
clip. A vaulted clip is copied straight into its job folder, hashed, and only
then is the vault entry freed; the archive row and `Storage/archive/files/<id>/`
are removed last, so main storage and the archive never both own the video.

## Device discovery

`mounted_roots()` lists drive roots (`C:\` … `Z:\` on Windows) or the usual
mount points on POSIX. For each known vault the scanner tries its last absolute
path, then `<root>/<file_name>` and `<root>/<rel_folder>/<file_name>`. The
relative folder is recorded at creation, so moving a device from `E:` to `F:`
still reconnects. Any `*.osvault` at a mount root that the index does not know
is offered for adoption; adopting reads its manifest, imports its live entries
and makes their bytes playable immediately.

The maintenance thread scans every 10 s and runs the auto-archive rule every 30
minutes. `GET /api/archive/vaults` triggers at most one scan every 5 s, so a
page refresh cannot hammer a slow device.

## Auto-archive

Off by default. When enabled, only clips posted on **both** Facebook and YouTube
archive themselves, once the most recent post time is older than
`auto_archive_days` (default 7). Clips that were never marked posted are never
touched.

A clip posted on only one platform is **staged**, not moved: the Clip Gallery
shows one button for the YouTube-only group and one for the Facebook-only group
(`archive yt-only (n)` / `archive fb-only (n)`) as soon as that one mark exists.
Nothing leaves the library until that button is pressed, so a half-finished
cross-post cannot lose its file. The decision is derived from the persisted
per-platform marks, so it survives restarts and days when the app was closed.

The gallery also archives exactly the clips selected in selection mode
(`POST /api/archive/clips` with those refs); it never re-scans or touches the
rest of the library.

The page shows the configured `JOB_RETENTION_SECONDS` and warns when the delay
is not shorter than retention, since the sweep would remove the clip first.

## Playback

`/api/archive/items/<id>/video` resolves to either a local file or a
`(container path, payload offset, size)` triple and serves it through one
Range-aware streaming response. A `<video>` therefore seeks normally whether
the bytes are local or inside a vault. When the vault is disconnected the
endpoint answers 409 with the vault name, and the page keeps showing the poster
plus a "connect" prompt instead of a broken player.

Posters are always served from `Storage/archive/files/<id>/`, so the grid looks
the same with every device unplugged.

## Failure rules

- A locked local file (player still open) is retried for ~3 s, then reported;
  the archive row is not created and the file is not moved. The Clip Gallery's
  player releases its `<video>` before asking to archive, so the modal that is
  playing the clip is no longer the lock (Issue #8).
- A locked poster does not undo a successful video move; the card falls back to
  a placeholder.
- A full, fragmented or disconnected vault never deletes the local copy.
- Deleting a vault requires confirmation and a connected device; its archived
  clips are deleted with it.
- Legacy clips archived with the old flag-only mechanism are moved into the
  permanent store once by the maintenance thread; clips whose files are already
  gone are skipped.

## Tests

`tests/test_archive.py` covers preallocation and the manifest, verified pushes,
range reads, restore, offline deletion queues, reconnection, adoption, vault
growth, auto-archive and the API/page wiring. All vaults live in temp folders;
no real `Storage/` or device is touched.
