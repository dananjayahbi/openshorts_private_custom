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
| Home | Library/GPU/disk snapshot, recent clips, one-click new clip |
| Clip Generator | Upload, link, or pick from the Collector; single video or bulk queue |
| Clip Gallery | Every rendered clip; mark used, archive, restore, download |
| Collector | Shelf of links and files; download later, queue, process |
| AI Agent | MCP connection snippets (Claude, ChatGPT, Cursor, n8n) |
| YouTube Studio | Titles, descriptions and thumbnails for the clips |
| Settings | Optional Gemini key and the MCP how-to |

Everything lives under `Storage/` (videos, thumbnails, uploads, collector) and
is served by the API as a local CDN.

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
