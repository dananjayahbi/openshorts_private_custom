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
one page cannot drag the shell behind it.

The venv lives **outside the repo** (`F:\openshorts-venv`, override with
`OPENSHORTS_VENV`) so the repo drive keeps its free space for rendered clips.
The pip cache is `F:\pip-cache`. Both are deliberately off the E: volume.

## Storage — the local CDN

Every video, thumbnail and upload lives under one tree at the repo root
(`storage.py`), so the library can be inspected, backed up or moved as a unit:

```
Storage/
  videos/<job_id>/...        clips, sources, metadata   -> /videos/<job_id>/...
  thumbnails/<session_id>/...                           -> /thumbnails/...
  uploads/                   transient sources (not served)
```

- `OUTPUT_DIR` is `Storage/videos`, `UPLOAD_DIR` is `Storage/uploads`,
  `THUMBNAILS_DIR` is `Storage/thumbnails`. The names survive on purpose: every
  `os.path.join(OUTPUT_DIR, job_id, ...)` in the pipeline keeps working, the URL
  mounts (`/videos`, `/thumbnails`) are unchanged, and the retention sweeps
  (`OUTPUT_MAX_GB`, `UPLOADS_MAX_GB`) now measure the new tree.
- The dashboard home page reports the size of the whole `Storage/` tree and the
  free space on its volume.
- **Move it to another disk** by setting `OPENSHORTS_STORAGE` to an absolute
  path before starting (both launchers create `videos/`, `thumbnails/`,
  `uploads/`):
  ```powershell
  $env:OPENSHORTS_STORAGE = 'F:\OpenShorts-Storage'
  .\start.bat
  ```
  Set it in the same shell for `start-native.ps1`; it passes the absolute
  `Storage\videos` to the renderer automatically.
- The folder is git-ignored. The old `output/` and `uploads/` trees were
  removed when this layout landed.

## Collector — find now, process later

A new **Collector** page separates finding videos from clipping them:

- **Add a link**: only metadata and the thumbnail are fetched (tens of KB), no
  video bytes. The card shows the title, channel, duration and "link only".
- **Download**: fetches the video into `Storage/collector/files` when you are
  ready; the card switches to "on disk".
- **Upload**: a local file is stored immediately (`Storage/collector/files`)
  with a poster frame.
- **Queue**: any card can be put in the queue. "Process queue" processes them
  one at a time, in order.

In the Clip Generator, source tab **Collector** opens a full-viewport picker
over the shelf. **Bulk Mode** applies to all three sources — several uploads,
one URL per line, or a multi-select from the collector — and the batch runs
sequentially with per-item progress (the Clips land in the Clip Gallery as each
job finishes). The queue button works from either the Collector page or the
Clip Generator.

| Piece | Where |
|---|---|
| Index (not served) | `Storage/collector/items.json` |
| Videos | `Storage/collector/files/<item>_<name>.mp4` |
| Posters | `Storage/collector/thumbs/<item>.jpg`, served at `/collector/thumbs/...` |
| API | `GET/POST /api/collector`, `POST /api/collector/upload`, `POST /api/collector/{id}/download`, `POST /api/collector/{id}/queue`, `DELETE /api/collector/{id}` |
| Processing | `POST /api/process` accepts `collector_id`; a downloaded file is hardlinked into the job, so the collector keeps its copy |

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

## Tests

```powershell
F:\openshorts-venv\Scripts\python.exe -m pytest -q
```

`pytest` and the cloud-mode imports (`requirements-billing.txt`, needed only to
collect those tests) are installed in the venv alongside the pipeline. The
suite passes natively on Windows (2029 passed, 14 skipped); the skips are the
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


### Docker (fallback, keep until native is proven)

```powershell
.\start-openshorts.ps1          # starts Docker Desktop, compose up, opens the UI
.\start-openshorts.ps1 -Stop
```

`docker-compose.override.yml` publishes the same three host ports. Once native
passes a real job, `.\remove-docker-stack.ps1` drops the images and **compacts
`docker_data.vhdx`** (pruning alone does not return the space to Windows — the
virtual disk keeps its high-water mark).

**Done on 13 Nov 2026:** all images, containers, volumes and build cache were
removed and the VHDX compacted **42.26 GB → 25.82 GB** (16.4 GB returned to C:).
The remaining 25.8 GB is allocated space the compact cannot reach because the
filesystem inside still marks it as used; uninstalling Docker Desktop removes
the file entirely. Run `.\remove-docker-stack.ps1 -CompactOnly` in an elevated
shell for the compaction step alone — it is skipped when the engine is down,
because `docker compose down` would try to start the VM and hang.

### Footprint (measured)

| | Size |
|---|---|
| Native venv (`F:\openshorts-venv`, torch cu128 + all requirements) | 5.56 GB |
| `node_modules` (dashboard + render-service + remotion) | 0.81 GB |
| Downloaded torch wheel kept for reinstalls (`F:\wheels`, optional) | 2.57 GB |
| Docker's `docker_data.vhdx` after compaction | 25.82 GB |
| Docker's `docker_data.vhdx` before removal | 42.26 GB |


## MCP — full agent control

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
| `JOB_RETENTION_SECONDS` | `2592000` | 30 days, so the Clip Gallery keeps its clips |
| `OUTPUT_MAX_GB` / `UPLOADS_MAX_GB` | `10` / `8` | hard disk safety net |
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
| `dashboard/src/App.jsx` | top-bar shell, six-tab nav, no source preview while processing |
| `dashboard/src/components/HomeDashboard.jsx` | new home page: stats, quick start, machine panel, recent clips |
| `dashboard/src/components/Gallery.jsx` | routes clip URLs through `getApiUrl` (media tokens) |
| `dashboard/src/contexts/AuthContext.jsx` | exposes `geminiEnvKey` |
| `dashboard/src/tokens.css`, `tailwind.config.js`, `index.css` | neutral night + ember-orange palette, squarer buttons |
| `dashboard/src/main.jsx` | no landing route: `/` and `#app` both open the app |
| deleted | `Landing.jsx`, `landing.css`, `SaaShortsTab`, `UGCGallery`, `AutopilotTab`, `ProcessingAnimation` |

## What the app looks like now

Dark neutral chrome, ember-orange accent, top nav (Home · Clip Generator ·
Clip Gallery · AI Agent · YouTube Studio · Settings). The landing page, the
AI Shorts tab, the UGC gallery, Autopilot, History and Pricing are gone —
this is a single-user local tool, not a storefront.

**No source playback while a job runs.** Pasting a URL used to embed the
YouTube player and mirror playback while downloading. The log tail and status
line are the only progress UI now.

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

`GET /api/gallery/clips?limit=&offset=` scans `Storage/videos/<job_id>/`, reads
each job's `*_metadata.json` and returns every clip that really rendered:

- newest job first, clips in metadata order
- the file served is the **captioned** copy when the job made one (newest
  `*clip_N.mp4`), otherwise the clean cut; `wm_` twins are skipped
- title, hook, TikTok/Instagram captions, duration, score, date
- served through `/videos/<job_id>/<file>`, the same authenticated path the job
  results use
- in cloud mode it filters by the job's `.owner` sidecar

Clips live in `Storage/videos/<job_id>/` for `JOB_RETENTION_SECONDS` (30 days)
and are trimmed oldest-first once `OUTPUT_MAX_GB` is reached. To keep them on
another disk, set `OPENSHORTS_STORAGE` (see **Storage** above) instead of
moving the working directory.

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
