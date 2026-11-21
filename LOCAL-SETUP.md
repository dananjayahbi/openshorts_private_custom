# Local setup — Windows 11 / i7 10th gen / GTX 1660 Ti 6 GB

Everything below is already applied in this fork. It is the map of what was
changed, why, and how to run it.

## Run it (native — no Docker)

```powershell
.\setup-native.ps1            # once: venv on F:, torch cu128, npm deps, fonts
.\start.bat                   # one visible CMD window per service + browser
.\stop.bat                    # stop all three
.\start-native.ps1            # same three services, hidden windows, logs in logs\
.\start-native.ps1 -Stop
```

`start.bat` is the interactive launcher: it opens **API**, **Renderer** and
**Dashboard** in separate CMD windows so each keeps streaming its own log, and
opens the dashboard once Vite answers. `start-native.ps1` is the headless
equivalent (hidden windows, output in `logs\`), useful for automation.

| Service | URL |
|---|---|
| **Dashboard** | http://localhost:18481 |
| API | http://localhost:18480 (`/docs`, `/health/ready`) |
| Renderer (Remotion) | http://localhost:18482 |

Logs land in `logs\api.log`, `logs\dashboard.log`, `logs\renderer.log` when
started with `start-native.ps1`.

The dashboard is a single-viewport shell: the top bar and phone tab bar stay
put, and each page scrolls inside its own pane (never the document). Panes
contain their scroll (`overscroll-contain`), so a wheel or swipe at the end of
one page cannot drag the shell behind it. Pages use the full width of the pane
(no centered `max-w` container); only running text keeps a reading-width cap.

The venv lives **outside the repo** (`F:\openshorts-venv`, override with
`OPENSHORTS_VENV`) so the repo drive keeps its free space for rendered clips.
The pip cache is `F:\pip-cache`. Both are deliberately off the E: volume.

## Storage — two roots, and nothing is deleted for you

The tree is split in two (`storage.py`):

```
Storage/                     small state, always next to the app
  settings.json, style_profiles.json
  clip_state.json            review status + platform/used marks
  content_plan.json          the Content Planner calendar
  thumbnails/<session_id>/...                        -> /thumbnails/...

<media>/                     large media (start.bat: D:\OpenShorts\Storage)
  videos/<job_id>/...        clips, sources, metadata -> /videos/<job_id>/...
  uploads/                   transient sources (not served)
  downloads/<id>/...         Download Manager sources (not served)
  collector/                 the Collector shelf           -> /collector/...
  archive/                   permanent clips + archive.db (not served)
```

- `OPENSHORTS_STORAGE` moves the small state root. `OPENSHORTS_MEDIA` moves the
  media root; when it is unset both are the same `Storage/` tree, which keeps an
  old install and the test suite working unchanged. `start.bat` sets the media
  root to `D:\OpenShorts\Storage`.
- **The external drive may be unplugged.** The API still starts, the dashboard
  shows a "media drive not connected" banner, and the media tree is recreated
  when the drive is plugged back in (the background loop calls
  `storage.ensure_media()`). Nothing is lost: every path is derived from the
  root, and the small state never leaves the app drive.
- `OUTPUT_DIR` is `<media>/videos`, `UPLOAD_DIR` is `<media>/uploads`, and
  `THUMBNAILS_DIR` is `Storage/thumbnails`. Every `os.path.join(OUTPUT_DIR,
  job_id, ...)` in the pipeline keeps working and the URL mounts are unchanged.
- **No automatic deletions.** `OUTPUT_MAX_GB=0` and `UPLOADS_MAX_GB=0` disable
  the size caps, and `JOB_RETENTION_SECONDS=0` / `SOURCE_RETENTION_SECONDS=0`
  mean "keep forever". The old defaults (24 h + a 10 GB output cap measured on
  `videos/` only) are what silently removed finished renders. Set a positive
  number only if you actually want the sweeps. Deleting a clip from the gallery
  is still a manual action.
- The dashboard home page reports the app's footprint across both roots and the
  free space on the media volume.
- The folders are git-ignored. The old `output/` and `uploads/` trees were
  removed when this layout landed.

## Overnight queue (bulk + streamed)

Turn on **bulk mode**, add the videos (files, links, or Collector items), then
turn on **streamed video**. The generator shows one row per video with its own
`1. box` / `2. prevent` buttons: each row stores its own streamer crop and
prevention area, so a batch of 20 streamers is marked once and then left alone.
`copy previous` reuses the last row's boxes when the cam layout is the same.

Pressing generate submits one normal job per row, one at a time. A failure is
recorded on its row (with the server's error line) and the next video loads; a
job that reports no progress for 45 minutes is cancelled and skipped. At the
end, the failed rows are retried once automatically, then ignored. The queue
banner shows the count, opens a per-row detail list when anything failed, and
holds a screen wake lock while it runs, so you can start it and go to sleep.

Details: `docs/architecture/streamer-mode.md`.

## Collector — find now, process later

A new **Collector** page separates finding videos from clipping them:

- **Add a link**: only metadata and the thumbnail are fetched (tens of KB), no
  video bytes. The card shows the title, channel, duration and "link only".
- **Download**: fetches the video into `Storage/collector/files` when you are
  ready; the card switches to "on disk".
- **Upload**: a local file is stored immediately (`Storage/collector/files`)
  with a poster frame taken 30 s in (the midpoint for clips shorter than that).
- **Queue**: any card can be put in the queue. "Process queue" processes them
  one at a time, in order.
- **Process**: opens the Clip Generator with that video already selected, so the
  output format and options are chosen before a job starts.

In the Clip Generator, source tab **Collector** opens a full-viewport picker
over the shelf. **Bulk Mode** applies to all three sources — several uploads,
one URL per line, or a multi-select from the collector — and the batch runs
sequentially with per-item progress (the clips land in the Clip Gallery as each
job finishes). The queue button works from either the Collector page or the
Clip Generator.

The queue **uses the ordinary single-video screen**, one video at a time: the
same processing view, log tail and clip cards as a manual run. When a video
finishes its clips are already in the Clip Gallery; the screen says so and then
shows **"Preparing the environment for the next video"**, clears the previous
job and starts the next one automatically. A slim line above the workspace shows
`done/total` and the current video with **stop queue**. A failed video shows the
pipeline's own last line — an AI provider that returned nothing, a download
error, a source with no audio — and the queue continues; **retry failed** re-runs
only those videos, so a transient error in video 2 does not repeat videos 1–4.
`new` while a queue runs stops it (clips already finished stay in the gallery).

| Piece | Where |
|---|---|
| Index (not served) | `Storage/collector/items.json` |
| Videos | `Storage/collector/files/<item>_<name>.mp4` |
| Posters | `Storage/collector/thumbs/<item>.jpg`, served at `/collector/thumbs/...` |
| API | `GET/POST /api/collector`, `POST /api/collector/upload`, `POST /api/collector/{id}/download`, `POST /api/collector/{id}/queue`, `DELETE /api/collector/{id}` |
| Processing | `POST /api/process` accepts `collector_id`; a downloaded file is hardlinked into the job, so the collector keeps its copy |

## Download Manager: full sources in temp, split into the Collector

`/download-manager` (nav 04) fetches whole videos for editing elsewhere. Paste
one link or several (one per line) and the server downloads them **one at a
time** into `Storage/downloads/<id>/` — yt-dlp with the same public-address guard
and provider chain as a job. The item shows its live byte progress (the temp
file's size against the probed size), title, length and state.

Each item has its **own part length** in minutes (default 20). 1.5 h at 20 min
becomes five items on the Collector (four 20-minute parts and the 10-minute
remainder). **split into parts** cuts one item; **start split queue** walks every
ready item one by one, so a batch can mix 20-minute and 1-hour parts. The split
uses ffmpeg's segment muxer with stream copy (fast; boundaries land on
keyframes, so a part can be a second or two off the exact wall-clock length).
Every part is handed to `collector.add_file` and appears on the shelf with a
poster and duration, ready to clip.

| Piece | Where |
|---|---|
| Index (not served) | `Storage/downloads/items.json` |
| Sources (not served) | `Storage/downloads/<id>/` |
| API | `GET/POST /api/downloads`, `PATCH /api/downloads/{id}`, `POST /api/downloads/{id}/split`, `POST /api/downloads/split-all`, `DELETE /api/downloads/{id}` |
| Output | `POST /api/downloads/*` never touches the Collector until a split; then the parts are normal Collector items |
| Cleanup | deleting a download removes its temp source only; the Collector parts stay |

Downloads and splits are server-side threads, so navigating away does not stop
them. A failed link becomes an error item (with the reason) instead of failing
the batch; a failed split goes back to **ready to split** with the ffmpeg error.
Deleting is refused while an item is queued, downloading or splitting.

## Streamed videos: the streamer split

On the Clip Generator, **streamed video** can be enabled for one video or for a
whole bulk queue. A button opens a modal that plays the original source at its
true aspect ratio; drag a box over the streamer's webcam/section. The box can be
moved and resized freely — its shape sets the split (a 16:9 cam takes about a
third of the frame, 9:8 the even 50/50) — and is saved as fractions of the
source frame.

- **Bulk + streamed:** each queued row has its own `1. box` / `2. prevent`
  buttons, so one row's crop can never be applied to another video. `copy
  previous` reuses the last row's boxes. Generate accepts the batch only when
  every row has at least a streamer box; each job then carries its own two
  rectangles.

- A local upload plays straight from the browser. A Collector item plays its
  downloaded copy. A link is downloaded into the Collector first and then
  reused by the job (`POST /api/streamer/prepare`), so it is not fetched twice.
- **Prevention area** (optional, second box in the same modal): mark the
  streamer's whole cam or any overlay the clip's half must never show. The
  clip's tracked crop is framed around it, so the streamer cam does not appear
  in the bottom half. It is independent of the streamer box, which is often only
  a zoom on the face. Pick the box with the `streamer box` / `prevent area`
  chips: only the selected box takes the pointer, so dragging over the cam while
  `prevent area` is selected draws that box instead of moving the streamer box.
  `copy streamer box` gives a starting point.
- The render composes the two panels into the normal 9:16 delivery: the marked
  streamer crop on top, and the viral clip below rendered at the shape that is
  left (full bleed, no blurred filler). The viral clip's audio is kept.
- Both marked boxes are blanked for the face/person tracker, so the bottom half
  follows the clip's own subject instead of the streamer.
- Captions/hooks are burned after composition. Captions sit on the line between
  the two panels; their style is otherwise unchanged. The AI prompts are told
  the source is a stream (streamer reactions matter, not long gameplay
  stretches).
- If the box is invalid, its shape leaves a panel outside 15%–85% of the frame,
  or the composition fails, the normal reframed clip is kept and the reason
  appears in the job log.

Details: `docs/architecture/streamer-mode.md`.

## Archive: permanent clips and external storage vaults

`/archive` (nav **Archive**) is the permanent home for clips you are done with.
Archiving moves the clip's video and poster out of `Storage/videos/<job_id>/`
into `Storage/archive/files/<id>/` **before** the retention sweep can touch
them, and records the clip in `Storage/archive/archive.db` (SQLite, stdlib).
The gallery's "archive" button, "archive used (N)", and the optional
auto-archive rule all feed this page; the old flag-only archive is migrated on
the first start after upgrading.

- **Filters** — search, archived date, vault, state (on this PC / in a vault /
  queued delete / missing), posted platform, sort (newest, oldest, duration,
  score, size) and page size. Every filter, sort and page is one indexed SQL
  query, so thousands of clips stay cheap.
- **Thumbnails stay local.** A vaulted clip keeps its poster, title, tags and
  copy; only the video bytes live on the device.
- **Auto-archive** — optional; clips posted on **both** platforms longer than N
  days ago are archived on the next maintenance pass. One-platform clips are
  staged behind the gallery's two buttons instead of moving on their own. The
  page warns when the delay is longer than `JOB_RETENTION_SECONDS`, because the
  sweep would remove them first.

### Vaults

A vault is one preallocated `<name>-<id8>.osvault` file on a chosen folder of a
device (flash drive, external HDD/SSD, network mount). Creating it writes the
whole file out so the space is really reserved; the rest of the device stays
usable. A 1 MiB header holds the manifest (id, name, key, capacity, allocation
pointer, free ranges); entries are `4 KiB header + payload`, block aligned.

| Action | What happens |
|---|---|
| Add vault | Pick a device folder, name it and set its size in GB. A worker writes the file; the card shows progress. |
| Scan | Every 10 s, and on **rescan**: mounted roots are searched for known vault files (so a new drive letter still reconnects) and unknown ones are offered for **adopt**. |
| Push | Verified move: copy into the container while hashing, compare SHA-256, then delete the local file. The queue runs one item at a time with live progress; a full vault leaves the local copy untouched. |
| Play | While the vault is connected, `/api/archive/items/{id}/video` streams the entry's bytes with HTTP Range support (seeking works). Disconnected cards say which vault to connect. |
| Restore | Copy an entry back to local archive storage (hash-checked), then free its space in the vault. "Return to gallery" also works directly for a vaulted clip while its vault is connected: it verifies the copy into `Storage/videos/<job_id>/`, frees the vault entry, and removes the archive copy. |
| Delete | Local files go immediately. A vaulted clip whose device is unplugged becomes **queued delete** and is removed automatically on reconnect. |
| Grow / delete vault | Grow-only (the file is extended); deleting a vault wipes its container and the archived clips inside it, after confirmation. |

| Piece | Where |
|---|---|
| Index | `Storage/archive/archive.db` |
| Videos + posters | `Storage/archive/files/<id>/` |
| Vault file | the folder you pick, `<name>-<id8>.osvault` |
| API | `GET /api/archive/items`, `POST /api/archive/clips`, `POST /api/archive/items/push`, `.../items/restore`, `.../items/unarchive`, `.../items/delete`, `GET /api/archive/items/{id}/video`, `.../poster`, `GET/POST /api/archive/vaults`, `PATCH/DELETE /api/archive/vaults/{id}`, `POST /api/archive/vaults/scan`, `.../adopt`, `GET /api/archive/devices`, `.../browse`, `GET/PATCH /api/archive/settings` |

Vault files are not encrypted: the key in the header identifies the vault to
this install, it does not protect the video. Keep the device itself safe.

## Clip Gallery: compact tiles, a full-viewport player, delete

The library is a grid of small square posters (the viral score top-left, the
platform marks and duration bottom-right, the title under it). A tile does not
play inline: clicking it opens a full-viewport modal with the real player, the
score, the five tags, the Facebook post and the clean YouTube title and
description (each with a copy button), the Facebook/YouTube marks, archive and
**delete**. Escape or the backdrop closes it.

Each tile is a **JPEG still**, not a video: the API writes `poster_clip_N.jpg`
(a frame about a second in, 640 px wide) next to the clip, caches it, and the
grid loads that. The tiles used to point a `<video preload="metadata">` at the
clip, which browser download managers read as "save this MP4" — merely opening
the gallery or the home page started a shelf of MP4 downloads. Only the modal
player now loads video bytes. `ffmpeg` failures are quiet (the tile keeps its
empty frame; the clip still opens), and a missing poster is made once per page
and reused on every later request.

- **Delete** — the hover trash on a tile, or the modal's delete, opens an
  in-app confirmation (`ConfirmDeleteModal`) instead of `window.confirm`,
  which is unstyleable and is silently suppressed in some in-app browsers.
  It names the clip(s), warns that every rendered file is removed for good,
  and puts focus on **keep it**; Escape (captured before the player's own
  Escape handler) or the backdrop cancels, a failed delete keeps the dialog
  open with the error, and the dialog stacks above the clip player. Confirming
  removes every file of that clip (clean cut, captioned/subtitled and
  watermark twins, layout sidecar, poster JPEG), its review state key, and the
  card. **select** enters selection mode (checkboxes, select all);
  **delete (n)** opens the same dialog for the selected clips and removes them
  in one call. The job's metadata entry stays so the remaining clips keep
  their index/file pairing; the gallery skips an index with no file.
- **A file held open** (a paused player, or a download manager saving the
  MP4 — the exact situation the old `<video>` tiles caused) makes Windows
  refuse the delete. The endpoint retries for ~3 s, then answers **409** with
  *"still open in another program … close it and try again"*; the dialog keeps
  the clip and the message, and the review state is not forgotten, so a retry
  still knows it was marked used/archived. Bulk delete does not abort: the rest
  go, and `failed` names the refs that stayed.
- API: `DELETE /api/gallery/clip/{job_id}/{index}` (409 when locked) and
  `POST /api/gallery/delete {"clips": [...]}` (validated, max 200, returns
  `{deleted, files, failed}`).
- The score is the moment picker's `predicted_score`, unchanged since the clip
  was chosen.

Each clip card shows the **viral score** the moment picker predicted and its
**five tags** (`tags` in the job's metadata, comma-separated, one copy button).
The tags are written in the same detail call as the title/hook, so they cost no
extra request; `clip_tags.five` normalises the answer (lowercase, no `#`,
deduped) and tops it up from the clip's own hashtags/title so every clip has
exactly five. Clips rendered before the field existed get five derived from
their title/description on read, without rewriting old metadata.

Copy is shaped for the two platforms this install publishes to (`clip_copy.py`):

- `facebook_title` — the post body, two blank lines, then exactly five hashtags
  built from `tags`.
- `youtube_title` — clean, no hashtags, at most 100 characters.
- `youtube_description` — a 250-500 character summary, no hashtags.
- `tags` — the same five words, for YouTube's separate tag field.

The detail and vision prompts ask for these fields directly; the old
`video_description_for_tiktok` / `video_description_for_instagram` keys are no
longer written and are only read as a fallback for clips rendered before the
split.

Each clip has two pieces of review state, stored in
`Storage/clip_state.json` (keyed `<job_id>:<index>`, so a re-render that renames
the file keeps them):

- **Posted on Facebook / YouTube** — two independent marks, because the same
  clip can be out on one platform and still pending on the other. Marking
  either makes the clip **used** (the Used tab counts a clip if it is on at
  least one platform); clearing both makes it unused again. The card shows the
  platforms it is on. `PATCH /api/gallery/clip/{id}/{index}` takes
  `{"platform": "facebook", "posted": true}` or
  `{"platforms": {"facebook": true, "youtube": false}}`; the legacy
  `{"used": true}` still works and converts on the first platform toggle.
- **Archived** — moves the clip out of the working folder into the Archive page
  (the file is kept permanently there). Restoring returns it to the gallery
  while the job folder and its metadata still exist; **archive used (N)** moves
  every used clip in one call, and in **select** mode **archive (n)** moves only
  the clips you ticked (`POST /api/archive/clips` with those refs).
- **Staged platforms** — when auto-archive is on, a clip posted on only YouTube
  or only Facebook does not move by itself. As soon as it has that one mark, the
  header offers **archive yt-only (n)** and **archive fb-only (n)**; pressing
  one archives exactly that group. Clips posted on both platforms archive
  automatically after the delay, and the times come from the persisted
  per-platform marks, so the delay elapses while the app is closed.

Filtering and paging happen server-side (`GET /api/gallery/clips`) before the
page is cut, so the tab badges, the pager and the grid agree with each other:

- `limit` (max 100) + `page`, or the legacy `offset`; the answer carries
  `total`, `page`, `pages` and `has_more`. A page past the end is clamped, not
  an error, so a stale link lands on the last page.
- `view=active|archived|all` and `usage=any|used|unused` (the three active tabs;
  archived cards now live on the Archive page).
- `status=any|accepted|staged|unreviewed` — the Sorter decision. The dashboard
  sends `accepted` so the gallery opens on publishable clips; `any` is the API
  default, keeping older callers and the whole library available.
- `platform=any|youtube|facebook|both|none` — the independent per-platform
  marks, not just the combined used flag.
- `date=any|today|yesterday|week|month|custom` with `date_from`/`date_to`
  (`YYYY-MM-DD`, both ends inclusive) for a custom range. Bounds are local
  time and apply to the job's render time (its metadata file's mtime — the
  directory's own mtime moves whenever a poster is written).
- `sort=newest|oldest|longest|shortest|score` — sorting happens on the whole
  filtered set before the page is cut, so "longest" is the longest in the
  library, not on the page.
- `q=` searches title, hook, tags, the Facebook post, the YouTube description
  and the job id.

The web UI sends every one of these through its filter bar (search, rendered
date, posted-on chips, sort, per-page size) and shows numbered server-side
pages with prev/next instead of the old infinite scroll.

`PATCH /api/gallery/clip/{job_id}/{index}` sets the flags;
`POST /api/gallery/archive-used` archives every used clip (the button is hidden
while a date/platform/search filter is active, because the call itself is not
filtered), and `GET /api/gallery/archive-staged` lists the single-platform
groups while `POST /api/gallery/archive-staged` with `{"platform": "youtube"}`
runs one. Stale keys for deleted jobs are pruned on the next scan.

The modal player letterboxes the clip with `object-fit: contain` instead of
cropping it, so a 16:9 or 1:1 render is shown in full.

## Sorter: accept, stage or reject

`/sorter` is the review queue for clips that have no decision yet. One clip
plays at a time; **Accept** is the large left button, **Reject** the large right
one, and **Stage for later** sits underneath them (the smaller, less dangerous
choice). Reject opens the same in-app delete confirmation as the gallery and
then removes every rendered file for that clip; there is no stored `rejected`
state. Keyboard: `←` or `A` accepts, `→` or `R` rejects, `↓` or `S` stages.

The decision lives in `clip_state.json` as `accepted` or `staged` (missing means
`unreviewed`), so it survives a re-render and is shared by the gallery. The
gallery's **review status** filter opens on `accepted`; choose `staging`,
`unreviewed` or `all` to see the other piles. The clip modal can also change the
status of a clip after the fact.

## Content Planner: the publishing calendar

`/content-planner` is a Sunday-to-Saturday month calendar. Each day holds
icon-sized posters of the clips planned for it; click one to open the same
full-viewport clip modal as the gallery (play it, mark it posted, change its
status). The **add** button on a day opens a picker over the gallery — accepted
clips by default, staging/all on request, with search — and adds the chosen
clip to that day. A clip may appear on multiple days but not twice on one day.

The green ring around a planned thumbnail means the clip is already marked used
on a platform; its `fb` / `yt` marks are the same per-platform flags the gallery
and the clip modal edit. The plan itself is `content_plan.json` in the small
state tree (next to settings), so unplugging the media drive keeps the calendar;
the clip metadata and posters come back when the drive is plugged in again.

## Storage numbers

The Home storage meter reads **used = the `Storage/` folder**, **total = the
space the drive still has available**, with the raw capacity in the caption.
Before, the total was the whole 310 GB drive, so a disk with 22 GB left looked
almost empty. The API returns `usedGb`, `totalGb` (available), `freeGb` and
`capacityGb` from `GET /api/overview`.

## Branding — Clip Studio

This private build is named **Clip Studio** and carries no upstream surface:
no GitHub links, star banner, repo/skill cards, hosted pricing, contact address,
screenshots, promo videos or SEO/OpenGraph metadata. `index.html` is a plain app
shell, the drawer footer is gone, and the MCP snippets point at this machine
(`/api/config` → `publicApiUrl`, from `PUBLIC_API_URL`). The MCP server's
protocol name stays `openshorts` (client configs and tooling use it); only the
displayed title is Clip Studio. `LICENSE` / `NOTICE` keep the upstream MIT
attribution.

## Playground, Style Profiles, and captions before the render

The caption look used to be editable only AFTER a clip was rendered. It is now
chosen before the job starts:

- **Clip Generator** → under the output format: a **style profile** selector
  (default **auto · current defaults**, so the shipped look is used without a
  choice) and a **burn captions** toggle. The full caption editor is no longer
  in advanced options: the generator picks a profile, and the look is sent as
  `caption_style` on `/api/process`. Choosing auto clears the last profile's
  look back to the shipped default.
- **Playground** (`04`) — the full editor (presets, font, size, colour,
  highlight, border, background box, position, uppercase, reveal, dim, shadow,
  animation, max chars/block) on a bigger stage, over a real clip from the
  library (or a neutral stage), with sample text, output format and hook style.
  Save the combination as a profile.
- **Style Profiles** (`05`) — the saved bundles. **use** applies one to the Clip
  Generator (the generator then sends that look); **edit** reopens it in the
  Playground; **delete** removes it. Cards render the saved look.

A profile is:

```json
{ "name": "Gaming vertical",
  "caption": { "style": "karaoke", "font_name": "Impact", "font_size": 56, ... },
  "output":  { "output_format": "vertical", "layouts": ["auto"], "auto_hook": true,
               "auto_hook_style": "pill", "target_clips": 5 },
  "prompts": { "detail": "…optional override…" } }
```

Stored in `Storage/style_profiles.json`; managed through
`GET/POST/PATCH/DELETE /api/style-profiles`. `/api/process` also accepts
`style_profile_id` (an agent can name a profile instead of repeating fields);
explicit request fields win over the profile, so an agent can apply one and
override individual fields.

Pipeline side: `/api/process` validates the look (`caption_style.py`) and sets
`AUTO_CAPTION_STYLE_JSON`; `main.auto_caption_clip` merges it over
`subtitles.AUTO_CAPTION_STYLE`, derives `max_chars` from the chosen font/size
when not supplied, and burns it. The effective look is written to each clip's
metadata (`caption_style`), so a later hook/edit/recut re-burns the same look
instead of silently reverting to the default. Verified end to end: a job with
`position=top, font=Impact, highlight=#00FF88, bg_opacity=0.35, shadow=2`
produced an ASS with `Alignment 8`, `Impact 47`, `&H0088FF00` and the shadow
colour, and the clip shipped with it.

## Stopping a job (single or queue)

**stop** sits next to the status badge while a single job renders, and in the
batch header while a queue runs. Both call `POST /api/jobs/{job_id}/cancel`:

- a **queued** job is taken off the heap and never starts;
- a **running** job has its process tree killed (`taskkill /T /F` on Windows),
  so main.py *and* its ffmpeg/NVENC children stop writing;
- the job becomes `cancelled` (not `failed`), no auto-retry or delivery runs,
  and no webhook/email is sent;
- once the process lets go of its files, the purge removes
  `Storage/videos/<job_id>` (partial clips, metadata, source), the
  `<job_id>_*` upload, the clip's gallery review key and the collector item's
  `job_id`, so nothing of the stopped run reaches the gallery or the next scan.

The batch **stop** cancels the video that is running and marks the rest
`cancelled` without submitting them; **retry failed** can re-run those later.
Cancelling a finished job is a no-op (`"cancelled": false`).

## Settings - only what this build uses

The Settings page keeps the AI provider chain, the editable prompts and the MCP
how-to. There is no separate Gemini key card any more: a key belongs to a level
in the chain, and the chain is what every job uses. The hosted product's
sections were removed:

- **Social Integration (Upload-Post)**: clips and thumbnails are downloaded and
  uploaded by hand here. The per-clip `post` button and the Studio publish panel
  are hidden unless a key from an older install is still in local storage.
- **Video Translation (ElevenLabs)** and **AI Shorts / UGC (fal.ai)**: those
  features are not part of this fork. The `dub voice` button is hidden unless a
  legacy ElevenLabs key exists.
- The AI-agent how-to moved into **Settings** (its three steps and the MCP
  card); the old `/ai-agent` URL redirects there. The flow is keyless.

### What made native possible

Five POSIX-only behaviours (seven call sites), all sealed in
`platform_compat.py`:

| Was | Now |
|---|---|
| `preexec_fn=_lower_priority` (`app.py`, `worker.py`) | `child_priority_kwargs()` → `BELOW_NORMAL_PRIORITY_CLASS` |
| `os.nice()` | `SetPriorityClass` via ctypes |
| `import resource` (`main.py` JOB_CPU line) | `cpu_times()` (process CPU on Windows) |
| `fcntl.flock` (`gpu_render.py`, `transcribe_backends.py`, `remote_worker.py`) | `msvcrt.locking` on one byte; same non-blocking contract, released on close |
| `os.replace` / `os.remove` on a just-written clip | `replace_with_retry` / `unlink_with_retry` — Windows keeps a handle for a moment after the writer exits, so the unguarded `finally` used to fail a clip that had rendered fine (`WinError 32`) |

Other differences and how they are handled:

- **ffmpeg**: the image put a `#!/bin/sh` thread-cap wrapper first on PATH. On
  Windows the PATH `ffmpeg.exe` is used directly (BtbN gpl build: NVENC, libass,
  fontconfig, x264). The wrapper's NVENC slot cap is not needed here — four
  concurrent NVENC encodes were tested on this card and all succeeded.
- **Fonts**: `fonts\fonts.local.conf` (generated by setup) points fontconfig at
  the repo's TTF files with the same aliases the image uses, so burned captions
  match the preview. The three fonts are also installed per-user.
- **Whisper model path**: `WHISPER_MODEL` is now relative
  (`.cache/huggingface/whisper-large-v3-turbo`), so the same `.env` works in the
  container (cwd `/app`) and natively.
- **torch**: the Windows wheel is cu128, which runs on driver 566.36 — so
  TransNetV2/YOLO reach the GPU without the driver update the cu130 container
  needed. `torch.cuda.get_device_capability(0)` = `(7, 5)`, `sm_75` present.
- **PyAV**: pinned to `18.1.0` in `requirements.txt`. PyAV 19 removed the
  `metadata_errors` kwarg faster-whisper 1.2.1 passes to `av.open()`, which made
  every native transcription die with `TypeError` (the container had resolved
  18.1.0, so it never showed there).
- **Remotion**: `render-service/package.json` pins the three Remotion packages
  to `4.0.541` (matching `remotion/package-lock.json`) and adds
  `react`/`react-dom` 18.3.1, which `@remotion/renderer` needs as peers.

## Unload VRAM (Home)

The API is a long-lived process, and three in-process passes load models into
it: the subtitle re-burn, the thumbnail studio and the clip editor. In prod
those held 7.7 GB idle (`transcribe_backends.release_models` documents the
measured failure). Home → machine → **unload vram** calls
`POST /api/gpu/unload`, which:

- refuses with 409 while a job is queued/processing (the job owns its own
  process and releases its models when it exits),
- drops the ASR models, TransNetV2, the YOLO model and mediapipe's face
  detector, runs `gc.collect()`, then `torch.cuda.empty_cache()` /
  `ipc_collect()`,
- reports `beforeMb`, `afterMb`, `freedMb` and what was released. The headline
  "used" includes other apps (browser, desktop), so the message says so when
  nothing measurable changed.

Both models now reload lazily if a later in-process call needs them
(`detect_person_yolo`, `detect_face_candidates`), so unloading is safe.

## Tests

```powershell
F:\openshorts-venv\Scripts\python.exe -m pytest -q
```

`pytest` and the cloud-mode imports (`requirements-billing.txt`, needed only to
collect those tests) are installed in the venv alongside the pipeline. The
suite passes natively on Windows (2069 passed, 14 skipped); the skips are the
POSIX-only ones: the `bin/ffmpeg` flock wrapper, POSIX file modes, and the
`flock`-based multi-instance simulations.

### Measured on this machine (native, 13 Nov 2026)

| Run | Result |
|---|---|
| Local 69.5 s speech clip → transcript | completed |
| Same clip, 2-clip plan render | **23.6 s** (Docker: 45.9 s) |
| `youtu.be/_x58r9TBois` full job, 3 AI-picked clips | **274 s**, GPU 88–100 %, VRAM peak ≈ 4.3 GB of 6.1 GB |
| Same video, 3-clip plan re-render from the kept source | **64.8 s** |
| Output | 1080×1920, face-tracked crop, karaoke captions + hook, NVENC |

Not built natively: `osrender` (the Rust reframe binary). `gpu_render.usable()`
returns False when the binary is missing, so reframe uses the ffmpeg engine —
the results above are from that path. `onnxruntime` is the CPU build; that only
affects the optional Parakeet ASR backend (whisper handles the pipeline).


### Docker (not installed any more)

Docker Desktop was **uninstalled on 13 Nov 2026** after the native stack was
proven end to end. What that removed:

| | |
|---|---|
| Docker Desktop program (per-user install) | uninstalled with its own installer |
| `docker_data.vhdx` (compacted to 25.82 GB before) | deleted |
| `docker-desktop` WSL distro | unregistered |
| `%LOCALAPPDATA%\Docker`, `%APPDATA%\Docker`, `%USERPROFILE%\.docker` | deleted |
| Program Files / ProgramData folders, Start Menu shortcut, dead Machine PATH entry | deleted |
| **C: free before → after** | **42.5 GB → 71.7 GB** |

The `Ubuntu` WSL distros were left alone. `remove-docker-stack.ps1` and
`start-openshorts.ps1` stay in the repo for reference, but there is no Docker
engine to run them against; a reinstall would need a full image rebuild.


### Footprint (measured)

| | Size |
|---|---|
| Native venv (`F:\openshorts-venv`, torch cu128 + all requirements) | 5.56 GB |
| `node_modules` (dashboard + render-service + remotion) | 0.81 GB |
| Downloaded torch wheel kept for reinstalls (`F:\wheels`, optional) | 2.57 GB |
| Docker (before uninstall: VHDX after compaction / before) | 25.82 GB / 42.26 GB → **removed** |
| C: free after uninstalling Docker | **71.7 GB** |


## AI providers — the fallback chain

The moment picker no longer assumes a vendor. Settings → **AI providers** has
five slots, tried in order; if a slot fails (dead endpoint, quota, a malformed
answer) the next one is tried in the same call. Not every slot has to be filled.

| Piece | Where |
|---|---|
| Chain (keys included) | `Storage/settings.json` → `llm.levels` |
| Providers | OpenAI-compatible (`base_url` + `/chat/completions`) and native Gemini |
| OpenAI-compatible covers | OpenAI, OpenRouter, Groq, DeepSeek, Ollama, LM Studio, vLLM, llama.cpp, LocalAI |
| Test button | `POST /api/settings/llm/test` — one tiny JSON round-trip |
| Who uses it | every text stage: the two moment-picker passes, the silent-video stills fallback, layout/on-screen checks, burned-in subtitle detection, hook grounding |
| Legacy fallback | with no saved chain, `LLM_BASE_URL` / `GEMINI_API_KEY` from the environment still work |

The chain lives server-side so an MCP/agent job and the batch queue use the same
providers as a dashboard submission. `GET /api/config` exposes only booleans
(`llmConfigured`) and the level summary — never the keys.

Frame-based stages send JPEG stills through the same chain: Gemini as parts,
OpenAI-compatible providers as `image_url` data URLs. A level whose model cannot
see images fails that call and the next level gets a turn; no stage is locked to
Gemini.

OpenAI-compatible calls stream by default, so a slow provider is visible in the
job log (`🧠 AI stream: 1,240 chars in 12s`) instead of going silent for minutes.
`LLM_STREAM=0` turns that off. An empty reply now names the provider and the
reason it was empty (routed model, `finish_reason`, token split) and the retry
policy reads those fields — a 400/policy refusal fails fast, a 429/5xx/truncated
stream is retried. Note that aliases such as OpenRouter's `openrouter/free`
route every call to a random free model, so identical requests can land on a
reasoning model that spends its whole output budget thinking and returns no
content; `LLM_MAX_TOKENS` gives it more room, a fixed model is more predictable,
and `LLM_REASONING_EFFORT=low` (OpenRouter only) shrinks the thinking budget.

## AI prompts — editable, seeded with the current text

Settings → **Prompts** lists the instruction blocks with their live text, the
placeholders each one receives, and where it is used. Saving an edit stores an
override in `Storage/settings.json`; **reset to default** removes it. Saving is
refused when a required placeholder is missing, so an edit cannot break the
next job.

| Prompt id | Default constant | Used by |
|---|---|---|
| `score` | `gemini_worker.SCORE_PROMPT_TEMPLATE` | moment picker pass 1 (0-100, "2-second test") |
| `detail` | `gemini_worker.DETAIL_PROMPT_TEMPLATE` | pass 2: final cuts, hook, Facebook post, YouTube title/description, tags |
| `visual` | `gemini_worker.VISUAL_PROMPT_TEMPLATE` | silent videos (Gemini video or stills) |
| `layout` | `gemini_worker.LAYOUT_CHOICE_PROMPT` | reframe choice (none / screencast / split) |
| `screen_content` | `gemini_worker.SHOT_CONTENT_PROMPT` | screen / beside / camera per shot |
| `hook_grounding` | `gemini_worker.GROUNDED_HOOK_PROMPT` | hook/title rewritten from frames |
| `burned_subtitles` | `burned_subtitles.PROMPT` | detect subtitles already in the source |

Three layers, highest wins: a Style Profile's own prompts (`PROMPT_OVERRIDES_JSON`
for that job) → the Settings override → the module constant. Edit at runtime
through `GET/PUT /api/settings/prompts` and `POST /api/settings/prompts/reset`.

Still code-level (not in the editor): the clip editor's effect prompts
(`editor.py`), YouTube Studio's five prompts (`thumbnail.py`), the free-tool
generators (`free_tools.py`) and AI UGC (`saasshorts.py`, not exposed here).
YouTube Studio's text/image generation still calls Gemini, so it needs a Gemini
level in the chain (or `GEMINI_API_KEY`); the clip pipeline does not.
`main.GEMINI_PROMPT_TEMPLATE` is legacy and unreferenced.

Other knobs that are not prompt text:

- **Clip count and length**: `CLIP_TARGET_MIN/MAX`, `CLIP_MIN_SECONDS`,
  `CLIP_MAX_SECONDS` (or the dashboard's advanced options / the matching form
  fields) are formatted into `detail`. No 15-clip ceiling: a large target
  widens the shortlist and the detail pass runs in `LLM_DETAIL_BATCH`-sized
  calls (16 windows for Gemini, 4 for OpenAI-compatible servers).
- **Agents** get no system prompt from this app; through MCP the agent's own
  prompt decides the cuts.


## MCP - full agent control

The API already served an MCP endpoint at `/mcp` (Streamable HTTP, self-host
open, no key). It now covers the whole pipeline *without any model key*: an
agent can be the moment picker.

| Tool | What it does |
|---|---|
| `process_video` | clip a URL/upload in one call (AI picks moments — needs a key or local LLM) |
| `prepare_transcript` | download + transcribe only, **no key**, no render |
| `get_transcript` | text, language, duration and segment timings (word timings with `include_words`) |
| `render_plan` | render clips from an explicit `{start,end,title,hook}` list, reusing the prepared source (no second download or transcription) |
| `get_job_status` / `list_clips` | poll and read results |
| `add_subtitles` / `recut_clip` | restyle captions, re-cut an existing clip |
| `get_overview` / `list_gallery` | machine stats and the global library |
| `publish_clip` / `create_upload` / `get_quota` | social posting, file uploads, plan minutes |

### The keyless agent flow

```text
prepare_transcript(url)        → job_id
get_job_status(job_id)         → completed
get_transcript(job_id)         → segments with start/end
render_plan(source_job_id, [
  {start, end, title, hook, description}, …
])                             → job_id → list_clips
```

`main.py --transcribe-only` stops after the transcript (`TRANSCRIPT_READY`),
and `main.py --clip-plan` renders the supplied cuts, snapping them to word
boundaries. `render_plan` points the new job at the prepared job's source
(`source_job_id`), so a second pass costs no download and no Whisper run.
Verified end to end on a local speech clip: prepare → transcript → two planned
clips rendered with captions and hooks in 46 s.

Registered for OpenCode in `~/.config/opencode/opencode.jsonc`:

```jsonc
"openshorts": { "type": "remote", "url": "http://localhost:18480/mcp", "oauth": false }
```

### Key handling

`GEMINI_API_KEY` stays in `.env` and is optional everywhere: a plan-driven job
needs no model, and `process_video` falls back to `LLM_BASE_URL` when a local
OpenAI-compatible server is configured. `/api/process` now accepts
`clip_plan`, `transcribe_only` and `source_job_id`, and only demands a key when
the AI moment picker is actually going to run.

## Repository

This checkout is a private fork, not a clone that follows upstream:

| Remote | URL |
|---|---|
| `origin` | `https://github.com/dananjayahbi/openshorts_private_custom.git` |

`upstream` (`mutonby/openshorts`) was **removed**, and is intentionally not
tracked: `main` tracks `origin/main`. The clone had been shallow (depth 1),
which is why the first push was rejected with `did not receive expected object`;
it was deepened with a one-off
`git fetch --unshallow https://github.com/mutonby/openshorts.git` (15 MB, no
remote added), so all 663 commits of history are present. To pull upstream
changes later, fetch the URL directly and merge — do not re-add a tracking
remote unless you want the connection back.

## Run it

```powershell
.\start-openshorts.ps1          # starts Docker Desktop if needed, brings the stack up, opens the UI
.\start-openshorts.ps1 -Stop    # stops it
```

| Service | URL |
|---|---|
| **Dashboard** | http://localhost:18481 |
| API | http://localhost:18480 (`/docs`, `/health/ready`) |
| Renderer (Remotion) | http://localhost:18482 |

Ports are published in `docker-compose.override.yml` with `!override`, so they
do not collide with anything else on the machine (8000 is used by another local
project). Container ports stay 8000/5173/3100.

## Configuration (`.env`, git-ignored)

| Setting | Value | Why |
|---|---|---|
| `WHISPER_MODEL` | `/app/.cache/huggingface/whisper-large-v3-turbo` | large-v3-turbo fp16 (~1.6 GB VRAM), stored on disk so the 1.6 GB download happens once |
| `WHISPER_DEVICE` / `WHISPER_COMPUTE` | `cuda` / `float16` | GPU transcription (CTranslate2) |
| `TRANSNETV2_DEVICE` | `cuda` | GPU scene detection |
| `FFMPEG_ENCODER` | `auto` | probes `h264_nvenc`, falls back to x264 only if unusable |
| `MAX_CONCURRENT_JOBS` | `1` | one job at a time on a 6 GB card |
| `GPU_MIN_FREE_MB` | `2500` | the default 4500 would stall every job on 6 GB |
| `OPENSHORTS_STORAGE` | `Storage` | small state root: settings, profiles, gallery flags, Thumbnail Studio |
| `OPENSHORTS_MEDIA` | `D:\OpenShorts\Storage` (set by `start.bat`) | big media root: renders, sources, Collector, archive; safe to unplug |
| `JOB_RETENTION_SECONDS` | `0` | keep every finished render; 0 = never age out |
| `OUTPUT_MAX_GB` / `UPLOADS_MAX_GB` | `0` / `0` | no size cap; a positive value trims oldest-first |
| `GEMINI_API_KEY` | your free key | server-side fallback; Settings in the UI still wins |

VRAM management is the pipeline's own: `transcribe_video()` unloads whisper in a
`finally` block **before** scene detection and rendering, so whisper (1.6 GB)
and TransNetV2/YOLO are never resident together.

## Local edits (all marked with a comment)

| File | Change |
|---|---|
| `bin/ffmpeg` | converted CRLF → LF. A Windows checkout wrote `#!/bin/sh\r` and every ffmpeg call died with `exec /app/bin/ffmpeg: no such file or directory`. |
| `.gitattributes` | new: keeps `bin/*` and `*.sh` LF so that cannot regress |
| `Dockerfile` | new documented, **off by default** build arg `TORCH_CUDA_INDEX` (see "GPU driver" below) |
| `render-service/Dockerfile` | pins `remotion`/`@remotion/bundler`/`@remotion/renderer` to 4.0.541 to match `remotion/package-lock.json`. Mixing 4.0.446 with 4.0.541 crashed the renderer with `export 'Interactive' was not found in 'remotion'`. |
| `app.py` | `GET /api/gallery/clips` — a real disk-backed gallery (the S3 one was commented out), `GET /api/overview` for the home dashboard, and `geminiEnvKey` in `/api/config` |
| `dashboard/src/App.jsx` | top-bar shell, page-per-nav-item routing (`/clip-generator`, `/clip-gallery`, `/settings`…, see `src/lib/routes.js`), no source preview while processing |
| `dashboard/src/components/HomeDashboard.jsx` | new home page: stats, quick start, machine panel, recent clips |
| `dashboard/src/components/Gallery.jsx` | routes clip URLs through `getApiUrl` (media tokens) |
| `dashboard/src/contexts/AuthContext.jsx` | exposes `geminiEnvKey` |
| `dashboard/src/tokens.css`, `tailwind.config.js`, `index.css` | neutral night + ember-orange palette, squarer buttons |
| `dashboard/src/main.jsx` | no landing route: `/` and `#app` both open the app |
| `dashboard/src/lib/routes.js` | nav pages as real URLs: `/` home, `/clip-generator`, `/clip-gallery`, `/sorter`, `/content-planner`, `/shelf`, `/playground`, `/style-profiles`, `/youtube-studio`, `/settings`; old `#app?tab=…` links redirect to them and `/ai-agent` now lands on Settings |
| deleted | `Landing.jsx`, `landing.css`, `SaaShortsTab`, `UGCGallery`, `AutopilotTab`, `ProcessingAnimation` |

## What the app looks like now

Dark neutral chrome, ember-orange accent, top nav (Home · Clip Generator ·
Clip Gallery · Sorter · Content Planner · Archive · Collector · Download Manager
· Playground · Style Profiles · YouTube Studio · Settings). The landing page,
the AI Shorts tab, the UGC gallery, Autopilot, History, Pricing and the separate
AI Agent page are gone — this is a single-user local tool, not a storefront.

**No source playback while a job runs.** Pasting a URL used to embed the
YouTube player and mirror playback while downloading. The log tail and status
line are the only progress UI now.

**No rights checkbox on the generator.** This is a single-user local install
processing the user's own files, so the "I confirm I own this content…" tick
box is gone and it no longer gates **Generate Clips**. The request still sends
`acknowledged: true`, so the backend check and the cloud mode attestation are
untouched.

**Home** (`/api/overview`): clips and videos rendered on this machine, active
jobs, library disk usage, GPU panel (VRAM, utilisation, temperature) and the
last four clips. The GPU panel needs `nvidia-smi`; the container image does not
include it, so it reads `—` there — a native install fills it in.


## No social integration required

Upload-Post was only used for one-click publishing. It is now optional
everywhere: the "required keys" banner, the generate gate and the Settings badge
all ignore it. Clips are downloaded from the job result or the Clip Gallery and
uploaded by hand. The Settings field stays for when you want it back.

## Clip Gallery

`GET /api/gallery/clips?limit=&page=…` scans `Storage/videos/<job_id>/`, reads
each job's `*_metadata.json` and returns the clips that really rendered:

- newest job first, clips in metadata order (or by `sort=`)
- the file served is the **captioned** copy when the job made one (newest
  `*clip_N.mp4`), otherwise the clean cut; `wm_` twins are skipped
- title, hook, TikTok/Instagram captions, duration, score, date, five tags
- a `poster` URL for the tile (the cached JPEG still described above; `null`
  when the frame could not be extracted)
- served through `/videos/<job_id>/<file>`, the same authenticated path the job
  results use
- in cloud mode it filters by the job's `.owner` sidecar
- filters (`view`, `usage`, `platform`, `date`/`date_from`/`date_to`, `sort`,
  `q`) and paging (`limit`, `page`, legacy `offset`) all run before the page is
  cut; the response adds `total`, `page`, `pages` and `has_more`.

Clips live in `<media>/videos/<job_id>/` and are never removed automatically:
`JOB_RETENTION_SECONDS=0` and `OUTPUT_MAX_GB=0` / `UPLOADS_MAX_GB=0` in the local
`.env` mean "keep forever". A positive value re-enables the old age- or
size-based sweeps, oldest first. Archive a clip to move it into
`<media>/archive/` (also never swept). The media root is set with
`OPENSHORTS_MEDIA` (see **Storage** above) instead of moving the working
directory.

## GPU driver (resolved)

`nvidia-smi` reports driver **566.36 = CUDA 12.7**, which is why the native run
uses the **cu128** torch wheel instead of the image's cu130 one. Verified on
this machine: `torch.cuda.is_available() == True`, device capability `(7, 5)`,
whisper large-v3-turbo on CUDA, TransNetV2 and YOLO on the GPU, NVENC encoding.
No driver update is needed. (The cost is ~2.3 GB of CUDA 12.8 libraries in the
venv, which lives on F:.)

## Model weights on disk

| Model | Where | Size |
|---|---|---|
| faster-whisper large-v3-turbo | `.cache/huggingface/whisper-large-v3-turbo` | 1.54 GB |
| YOLOv8n | `yolov8n.pt` (repo root) | 6 MB |
| MediaPipe BlazeFace | inside the wheel | — |
| TransNetV2 | inside the wheel | — |

`yolov8n.pt` sits in the repo root because `.:/app` hides the copy baked into
the image. It is git-ignored (`*.pt`).
