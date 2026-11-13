import React, { useCallback, useEffect, useState } from 'react';
import {
  ArrowRight, Cpu, Film, HardDrive, Loader2, MemoryStick, Play, Scissors, Youtube,
} from 'lucide-react';
import { apiJson } from '../lib/api';
import { getApiUrl } from '../config';

const POLL_MS = 20000;

const greeting = () => {
  const h = new Date().getHours();
  if (h < 5) return 'still up';
  if (h < 12) return 'good morning';
  if (h < 18) return 'good afternoon';
  return 'good evening';
};

const minutes = (value) => {
  const v = Number(value) || 0;
  return v >= 60 ? `${Math.round(v / 60)}h` : `${Math.round(v)}m`;
};


/* One number, one label. The value is the loudest thing on the tile. */
function Stat({ icon: Icon, label, value, hint, tone = 'ink' }) {
  return (
    <div className="card px-4 py-3.5 flex items-start gap-3 min-w-0">
      <div className="w-8 h-8 rounded-input bg-paper3 flex items-center justify-center shrink-0">
        <Icon size={15} className={tone === 'accent' ? 'text-brass' : 'text-muted'} />
      </div>
      <div className="min-w-0">
        <p className="readout truncate">{label}</p>
        <p className="text-xl leading-tight text-ink tabular-nums truncate">{value}</p>
        {hint && <p className="text-[11px] text-muted truncate mt-0.5">{hint}</p>}
      </div>
    </div>
  );
}

/* A thin meter: GPU memory, disk. `tone` flips to warn when it is nearly full. */
function Meter({ used, total, label, right }) {
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const hot = pct >= 85;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 mb-1.5">
        <span className="readout truncate">{label}</span>
        <span className="readout tabular-nums shrink-0 text-ink2">{right}</span>
      </div>
      <div className="h-1.5 rounded-full bg-paper3 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${hot ? 'bg-danger' : 'bg-brass'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function HomeDashboard({ onStartClip, onOpenGallery, onOpenClips }) {
  const [overview, setOverview] = useState(null);
  const [clips, setClips] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const [unloading, setUnloading] = useState(false);
  const [vramMsg, setVramMsg] = useState('');

  const load = useCallback(async () => {
    const [ov, gal] = await Promise.allSettled([
      apiJson('/api/overview'),
      apiJson('/api/gallery/clips?limit=4&offset=0'),
    ]);
    if (ov.status === 'fulfilled') setOverview(ov.value);
    if (gal.status === 'fulfilled') {
      setClips((gal.value.clips || []).map((c) => ({ ...c, url: getApiUrl(c.url) })));
    }
    setLoaded(true);
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  const submit = (e) => {
    e.preventDefault();
    const value = url.trim();
    if (!value) return;
    if (!/^https?:\/\//i.test(value)) {
      setError('Paste a full link, starting with https://');
      return;
    }
    setError('');
    setUrl('');
    onStartClip(value);
  };

  const gpu = overview?.gpu;
  const storage = overview?.storage || {};
  const jobRunning = (overview?.activeJobs || 0) > 0;

  // Drop the models the long-lived API process holds (in-process subtitle,
  // thumbnail and editor passes) and report what nvidia-smi saw change. The
  // server refuses while a job is running, because that job owns its own
  // process and unloading under it would fail the render.
  const unloadVram = async () => {
    setUnloading(true);
    setVramMsg('');
    try {
      const res = await apiJson('/api/gpu/unload', { method: 'POST' });
      await load();
      const after = res.afterMb == null ? null : (res.afterMb / 1024).toFixed(1);
      if (res.freedMb > 0) {
        setVramMsg(`Freed ${res.freedMb} MB — ${after} GB still in use.`);
      } else if (res.beforeMb == null) {
        setVramMsg('Models unloaded. nvidia-smi is unavailable, so the change could not be measured.');
      } else {
        setVramMsg(`Models unloaded; nothing measurable was freed — ${after} GB is used by other processes.`);
      }
    } catch (e) {
      setVramMsg(e.detail || String(e.message || e).slice(0, 240));
    } finally {
      setUnloading(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto overscroll-contain custom-scrollbar">
      <div className="w-full p-3 sm:p-5 md:p-6 space-y-6 animate-fade">

        {/* Header */}
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="eyebrow mb-1.5">workspace</p>
            <h1 className="font-display lowercase text-2xl sm:text-3xl text-ink leading-none">
              {greeting()}
            </h1>
            <p className="text-sm text-muted mt-2">
              Drop a YouTube link, or pick up where the last clip left off.
            </p>
          </div>
          <div className="readout">
            {new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })}
          </div>
        </div>

        {/* Stat row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat
            icon={Scissors}
            label="clips"
            value={overview ? overview.clips : '—'}
            hint="rendered on this machine"
          />
          <Stat
            icon={Film}
            label="videos"
            value={overview ? overview.videos : '—'}
            hint="sources processed"
          />
          <Stat
            icon={Play}
            label="queue"
            value={overview ? (overview.activeJobs ? `${overview.activeJobs} running` : 'idle') : '—'}
            hint={overview?.activeJobs ? 'one job at a time' : 'nothing running'}
            tone={overview?.activeJobs ? 'accent' : 'ink'}
          />
          <Stat
            icon={Cpu}
            label="vram"
            value={gpu ? `${(gpu.totalMb / 1024).toFixed(0)} GB` : '—'}
            hint={gpu ? `${(gpu.usedMb / 1024).toFixed(1)} GB in use` : 'needs nvidia-smi'}
          />
        </div>

        {/* Start + system */}
        <div className="grid lg:grid-cols-[1.6fr_1fr] gap-4">
          <div className="card p-5 sm:p-6">
            <div className="flex items-center gap-2 mb-1">
              <Youtube size={16} className="text-brass" />
              <h2 className="text-sm font-medium text-ink lowercase">new clip</h2>
            </div>
            <p className="text-xs text-muted mb-4">
              Paste a YouTube URL. The pipeline downloads it, finds the best moments and renders
              vertical clips with captions.
            </p>
            <form onSubmit={submit} className="flex flex-col sm:flex-row gap-2">
              <input
                value={url}
                onChange={(e) => { setUrl(e.target.value); if (error) setError(''); }}
                placeholder="https://youtube.com/watch?v=…"
                className="input-field flex-1"
                spellCheck={false}
                autoComplete="off"
              />
              <button type="submit" className="btn-primary shrink-0">
                <Scissors size={15} />
                Generate clips
              </button>
            </form>
            {error && <p className="text-xs text-danger mt-2">{error}</p>}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-4 text-[11px] text-muted">
              <span>6 GB card · one job at a time</span>
              <span className="hidden sm:inline">·</span>
              <button onClick={onOpenClips} className="lowercase hover:text-ink2 transition-colors">
                open clip generator
              </button>
            </div>
          </div>

          <div className="card p-5 sm:p-6 space-y-5">
            <div className="flex items-center gap-2">
              <Cpu size={15} className="text-muted" />
              <h2 className="text-sm font-medium text-ink lowercase">machine</h2>
            </div>

            {gpu ? (
              <div className="space-y-1">
                <p className="text-xs text-ink2 truncate" title={gpu.name}>{gpu.name}</p>
                <Meter
                  label="vram"
                  used={gpu.usedMb}
                  total={gpu.totalMb}
                  right={`${(gpu.usedMb / 1024).toFixed(1)} / ${(gpu.totalMb / 1024).toFixed(0)} GB`}
                />
                <p className="readout pt-1">
                  {gpu.utilization}% util · {gpu.temperatureC}°c
                </p>
              </div>
            ) : (
              <p className="text-xs text-muted leading-relaxed">
                Live VRAM needs <code className="text-ink2">nvidia-smi</code>, which the container
                image does not ship. Jobs still run on the GPU — the native install reports this
                panel in full.
              </p>
            )}

            <div className="flex flex-wrap items-center justify-between gap-2 pt-2.5 border-t border-rule">
              <span className="text-[11px] text-muted lowercase">models held by the app</span>
              <button
                type="button"
                onClick={unloadVram}
                disabled={unloading || jobRunning}
                className="btn-quiet text-xs px-2.5 py-1.5"
                title={jobRunning
                  ? 'A job is running. Unload after it finishes.'
                  : 'Unload the models the API keeps in memory and free their VRAM'}
              >
                {unloading
                  ? <Loader2 size={13} className="animate-spin" />
                  : <MemoryStick size={13} />}
                unload vram
              </button>
            </div>
            {vramMsg && (
              <p className="text-[11px] leading-relaxed text-muted" role="status">{vramMsg}</p>
            )}

            {storage.totalGb ? (
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <HardDrive size={13} className="text-muted" />
                  <span className="readout">library storage</span>
                </div>
                {/* Used = the Storage folder; total = the space the disk still
                    has available, so the bar tracks how much of that room the
                    library takes (not how full the whole drive is). */}
                <Meter
                  label="storage folder"
                  used={storage.usedGb}
                  total={storage.totalGb}
                  right={`${storage.usedGb} GB of ${storage.totalGb} GB free`}
                />
                <p className="text-[11px] text-muted">
                  {storage.freeGb} GB free of {storage.capacityGb || storage.totalGb} GB on this drive
                </p>
              </div>
            ) : null}

            <div className="pt-1 border-t border-rule">
              <p className="readout mb-1.5">pipeline</p>
              <ul className="text-[11px] text-muted space-y-1">
                <li>whisper large-v3-turbo · fp16 · cuda</li>
                <li>scenes + faces · gpu</li>
                <li>encode · nvenc</li>
              </ul>
            </div>
          </div>
        </div>

        {/* Recent clips */}
        <div>
          <div className="flex items-end justify-between gap-3 mb-3">
            <div>
              <p className="eyebrow mb-1">library</p>
              <h2 className="text-base text-ink lowercase">recent clips</h2>
            </div>
            <button
              onClick={onOpenGallery}
              className="text-xs lowercase text-muted hover:text-brass transition-colors inline-flex items-center gap-1"
            >
              all clips <ArrowRight size={13} />
            </button>
          </div>

          {!loaded ? (
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="card p-2.5">
                  <div className="aspect-[4/3] rounded-input bg-paper3 mb-2.5 animate-pulse" />
                  <div className="h-3 w-4/5 rounded bg-paper3 animate-pulse" />
                  <div className="h-2.5 w-1/3 rounded bg-paper3 mt-2 animate-pulse" />
                </div>
              ))}
            </div>
          ) : clips.length === 0 ? (
            <div className="card p-8 text-center">
              <p className="text-sm text-muted">No clips yet. The first render lands here.</p>
            </div>
          ) : (
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {clips.map((clip) => (
                <button
                  key={`${clip.job_id}-${clip.index}`}
                  onClick={() => onOpenGallery(clip)}
                  className="card card-hover p-2.5 text-left group min-w-0"
                >
                  <div className="aspect-[4/3] rounded-input bg-paper3 mb-2.5 overflow-hidden relative">
                    <video
                      src={`${clip.url}#t=0.1`}
                      preload="metadata"
                      muted
                      playsInline
                      className="w-full h-full object-cover opacity-90 group-hover:opacity-100 transition-opacity"
                    />
                    <span className="readout absolute bottom-1.5 right-1.5 bg-paper/85 px-1.5 py-0.5 rounded tabular-nums">
                      {(Number(clip.duration) || 0).toFixed(1)}s
                    </span>
                    <span className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/30">
                      <Play size={20} className="text-ink drop-shadow" />
                    </span>
                  </div>
                  <p className="text-xs text-ink leading-snug line-clamp-2">{clip.title}</p>
                  <p className="readout mt-1.5">
                    {new Date(clip.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                  </p>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
