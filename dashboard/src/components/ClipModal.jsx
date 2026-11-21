import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
    Archive, ArchiveRestore, Check, CheckCircle2, Circle, Copy, Download,
    Loader2, Trash2, X,
} from 'lucide-react';
import { getApiUrl } from '../config';
import { youtubeTitle, youtubeDescription, facebookTitle } from '../lib/clipCopy';

// The full-viewport clip view: the only place a clip plays. The gallery tile
// is a poster; clicking it opens this. Editorial actions live here too, so the
// grid stays compact.

const scoreTone = (score) => {
    const n = Number(score);
    if (!Number.isFinite(n)) return 'text-muted';
    if (n >= 80) return 'text-ok';
    if (n >= 60) return 'text-brass';
    return 'text-ink2';
};

// The API puts the useful sentence in ``detail``; raw JSON would end up in
// the dialog ("{"detail":"The file is still open ..."}"), which is not a
// message a person should have to read.
const readError = async (res) => {
    try {
        const body = await res.json();
        if (typeof body?.detail === 'string') return body.detail;
        if (body?.detail?.message) return body.detail.message;
    } catch (_) { /* not JSON */ }
    return `HTTP ${res.status}`;
};

// Closing the <video> is not enough on Windows: the browser keeps the HTTP
// response (and therefore the file handle) open while it may still buffer.
// Archive is a rename, so the modal releases the player and gives the request
// a moment to finish before asking the server to move the file.
const RELEASE_PLAYER_MS = 250;

const CopyField = ({ label, value, multiline = false }) => {
    const [copied, setCopied] = useState(false);
    if (!value) return null;
    const copy = async () => {
        try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1600);
        } catch { /* clipboard denied: the text is still selectable */ }
    };
    return (
        <div className="bg-paper2 rounded-input p-2.5 relative group/item">
            <p className="eyebrow mb-1">{label}</p>
            <p className={`text-xs text-ink2 select-all ${multiline ? 'line-clamp-4' : 'line-clamp-3'}`}>
                {value}
            </p>
            <button
                type="button"
                onClick={copy}
                className="absolute top-2 right-2 p-1 text-muted hover:text-brass transition-colors"
                title={`Copy ${label}`}
            >
                {copied ? <Check size={13} className="text-ok" /> : <Copy size={13} />}
            </button>
        </div>
    );
};

export default function ClipModal({ clip, onClose, onChanged, onDelete, deleteLabel = 'delete' }) {
    const [flags, setFlags] = useState({
        used: !!clip.used,
        archived: !!clip.archived,
        status: clip.status || 'unreviewed',
        platforms: clip.platforms || { facebook: false, youtube: false },
    });
    const [busy, setBusy] = useState('');
    const [error, setError] = useState('');
    const videoRef = useRef(null);

    const releasePlayer = useCallback(async () => {
        const video = videoRef.current;
        if (video) {
            try { video.pause(); } catch (_) { /* already gone */ }
            video.removeAttribute('src');
            try { video.load(); } catch (_) { /* already gone */ }
        }
        await new Promise((resolve) => setTimeout(resolve, RELEASE_PLAYER_MS));
    }, []);

    useEffect(() => {
        const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
        window.addEventListener('keydown', onKey);
        const previous = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            window.removeEventListener('keydown', onKey);
            document.body.style.overflow = previous;
        };
    }, [onClose]);

    const patch = async (body, tag) => {
        setBusy(tag);
        setError('');
        try {
            const res = await fetch(getApiUrl(`/api/gallery/clip/${clip.job_id}/${clip.index}`), {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!res.ok) throw new Error(await readError(res));
            const next = await res.json();
            setFlags({
                used: !!next.used,
                archived: !!next.archived,
                status: next.status || 'unreviewed',
                platforms: next.platforms || { facebook: false, youtube: false },
            });
            onChanged?.(clip, next);
        } catch (e) {
            setError(String(e.message || e).slice(0, 240));
        } finally {
            setBusy('');
        }
    };

    const download = async () => {
        try {
            const response = await fetch(clip.url);
            if (!response.ok) throw new Error('download failed');
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `clip_${clip.job_id}_${clip.index + 1}.mp4`;
            document.body.appendChild(a);
            a.click();
            URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch {
            window.open(clip.url, '_blank');
        }
    };

    const toggleArchive = async () => {
        // Archiving renames the MP4 out of the job folder. Let the video
        // response close first (Issue #8: the player itself was the lock).
        if (!flags.archived) await releasePlayer();
        await patch({ archived: !flags.archived }, 'archive');
    };

    return (
        <div
            className="fixed inset-0 z-[130] bg-black/85 backdrop-blur-sm flex items-center justify-center p-0 sm:p-6 animate-fade"
            onClick={onClose}
            role="dialog"
            aria-modal="true"
            aria-label={clip.title}
        >
            <div
                className="w-full h-full sm:h-auto sm:max-h-[94vh] sm:max-w-6xl bg-paper border-0 sm:border border-rule sm:rounded-card overflow-hidden flex flex-col lg:flex-row"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Player: the whole point of the modal */}
                <div className="relative bg-black flex items-center justify-center min-h-0 flex-1 lg:max-h-[94vh]">
                    <video
                        ref={videoRef}
                        src={clip.url}
                        controls
                        autoPlay
                        playsInline
                        className="max-h-[58vh] lg:max-h-[94vh] w-full h-full object-contain"
                    />
                    <button
                        type="button"
                        onClick={onClose}
                        className="absolute top-2 right-2 w-8 h-8 rounded-full bg-black/70 text-white flex items-center justify-center hover:bg-black lg:hidden"
                        aria-label="Close"
                    >
                        <X size={16} />
                    </button>
                </div>

                <aside className="lg:w-[400px] shrink-0 overflow-y-auto overscroll-contain custom-scrollbar p-4 sm:p-5 space-y-3 max-h-[42vh] lg:max-h-[94vh]">
                    <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                                <span className={`readout px-1.5 py-0.5 rounded-full bg-paper3 ${scoreTone(clip.score)}`}>
                                    score {Number.isFinite(Number(clip.score)) ? Math.round(Number(clip.score)) : '—'}
                                </span>
                                <span className="readout">{clip.duration.toFixed(1)}s</span>
                                <span className="readout">{new Date(clip.created_at).toLocaleDateString()}</span>
                            </div>
                            <h2 className="text-sm font-medium text-ink leading-snug">{clip.title}</h2>
                        </div>
                        <button
                            type="button"
                            onClick={onClose}
                            className="hidden lg:flex w-8 h-8 rounded-full bg-paper2 text-muted hover:text-ink items-center justify-center shrink-0"
                            aria-label="Close"
                        >
                            <X size={16} />
                        </button>
                    </div>

                    <div>
                        <p className="eyebrow mb-1.5">review status</p>
                        <div className="flex gap-1.5">
                            {[
                                ['accepted', 'Accepted'],
                                ['staged', 'Staging'],
                                ['unreviewed', 'Clear'],
                            ].map(([id, label]) => {
                                const on = (flags.status || 'unreviewed') === id;
                                return (
                                    <button
                                        key={id}
                                        type="button"
                                        disabled={!!busy}
                                        onClick={() => patch({ status: id }, `status-${id}`)}
                                        className={`btn-quiet flex-1 text-xs py-1.5 px-2 ${on ? 'text-brass' : ''}`}
                                        title={id === 'unreviewed'
                                            ? 'Send this clip back to the Sorter queue'
                                            : `Mark this clip as ${label.toLowerCase()}`}
                                    >
                                        {busy === `status-${id}`
                                            ? <Loader2 size={12} className="animate-spin" />
                                            : on ? <CheckCircle2 size={12} /> : <Circle size={12} />}
                                        {label}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    <div>
                        <p className="eyebrow mb-1.5">posted on</p>
                        <div className="flex gap-1.5">
                            {[['facebook', 'Facebook'], ['youtube', 'YouTube']].map(([id, label]) => {
                                const on = !!flags.platforms?.[id];
                                return (
                                    <button
                                        key={id}
                                        type="button"
                                        disabled={!!busy}
                                        onClick={() => patch({ platform: id, posted: !on }, id)}
                                        className={`btn-quiet flex-1 text-xs py-1.5 px-2 ${on ? 'text-brass' : ''}`}
                                        title={on
                                            ? `Posted on ${label} — click to mark it unposted there`
                                            : `Mark as posted on ${label}`}
                                    >
                                        {busy === id ? <Loader2 size={12} className="animate-spin" />
                                            : on ? <CheckCircle2 size={12} /> : <Circle size={12} />}
                                        {label}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    <CopyField label="tags" value={clip.tags} />
                    <CopyField label="Facebook post" value={facebookTitle(clip)} multiline />
                    <CopyField label="YouTube title" value={youtubeTitle(clip)} />
                    <CopyField label="YouTube description" value={youtubeDescription(clip)} multiline />

                    {error && <p className="text-[11px] text-danger" role="alert">{error}</p>}

                    <div className="flex flex-wrap items-center gap-1.5 pt-1">
                        <button
                            type="button"
                            onClick={download}
                            className="btn-quiet text-xs py-1.5 px-2.5"
                        >
                            <Download size={13} /> download
                        </button>
                        <button
                            type="button"
                            disabled={!!busy}
                            onClick={toggleArchive}
                            className="btn-quiet text-xs py-1.5 px-2.5"
                        >
                            {busy === 'archive' ? <Loader2 size={13} className="animate-spin" />
                                : flags.archived ? <ArchiveRestore size={13} /> : <Archive size={13} />}
                            {flags.archived ? 'restore' : 'archive'}
                        </button>
                        <button
                            type="button"
                            onClick={() => onDelete?.(clip)}
                            disabled={!!busy}
                            className="btn-quiet text-xs py-1.5 px-2.5 ml-auto text-danger"
                        >
                            <Trash2 size={13} /> {deleteLabel}
                        </button>
                    </div>
                </aside>
            </div>
        </div>
    );
}
