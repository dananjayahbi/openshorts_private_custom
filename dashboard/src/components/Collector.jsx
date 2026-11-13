import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
    AlertTriangle, CheckCircle2, Download, Film, HardDrive, Link2, ListPlus,
    Loader2, Play, Plus, RefreshCw, Trash2, Upload, X,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { getApiUrl } from '../config';

const fmtDuration = (seconds) => {
    const s = Number(seconds);
    if (!Number.isFinite(s) || s <= 0) return '—';
    const m = Math.floor(s / 60);
    return `${m}:${String(Math.round(s % 60)).padStart(2, '0')}`;
};

const fmtSize = (bytes) => {
    const b = Number(bytes);
    if (!Number.isFinite(b) || b <= 0) return '';
    if (b >= 1024 ** 3) return `${(b / 1024 ** 3).toFixed(2)} GB`;
    if (b >= 1024 ** 2) return `${(b / 1024 ** 2).toFixed(1)} MB`;
    return `${Math.round(b / 1024)} KB`;
};

const StateBadge = ({ item }) => {
    if (item.state === 'downloading') {
        return (
            <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-paper3 text-ink2">
                <Loader2 size={11} className="animate-spin" /> downloading
            </span>
        );
    }
    if (item.state === 'error') {
        return (
            <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-danger/10 text-danger">
                <AlertTriangle size={11} /> failed
            </span>
        );
    }
    if (item.ready) {
        return (
            <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-ok/10 text-ok">
                <CheckCircle2 size={11} /> on disk
            </span>
        );
    }
    return (
        <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-paper3 text-muted">
            <Link2 size={11} /> link only
        </span>
    );
};

export const CollectorCard = ({ item, onChanged, onProcessItem, compact = false }) => {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');

    const call = async (path, options) => {
        setBusy(true);
        setError('');
        try {
            const res = await apiFetch(path, options);
            if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
            onChanged();
        } catch (e) {
            setError(String(e.message || e).slice(0, 240));
        } finally {
            setBusy(false);
        }
    };

    const queue = (queued) => call(`/api/collector/${item.id}/queue`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ queued }),
    });

    const remove = async () => {
        if (!window.confirm(`Remove "${item.title}" from the collector?`)) return;
        await call(`/api/collector/${item.id}`, { method: 'DELETE' });
    };

    return (
        <div className={`card overflow-hidden flex flex-col ${item.queued ? 'ring-1 ring-[color:var(--color-accent)]' : ''}`}>
            <div className="relative aspect-video bg-paper3 overflow-hidden">
                {item.thumbnail ? (
                    <img
                        src={getApiUrl(item.thumbnail)}
                        alt=""
                        loading="lazy"
                        className="w-full h-full object-cover"
                    />
                ) : (
                    <div className="w-full h-full flex items-center justify-center text-muted">
                        <Film size={compact ? 22 : 30} />
                    </div>
                )}
                <div className="absolute top-2 left-2">
                    <StateBadge item={item} />
                </div>
                {item.queued && (
                    <div className="absolute top-2 right-2 text-[11px] px-2 py-0.5 rounded-full bg-[color:var(--color-accent)] text-paper font-medium">
                        queued
                    </div>
                )}
                <div className="absolute bottom-2 right-2 text-[11px] px-1.5 py-0.5 rounded bg-black/70 text-white font-mono">
                    {fmtDuration(item.duration)}
                </div>
            </div>

            <div className="p-3 sm:p-4 flex flex-col gap-2 flex-1">
                <p className="text-sm font-medium leading-snug line-clamp-2" title={item.title}>
                    {item.title}
                </p>
                <p className="text-[11px] text-muted truncate">
                    {item.channel ? `${item.channel} · ` : ''}
                    {item.ready ? fmtSize(item.size_bytes) : 'not downloaded'}
                    {item.source === 'upload' ? ' · uploaded' : ''}
                </p>
                {item.error && (
                    <p className="text-[11px] text-danger line-clamp-2" title={item.error}>{item.error}</p>
                )}
                {error && <p className="text-[11px] text-danger">{error}</p>}

                <div className="mt-auto pt-2 flex flex-wrap items-center gap-1.5">
                    {!item.ready && item.state !== 'downloading' && (
                        <button
                            type="button"
                            disabled={busy}
                            onClick={() => call(`/api/collector/${item.id}/download`, { method: 'POST' })}
                            className="btn-quiet text-xs py-1.5 px-2.5"
                            title="Download the video now and keep it in the collector"
                        >
                            {busy ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                            download
                        </button>
                    )}
                    {item.ready && (
                        <button
                            type="button"
                            disabled={busy}
                            onClick={() => onProcessItem?.(item)}
                            className="btn-quiet text-xs py-1.5 px-2.5"
                            title="Process this video now"
                        >
                            <Play size={13} /> process
                        </button>
                    )}
                    <button
                        type="button"
                        disabled={busy}
                        onClick={() => queue(!item.queued)}
                        className={`btn-quiet text-xs py-1.5 px-2.5 ${item.queued ? 'text-brass' : ''}`}
                        title={item.queued ? 'Remove from the queue' : 'Add to the processing queue'}
                    >
                        <ListPlus size={13} /> {item.queued ? 'queued' : 'queue'}
                    </button>
                    <button
                        type="button"
                        disabled={busy}
                        onClick={remove}
                        className="btn-quiet text-xs py-1.5 px-2.5 ml-auto text-muted hover:text-danger"
                        title="Remove from the collector"
                    >
                        <Trash2 size={13} />
                    </button>
                </div>
            </div>
        </div>
    );
};

export default function Collector({ onProcessItem, onProcessQueue }) {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [url, setUrl] = useState('');
    const [addingUrl, setAddingUrl] = useState(false);
    const [uploading, setUploading] = useState(null); // {done, total}
    const [error, setError] = useState('');
    const fileInput = useRef(null);
    const pollRef = useRef(null);

    const load = useCallback(async () => {
        try {
            const res = await apiFetch('/api/collector');
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();
            setItems(data.items || []);
            setError('');
        } catch (e) {
            setError(String(e.message || e).slice(0, 240));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    // While a download runs in the background, keep the cards in sync.
    useEffect(() => {
        const anyDownloading = items.some((i) => i.state === 'downloading');
        if (!anyDownloading) return undefined;
        pollRef.current = setInterval(load, 2500);
        return () => clearInterval(pollRef.current);
    }, [items, load]);

    const addUrl = async (e) => {
        e.preventDefault();
        const value = url.trim();
        if (!value) return;
        setAddingUrl(true);
        setError('');
        try {
            const res = await apiFetch('/api/collector', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: value }),
            });
            if (!res.ok) throw new Error(await res.text());
            setUrl('');
            await load();
        } catch (err) {
            setError(String(err.message || err).slice(0, 300));
        } finally {
            setAddingUrl(false);
        }
    };

    const uploadFiles = async (files) => {
        const list = Array.from(files || []);
        if (!list.length) return;
        setError('');
        for (let i = 0; i < list.length; i += 1) {
            setUploading({ done: i, total: list.length });
            const form = new FormData();
            form.append('file', list[i]);
            try {
                const res = await apiFetch('/api/collector/upload', { method: 'POST', body: form });
                if (!res.ok) throw new Error(await res.text());
            } catch (err) {
                setError(`${list[i].name}: ${String(err.message || err).slice(0, 240)}`);
            }
        }
        setUploading(null);
        if (fileInput.current) fileInput.current.value = '';
        await load();
    };

    const queued = items.filter((i) => i.queued);
    const downloading = items.some((i) => i.state === 'downloading');

    return (
        <div className="h-full overflow-y-auto custom-scrollbar">
            <div className="w-full px-3 sm:px-6 py-4 sm:py-6">
                <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
                    <div>
                        <p className="eyebrow mb-1">collector</p>
                        <h1 className="text-xl sm:text-2xl font-semibold">Your video shelf</h1>
                        <p className="text-sm text-muted mt-1 max-w-2xl">
                            Keep links and files here until you are ready. A link only costs its
                            thumbnail; download the video when you want it on disk.
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        {downloading && (
                            <span className="readout flex items-center gap-1.5">
                                <Loader2 size={12} className="animate-spin" /> downloading
                            </span>
                        )}
                        <button type="button" onClick={load} className="btn-quiet text-xs py-1.5 px-2.5" title="Refresh">
                            <RefreshCw size={13} /> refresh
                        </button>
                    </div>
                </div>

                {/* Add sources */}
                <div className="card p-3 sm:p-4 mb-5">
                    <div className="flex flex-col lg:flex-row gap-3">
                        <form onSubmit={addUrl} className="flex-1 flex gap-2">
                            <input
                                type="url"
                                value={url}
                                onChange={(e) => setUrl(e.target.value)}
                                placeholder="Paste a YouTube or video link (metadata only, no download)"
                                className="input-field"
                            />
                            <button type="submit" disabled={addingUrl || !url.trim()} className="btn-primary shrink-0">
                                {addingUrl ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}
                                <span className="hidden sm:inline">add link</span>
                            </button>
                        </form>
                        <div className="flex items-center gap-2">
                            <input
                                ref={fileInput}
                                type="file"
                                accept="video/*"
                                multiple
                                className="hidden"
                                onChange={(e) => uploadFiles(e.target.files)}
                            />
                            <button
                                type="button"
                                disabled={!!uploading}
                                onClick={() => fileInput.current?.click()}
                                className="btn-quiet text-xs py-2 px-3"
                            >
                                {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
                                {uploading ? `${uploading.done + 1}/${uploading.total}` : 'upload file'}
                            </button>
                            {queued.length > 0 && (
                                <button
                                    type="button"
                                    onClick={() => onProcessQueue?.(queued)}
                                    className="btn-primary text-xs py-2 px-3"
                                    title="Process every queued video, one at a time"
                                >
                                    <ListPlus size={14} />
                                    process queue ({queued.length})
                                </button>
                            )}
                        </div>
                    </div>
                    {error && (
                        <p className="mt-3 text-xs text-danger flex items-start gap-1.5" role="alert">
                            <AlertTriangle size={13} className="shrink-0 mt-0.5" /> {error}
                        </p>
                    )}
                </div>

                {loading ? (
                    <div className="py-16 flex justify-center text-muted">
                        <Loader2 size={22} className="animate-spin" />
                    </div>
                ) : items.length === 0 ? (
                    <div className="card p-10 text-center">
                        <HardDrive size={26} className="mx-auto text-muted mb-3" />
                        <p className="text-ink2">Nothing collected yet.</p>
                        <p className="text-sm text-muted mt-1">
                            Add a link or upload a file above. Nothing is processed until you ask.
                        </p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4 gap-3 sm:gap-4">
                        {items.map((item) => (
                            <CollectorCard
                                key={item.id}
                                item={item}
                                onChanged={load}
                                onProcessItem={onProcessItem}
                            />
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
