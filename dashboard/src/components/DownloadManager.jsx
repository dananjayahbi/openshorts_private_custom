import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
    AlertTriangle, Download, ExternalLink, Loader2, RefreshCw, Scissors, Trash2,
} from 'lucide-react';
import { apiFetch } from '../lib/api';

// The Download Manager: one full source per link, in temp storage, then cut
// into the part length each video needs and put those parts on the Collector
// shelf. The download queue and the split queue both run server-side, one item
// at a time, so closing this page does not stop them.

const ACTIVE = new Set(['queued', 'downloading', 'splitting', 'split_queued']);
const STATE_LABEL = {
    queued: 'queued',
    downloading: 'downloading',
    ready: 'ready to split',
    error: 'download failed',
    split_queued: 'queued to split',
    splitting: 'splitting',
    done: 'in the collector',
};

const fmtDuration = (seconds) => {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    if (!total) return '—';
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return h ? `${h}h ${m}m` : m ? `${m}m ${s}s` : `${s}s`;
};

const fmtBytes = (bytes) => {
    const n = Number(bytes) || 0;
    if (!n) return '—';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = n;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    return `${value >= 10 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
};

const stateTone = (state) => {
    if (state === 'error') return 'text-danger';
    if (state === 'done') return 'text-ok';
    if (state === 'downloading' || state === 'splitting') return 'text-brass';
    return 'text-muted';
};

export default function DownloadManager({ onOpenCollector }) {
    const [items, setItems] = useState([]);
    const [urlsText, setUrlsText] = useState('');
    const [adding, setAdding] = useState(false);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState({});
    // Per-item chunk length in minutes while the user types. Keep typed values
    // across polls; the server value is the fallback on first render.
    const [chunkInputs, setChunkInputs] = useState({});
    const [confirmDelete, setConfirmDelete] = useState(null);
    const [loaded, setLoaded] = useState(false);

    const load = useCallback(async () => {
        try {
            const res = await apiFetch('/api/downloads');
            if (!res.ok) return;
            const data = await res.json();
            setItems(data.items || []);
        } catch { /* keep the last list; polling retries */ }
        finally { setLoaded(true); }
    }, []);

    useEffect(() => { load(); }, [load]);

    const hasActive = items.some((item) => ACTIVE.has(item.state));
    useEffect(() => {
        if (!hasActive) return undefined;
        const timer = setInterval(load, 2500);
        return () => clearInterval(timer);
    }, [hasActive, load]);

    useEffect(() => {
        setChunkInputs((current) => {
            const next = { ...current };
            let changed = false;
            for (const item of items) {
                if (next[item.id] === undefined) {
                    next[item.id] = String(Math.round((item.chunk_seconds || 1200) / 60));
                    changed = true;
                }
            }
            return changed ? next : current;
        });
    }, [items]);

    const minutesFor = (item) => {
        const raw = chunkInputs[item.id];
        const minutes = Number(raw);
        return Number.isFinite(minutes) && minutes >= 1
            ? minutes : Math.round((item.chunk_seconds || 1200) / 60);
    };
    const secondsFor = (item) => Math.round(minutesFor(item) * 60);
    const partsFor = (item) => {
        if (!item.duration) return item.parts_expected || null;
        return Math.max(1, Math.ceil(Number(item.duration) / secondsFor(item)));
    };

    const addLinks = async (event) => {
        event.preventDefault();
        const urls = urlsText.split('\n').map((line) => line.trim()).filter(Boolean);
        if (!urls.length) return;
        setAdding(true);
        setError('');
        try {
            const res = await apiFetch('/api/downloads', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ urls }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Could not add the link(s).');
            setUrlsText('');
            await load();
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setAdding(false);
        }
    };

    const saveChunk = async (item) => {
        const seconds = secondsFor(item);
        if (!Number.isFinite(seconds) || seconds < 60 || seconds === item.chunk_seconds) return;
        try {
            await apiFetch(`/api/downloads/${item.id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ chunk_seconds: seconds }),
            });
        } catch { /* the split body carries it too */ }
    };

    const split = async (item) => {
        setBusy((b) => ({ ...b, [item.id]: 'split' }));
        setError('');
        try {
            const res = await apiFetch(`/api/downloads/${item.id}/split`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ chunk_seconds: secondsFor(item) }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Could not start the split.');
            await load();
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setBusy((b) => { const next = { ...b }; delete next[item.id]; return next; });
        }
    };

    const ready = useMemo(() => items.filter((item) => item.state === 'ready'), [items]);

    const splitAll = async () => {
        if (!ready.length) return;
        setBusy((b) => ({ ...b, all: 'split' }));
        setError('');
        try {
            const res = await apiFetch('/api/downloads/split-all', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    items: ready.map((item) => ({ id: item.id, chunk_seconds: secondsFor(item) })),
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Could not start the split queue.');
            await load();
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setBusy((b) => { const next = { ...b }; delete next.all; return next; });
        }
    };

    const remove = async (item) => {
        if (confirmDelete !== item.id) { setConfirmDelete(item.id); return; }
        setConfirmDelete(null);
        setBusy((b) => ({ ...b, [item.id]: 'delete' }));
        try {
            const res = await apiFetch(`/api/downloads/${item.id}`, { method: 'DELETE' });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Could not delete it.');
            await load();
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setBusy((b) => { const next = { ...b }; delete next[item.id]; return next; });
        }
    };

    return (
        <div className="h-full overflow-y-auto overscroll-contain custom-scrollbar animate-fade">
            <div className="w-full p-3 sm:p-6 space-y-6">
                <div className="space-y-2">
                    <p className="eyebrow flex items-center gap-2">
                        <Download size={12} /> 04 · DOWNLOAD MANAGER
                    </p>
                    <h1 className="font-display lowercase text-3xl md:text-4xl text-ink">
                        Download, cut, shelf
                    </h1>
                    <p className="text-muted text-sm md:text-base leading-relaxed max-w-2xl">
                        Fetch a full YouTube video into temporary storage, cut it into the part
                        length you want, and put those parts on the Collector shelf. Add one link
                        or several — the queue downloads them one at a time; each video keeps its
                        own part length before you start the split queue.
                    </p>
                </div>

                <form onSubmit={addLinks} className="card p-4 sm:p-5 space-y-3">
                    <label className="block">
                        <span className="eyebrow">video links</span>
                        <textarea
                            value={urlsText}
                            onChange={(e) => setUrlsText(e.target.value)}
                            rows={3}
                            placeholder={"https://www.youtube.com/watch?v=...\nOne link per line for a queue"}
                            className="input-field mt-1 text-sm resize-y"
                        />
                    </label>
                    <div className="flex flex-wrap items-center gap-3">
                        <button type="submit" disabled={adding || !urlsText.trim()} className="btn-primary px-4 py-2 text-sm">
                            {adding ? <><Loader2 size={15} className="animate-spin" /> adding…</> : <><Download size={15} /> download &amp; queue</>}
                        </button>
                        <span className="text-[11px] text-muted">
                            Files stay in Storage/downloads until you delete them; splitting copies
                            the parts into the Collector.
                        </span>
                    </div>
                </form>

                {error && (
                    <div role="alert" className="px-4 py-3 rounded-card border border-rule bg-paper2 text-sm text-danger flex items-start gap-2">
                        <AlertTriangle size={15} className="shrink-0 mt-0.5" />
                        <span className="flex-1 break-words">{error}</span>
                        <button type="button" onClick={() => setError('')} className="text-muted hover:text-ink" aria-label="dismiss">×</button>
                    </div>
                )}

                <div className="flex flex-wrap items-center gap-3">
                    <button type="button" onClick={load} className="btn-quiet px-3 py-1.5 text-xs">
                        <RefreshCw size={13} /> refresh
                    </button>
                    <button
                        type="button"
                        onClick={splitAll}
                        disabled={!ready.length || busy.all === 'split'}
                        className="btn-primary px-4 py-2 text-sm"
                    >
                        {busy.all === 'split'
                            ? <><Loader2 size={15} className="animate-spin" /> starting…</>
                            : <><Scissors size={15} /> start split queue ({ready.length})</>}
                    </button>
                    {hasActive && <span className="readout text-brass">working…</span>}
                </div>

                {!loaded ? (
                    <p className="text-sm text-muted">loading…</p>
                ) : items.length === 0 ? (
                    <div className="card p-8 text-center text-sm text-muted">
                        No downloads yet. Paste a link above to fetch the full source.
                    </div>
                ) : (
                    <div className="space-y-3">
                        {items.map((item) => {
                            const parts = partsFor(item);
                            const active = ACTIVE.has(item.state);
                            return (
                                <div key={item.id} className="card p-4 space-y-3">
                                    <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
                                        <div className="min-w-0 flex-1">
                                            <h2 className="text-sm sm:text-base text-ink font-medium break-words">
                                                {item.title || item.url}
                                            </h2>
                                            <p className="text-[11px] text-muted break-all line-clamp-2">{item.url}</p>
                                        </div>
                                        <span className={`readout shrink-0 ${stateTone(item.state)}`}>
                                            {STATE_LABEL[item.state] || item.state}
                                        </span>
                                    </div>

                                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
                                        <span>length {fmtDuration(item.duration)}</span>
                                        <span>size {fmtBytes(item.size_bytes || item.downloaded_bytes)}</span>
                                        {parts ? <span>≈ {parts} part{parts === 1 ? '' : 's'} at {minutesFor(item)} min</span> : null}
                                        {item.state === 'splitting' && item.parts_expected
                                            ? <span className="text-brass">part {Math.min(item.parts_done + 1, item.parts_expected)} of {item.parts_expected}</span>
                                            : null}
                                    </div>

                                    {item.state === 'downloading' && (
                                        <div className="space-y-1">
                                            <div className="h-1.5 rounded-full bg-paper3 overflow-hidden">
                                                <div className="h-full bg-brass transition-all" style={{ width: `${item.progress || 0}%` }} />
                                            </div>
                                            <p className="text-[11px] text-muted">
                                                {fmtBytes(item.downloaded_bytes)} of {fmtBytes(item.expected_bytes)} downloaded
                                            </p>
                                        </div>
                                    )}

                                    {item.error && (
                                        <p className="text-xs text-danger break-words">{item.error}</p>
                                    )}
                                    {item.split_error && (
                                        <p className="text-xs text-danger break-words">Split failed: {item.split_error}</p>
                                    )}

                                    {item.state === 'done' && (
                                        <p className="text-xs text-ok">
                                            {item.parts_done || item.collector_ids.length} part
                                            {(item.parts_done || item.collector_ids.length) === 1 ? '' : 's'} saved to the Collector.
                                        </p>
                                    )}

                                    <div className="flex flex-wrap items-center gap-2 pt-1">
                                        {item.state === 'ready' && (
                                            <>
                                                <label className="flex items-center gap-2 text-[11px] text-muted">
                                                    part length
                                                    <input
                                                        type="number"
                                                        min="1"
                                                        max="1440"
                                                        step="1"
                                                        value={chunkInputs[item.id] ?? ''}
                                                        onChange={(e) => setChunkInputs((current) => ({ ...current, [item.id]: e.target.value }))}
                                                        onBlur={() => saveChunk(item)}
                                                        className="input-field !w-20 text-xs py-1"
                                                        aria-label="part length in minutes"
                                                    />
                                                    min
                                                </label>
                                                <button
                                                    type="button"
                                                    onClick={() => split(item)}
                                                    disabled={busy[item.id] === 'split'}
                                                    className="btn-primary px-3 py-1.5 text-xs"
                                                >
                                                    {busy[item.id] === 'split'
                                                        ? <><Loader2 size={13} className="animate-spin" /> starting…</>
                                                        : <><Scissors size={13} /> split into parts</>}
                                                </button>
                                            </>
                                        )}
                                        {item.state === 'done' && onOpenCollector && (
                                            <button type="button" onClick={onOpenCollector} className="btn-quiet px-3 py-1.5 text-xs">
                                                <ExternalLink size={13} /> open collector
                                            </button>
                                        )}
                                        <button
                                            type="button"
                                            onClick={() => remove(item)}
                                            disabled={active || busy[item.id] === 'delete'}
                                            className={`btn-quiet px-3 py-1.5 text-xs ml-auto ${confirmDelete === item.id ? 'text-danger' : ''}`}
                                        >
                                            {busy[item.id] === 'delete'
                                                ? <><Loader2 size={13} className="animate-spin" /> deleting…</>
                                                : confirmDelete === item.id
                                                    ? <><Trash2 size={13} /> delete the temp file?</>
                                                    : <><Trash2 size={13} /> delete</>}
                                        </button>
                                        {confirmDelete === item.id && (
                                            <button
                                                type="button"
                                                onClick={() => setConfirmDelete(null)}
                                                className="btn-quiet px-3 py-1.5 text-xs"
                                            >
                                                cancel
                                            </button>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
}
