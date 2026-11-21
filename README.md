# Clip Studio

A private, single-user local build: paste a YouTube link (or pick a file), and
the pipeline transcribes it, picks the moments, reframes them vertical and
burns captions in. Clips are downloaded and uploaded by hand; nothing is
published anywhere automatically.

Built from the OpenShorts codebase (MIT, see `LICENSE` / `NOTICE`) and stripped
of the hosted product: no accounts, no billing, no marketing pages, no GitHub
promos, no watermark. It runs natively on Windows with an NVIDIA GPU — no
Docker.

## What is in it

| Page | What it does |
|---|---|
| Home | Library/GPU/disk snapshot, recent clips, one-click new clip, **unload vram** |
| Clip Generator | Upload, link, or pick from the Collector; style profile + captions before the render; a bulk queue that loops the same screen and retries failures once; **streamed video** split with its own marked box + prevention area per queued video; no clip-count cap (hours-long sources can yield 100s); stop a run and remove its partial files |
| Clip Gallery | Compact score tiles with a full-viewport player, five tags, per-platform marks, single/bulk delete, bulk-archive the selection, staged one-platform archive buttons |
| Archive | Permanent clip store with advanced filters; push videos to external storage vaults and play them back when the device is connected |
| Collector | Shelf of links and files; download later, queue, process |
| Download Manager | Fetch full links into temp storage; cut each into its own part length and save the parts to the Collector |
| Playground | Try caption looks and output shapes on a real clip, save the result as a profile |
| Style Profiles | Saved caption/format bundles; apply one in the Clip Generator |
| AI Agent | MCP connection snippets (Claude, ChatGPT, Cursor, n8n) |
| YouTube Studio | Titles, descriptions and thumbnails for the clips |
| Settings | Five-level AI provider chain (any OpenAI-compatible endpoint or Gemini), editable prompts, MCP how-to |

Every page has its own URL, so it can be bookmarked, shared and reloaded:
`/` (Home), `/clip-generator`, `/clip-gallery`, `/archive`, `/shelf` (Collector),
`/download-manager`, `/playground`, `/style-profiles`, `/ai-agent`,
`/youtube-studio`, `/settings`.
Old `#app?tab=…` links are redirected to the matching page.

Every clip's copy is shaped for Facebook and YouTube: a Facebook post (title,
two blank lines, five hashtags), a clean YouTube title with no hashtags, a
250-500 character YouTube description, and five comma-separated tags for
YouTube's tag field.

Small state (settings, style profiles, gallery flags, Thumbnail Studio) stays
under `Storage/`; the big media tree (videos, uploads, collector, downloads,
archive) can live on another disk via `OPENSHORTS_MEDIA` — `start.bat` points it
at `D:\OpenShorts\Storage`. Both are served by the API as a local CDN.
`Storage/settings.json` holds the provider chain and prompt overrides;
`Storage/style_profiles.json` the saved looks. Archived clips and their SQLite
index live under `<media>/archive/`; external vaults are single preallocated
`.osvault` files on the device you pick. Unplugging the media drive is safe: the
dashboard says so, and replugging it restores everything without a restart.

## Run it

```powershell
.\start.bat            # API :18480, dashboard :18481, renderer :18482
.\stop.bat             # stop the three ports
```

`start-native.ps1` is the hidden/log flavour; `setup-native.ps1` is the
one-time install (Python venv at `F:\openshorts-venv`, Node deps, fonts).

See `LOCAL-SETUP.md` for the full map: ports, storage layout, GPU settings,
MCP, tests and the post-Docker footprint.

## Requirements

- Windows 10/11, NVIDIA GPU with a recent driver (`nvidia-smi`)
- Python 3.12 venv with `requirements.txt` (torch cu128)
- Node.js 20+ for the dashboard and the Remotion renderer
- `ffmpeg.exe` on `PATH` with NVENC, libass and fontconfig
- About 6 GB of VRAM; one job at a time

## Tests

```powershell
F:\openshorts-venv\Scripts\python.exe -m pytest -q
```
