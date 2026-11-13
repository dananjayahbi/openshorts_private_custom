import React, { useEffect, useState } from 'react';
import {
    AlertTriangle, Check, Film, Link2, Loader2, RefreshCw, X,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { getApiUrl } from '../config';

const fmtDuration = (seconds) => {
    const s = Number(seconds);
    if (!Number.isFinite(s) || s <= 0) return '—';
    return `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
};

export default function CollectorPicker({ open, multi = false, onClose, onConfirm }) {
    const [items, setItems] = useState([]);
    const [selected, setSelected] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const load = async () => {
        setLoading(true);
        setError('');
        try {
            const res = await apiFetch('/api/collector');
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();
            setItems(data.items || []);
        } catch (e) {
            setError(String(e.message || e).slice(0, 300));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (!open) return;
        setSelected([]);
        load();
        const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open]);

    if (!open) return null;

    const toggle = (id) => {
        setSelected((prev) => {
            if (prev.includes(id)) return prev.filter((x) => x !== id);
            return multi ? [...prev, id] : [id];
        });
    };

    const confirm = () => {
        const picked = items.filter((i) => selected.includes(i.id));
        if (picked.length) onConfirm?.(picked);
    };

    return (
        <div className="fixed inset-0 z-[120] flex flex-col bg-paper text-ink" role="dialog" aria-modal="true">
            <header className="shrink-0 border-b border-rule bg-paper2 px-3 sm:px-6 py-3 flex items-center gap-3">
                <div className="min-w-0">
                    <p className="eyebrow">collector</p>
                    <h2 className="text-base sm:text-lg font-semibold truncate">
                        {multi ? 'Pick videos to process' : 'Pick a video'}
                    </h2>
                </div>
                <div className="ml-auto flex items-center gap-2">
                    <button type="button" onClick={load} className="btn-quiet text-xs py-1.5 px-2.5" title="Refresh">
                        <RefreshCw size={13} /> <span className="hidden sm:inline">refresh</span>
                    </button>
                    <button type="button" onClick={onClose} className="btn-quiet text-xs py-1.5 px-2.5" title="Close">
                        <X size={15} />
                    </button>
                </div>
            </header>

            <div className="flex-1 overflow-y-auto custom-scrollbar px-3 sm:px-6 py-4">
                {error && (
                    <p className="mb-4 text-xs text-danger flex items-start gap-1.5">
                        <AlertTriangle size={13} className="shrink-0 mt-0.5" /> {error}
                    </p>
                )}
                {loading ? (
                    <div className="py-20 flex justify-center text-muted"><Loader2 size={24} className="animate-spin" /></div>
                ) : items.length === 0 ? (
                    <div className="py-20 text-center text-muted">
                        <Film size={26} className="mx-auto mb-3" />
                        <p className="text-ink2">The collector is empty.</p>
                        <p className="text-sm mt-1">Add links or files on the Collector page first.</p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-3 sm:gap-4">
                        {items.map((item) => {
                            const active = selected.includes(item.id);
                            return (
                                <button
                                    type="button"
                                    key={item.id}
                                    onClick={() => toggle(item.id)}
                                    className={`card overflow-hidden text-left transition-colors ${active
                                        ? 'ring-2 ring-[color:var(--color-accent)]'
                                        : 'hover:border-[color:var(--color-accent)]'}`}
                                >
                                    <div className="relative aspect-video bg-paper3">
                                        {item.thumbnail ? (
                                            <img src={getApiUrl(item.thumbnail)} alt="" loading="lazy"
                                                 className="w-full h-full object-cover" />
                                        ) : (
                                            <div className="w-full h-full flex items-center justify-center text-muted">
                                                <Film size={26} />
                                            </div>
                                        )}
                                        {active && (
                                            <span className="absolute top-2 right-2 w-6 h-6 rounded-full bg-[color:var(--color-accent)] text-paper flex items-center justify-center">
                                                <Check size={14} />
                                            </span>
                                        )}
                                        <span className="absolute bottom-2 right-2 text-[11px] px-1.5 py-0.5 rounded bg-black/70 text-white font-mono">
                                            {fmtDuration(item.duration)}
                                        </span>
                                        {!item.ready && (
                                            <span className="absolute top-2 left-2 text-[10px] px-1.5 py-0.5 rounded bg-black/70 text-white flex items-center gap-1">
                                                <Link2 size={10} /> link
                                            </span>
                                        )}
                                    </div>
                                    <div className="p-3">
                                        <p className="text-sm leading-snug line-clamp-2">{item.title}</p>
                                        <p className="text-[11px] text-muted mt-1 truncate">
                                            {item.channel || (item.ready ? 'on disk' : 'not downloaded')}
                                            {item.queued ? ' · queued' : ''}
                                        </p>
                                    </div>
                                </button>
                            );
                        })}
                    </div>
                )}
            </div>

            <footer className="shrink-0 border-t border-rule bg-paper2 px-3 sm:px-6 py-3 flex items-center gap-3">
                <p className="text-xs text-muted">
                    {selected.length ? `${selected.length} selected` : 'Nothing selected'}
                </p>
                <div className="ml-auto flex items-center gap-2">
                    <button type="button" onClick={onClose} className="btn-quiet text-xs py-2 px-3">cancel</button>
                    <button
                        type="button"
                        disabled={!selected.length}
                        onClick={confirm}
                        className="btn-primary text-xs py-2 px-3"
                    >
                        use selection{selected.length ? ` (${selected.length})` : ''}
                    </button>
                </div>
            </footer>
        </div>
    );
}
