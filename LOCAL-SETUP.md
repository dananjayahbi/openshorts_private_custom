# Local setup — Windows 11 / i7 10th gen / GTX 1660 Ti 6 GB

Everything below is already applied in this fork. It is the map of what was
changed, why, and how to run it.

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

`GET /api/gallery/clips?limit=&offset=` scans `output/<job_id>/`, reads each
job's `*_metadata.json` and returns every clip that really rendered:

- newest job first, clips in metadata order
- the file served is the **captioned** copy when the job made one (newest
  `*clip_N.mp4`), otherwise the clean cut; `wm_` twins are skipped
- title, hook, TikTok/Instagram captions, duration, score, date
- served through `/videos/<job_id>/<file>`, the same authenticated path the job
  results use
- in cloud mode it filters by the job's `.owner` sidecar

Clips live in `output/<job_id>/` for `JOB_RETENTION_SECONDS` (30 days) and are
trimmed oldest-first once `OUTPUT_MAX_GB` is reached. A permanent library would
need its own volume — say the word and I will move the clips out of the working
directory into one.

## GPU driver (open item)

`nvidia-smi` reports driver **566.36 = CUDA 12.7**. The image's torch is
**cu130** (requires driver 580+), so today TransNetV2 and YOLO silently fall
back to the CPU:

```
CUDA initialization: The NVIDIA driver on your system is too old (found version 12070)
```

Everything else is already on the GPU (whisper, NVENC, CUDA decode). Fix:
update the driver in the NVIDIA app (`Drivers → Check for updates`) and reboot.

The alternative — `TORCH_CUDA_INDEX=cu128` as a build arg — costs ~2.3 GB of
duplicate CUDA 12.8 libraries, so it is left switched off.

## Model weights on disk

| Model | Where | Size |
|---|---|---|
| faster-whisper large-v3-turbo | `.cache/huggingface/whisper-large-v3-turbo` | 1.54 GB |
| YOLOv8n | `yolov8n.pt` (repo root) | 6 MB |
| MediaPipe BlazeFace | inside the wheel | — |
| TransNetV2 | inside the wheel | — |

`yolov8n.pt` sits in the repo root because `.:/app` hides the copy baked into
the image. It is git-ignored (`*.pt`).
