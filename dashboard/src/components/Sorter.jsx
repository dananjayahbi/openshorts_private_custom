import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
    AlertCircle, CheckCircle2, Clock3, Eye, Loader2, Trash2, X,
} from 'lucide-react';
import { getApiUrl } from '../config';
import ClipModal from './ClipModal';
import ConfirmDeleteModal from './ConfirmDeleteModal';

// One clip at a time, the way a person reviews a day of renders: accept
// (left), reject (right), or park it in staging. Accepted clips are what the
// Clip Gallery shows by default; staged clips are the "maybe later" pile;
// rejected clips are deleted from disk. The queue is server-filtered to
// unreviewed clips, so a reload resumes exactly where the review stopped.

const BATCH = 24;
const keyOf = (clip) => `${clip.job_id}:${clip.index}`;

const readError = async (res) => {
    try {
        const body = await res.json();
        if (typeof body?.detail === 'string') return body.detail;
        if (body?.detail?.message) return body.detail.message;
    } catch (_) { /* not JSON */ }
    return `HTTP ${res.status}`;
};

const scoreTone = (score) => {
    const n = Number(score);
    if (!Number.isFinite(n)) return 'text-muted';
    if (n >= 80) return 'text-ok';
    if (n >= 60) return 'text-brass';
    return 'text-ink2';
};

const platformBadge = (label, on) => (
    <span
        key={label}
        className={`text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide ${on
            ? 'bg-brass/20 text-brass'
            : 'bg-paper3 text-muted'}`}
    >
        {label}
    </span>
);

export default function Sorter({ onOpenGallery }) {
    const [queue, setQueue] = useState([]);
    const [counts, setCounts] = useState({ accepted: 0, staged: 0, unreviewed: 0 });
    const [loading, setLoading] = useState(true);
    const [exhausted, setExhausted] = useState(false);
    const [error, setError] = useState('');
    const [actionError, setActionError] = useState('');
    const [busy, setBusy] = useState('');
    const [details, setDetails] = useState(null);
    const [pendingReject, setPendingReject] = useState(null);
    const [deleteError, setDeleteError] = useState('');
    const [deleting, setDeleting] = useState(false);

    const videoRef = useRef(null);
    const loadingRef = useRef(false);
    const queueRef = useRef([]);
    const current = queue[0] || null;

    useEffect(() => { queueRef.current = queue; }, [queue]);

    const loadQueue = useCallback(async () => {
        if (loadingRef.current) return;
        loadingRef.current = true;
        setLoading(true);
        try {
            const params = new URLSearchParams({
                status: 'unreviewed',
                view: 'active',
                limit: String(BATCH),
                page: '1',
                sort: 'oldest',
            });
            const res = await fetch(getApiUrl(`/api/gallery/clips?${params.toString()}`));
            if (!res.ok) throw new Error(await readError(res));
            const data = await res.json();
            if (data.media_offline) {
                throw new Error('The media drive is not connected. Plug it back in and retry.');
            }
            const clips = (data.clips || []).map((clip) => ({
                ...clip,
                url: getApiUrl(clip.url),
                poster: clip.poster ? getApiUrl(clip.poster) : null,
            }));
            setCounts(data.status_counts || { accepted: 0, staged: 0, unreviewed: 0 });
            const seen = new Set(queueRef.current.map(keyOf));
            const fresh = clips.filter((clip) => !seen.has(keyOf(clip)));
            if (fresh.length) setQueue((prev) => [...prev, ...fresh]);
            // Page 1 holds every remaining unreviewed clip when there are fewer
            // than one page. No fresh refs also means there is nothing left to
            // top up from, so the queue cannot ask for the same page forever.
            setExhausted(clips.length < BATCH || fresh.length === 0);
            setError('');
        } catch (e) {
            setError(String(e.message || e).slice(0, 240));
        } finally {
            setLoading(false);
            loadingRef.current = false;
        }
    }, []);

    useEffect(() => { loadQueue(); }, [loadQueue]);

    // Top up before the current clip runs out, so the review never waits.
    useEffect(() => {
        if (!loading && !exhausted && queue.length < 4) loadQueue();
    }, [queue.length, loading, exhausted, loadQueue]);

    const advance = () => {
        try { videoRef.current?.pause(); } catch (_) { /* already gone */ }
        setQueue((prev) => prev.slice(1));
    };

    const bumpCounts = (from, to) => {
        setCounts((prev) => {
            const next = { ...prev };
            if (next[from] != null) next[from] = Math.max(0, next[from] - 1);
            if (next[to] != null) next[to] += 1;
            return next;
        });
    };

    const review = async (clip, status) => {
        if (!clip || busy) return;
        setBusy(status);
        setActionError('');
        try {
            const res = await fetch(
                getApiUrl(`/api/gallery/clip/${clip.job_id}/${clip.index}`),
                {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status }),
                },
            );
            if (!res.ok) throw new Error(await readError(res));
            bumpCounts('unreviewed', status);
            advance();
        } catch (e) {
            setActionError(String(e.message || e).slice(0, 240));
        } finally {
            setBusy('');
        }
    };

    const requestReject = (clip = current) => {
        if (!clip || busy) return;
        setDeleteError('');
        setPendingReject(clip);
    };

    const confirmReject = async () => {
        const clip = pendingReject;
        if (!clip || deleting) return;
        setDeleting(true);
        setDeleteError('');
        try {
            const res = await fetch(getApiUrl('/api/gallery/delete'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    clips: [{ job_id: clip.job_id, index: clip.index }],
                }),
            });
            if (!res.ok) throw new Error(await readError(res));
            const data = await res.json();
            if (data.failed?.length) {
                throw new Error(
                    'A file is still open in another program (the player or a '
                    + 'download manager). Close it and try again.',
                );
            }
            setCounts((prev) => ({
                ...prev,
                unreviewed: Math.max(0, prev.unreviewed - 1),
            }));
            setPendingReject(null);
            if (details && keyOf(details) === keyOf(clip)) setDetails(null);
            if (current && keyOf(current) === keyOf(clip)) advance();
            else setQueue((prev) => prev.filter((item) => keyOf(item) !== keyOf(clip)));
        } catch (e) {
            setDeleteError(String(e.message || e).slice(0, 240));
        } finally {
            setDeleting(false);
        }
    };

    // Keyboard review: left/A accepts, right/R rejects, down/S stages. Space
    // keeps its normal play/pause meaning while the player has focus.
    useEffect(() => {
        if (!current || details || pendingReject) return undefined;
        const onKey = (e) => {
            const tag = String(e.target?.tagName || '').toUpperCase();
            // Leave the player's own arrow-key seek alone when it has focus.
            if (['INPUT', 'TEXTAREA', 'SELECT', 'VIDEO'].includes(tag)
                    || e.target?.isContentEditable) return;
            const key = e.key;
            if (key === 'ArrowLeft' || key.toLowerCase() === 'a') {
                e.preventDefault();
                review(current, 'accepted');
            } else if (key === 'ArrowRight' || key.toLowerCase() === 'r') {
                e.preventDefault();
                requestReject(current);
            } else if (key === 'ArrowDown' || key.toLowerCase() === 's') {
                e.preventDefault();
                review(current, 'staged');
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    });

    const handleDetailChanged = (clip, next) => {
        if (next?.archived) {
            // Archiving moved the file out of the job folder: the Sorter no
            // longer has a clip to play, so drop it from the queue.
            setDetails(null);
            setQueue((prev) => prev.filter((item) => keyOf(item) !== keyOf(clip)));
        } else if (next?.status && next.status !== 'unreviewed') {
            bumpCounts('unreviewed', next.status);
            setDetails(null);
            setQueue((prev) => prev.filter((item) => keyOf(item) !== keyOf(clip)));
        } else {
            setDetails((open) => (
                open && keyOf(open) === keyOf(clip) ? { ...open, ...next } : open));
        }
    };

    if (error && queue.length === 0) {
        return (
            <div className="h-full flex flex-col items-center justify-center text-danger p-6 text-center">
                <AlertCircle size={32} className="mb-4" />
                <p className="max-w-md">{error}</p>
                <button type="button" onClick={loadQueue} className="btn-quiet mt-4">
                    retry
                </button>
            </div>
        );
    }

    if (loading && queue.length === 0) {
        return (
            <div className="h-full flex flex-col items-center justify-center text-muted animate-fade">
                <Loader2 size={32} className="animate-spin mb-4 text-brass" />
                <p className="lowercase">Loading the review queue…</p>
            </div>
        );
    }

    return (
        <div className="h-full overflow-y-auto overscroll-contain custom-scrollbar animate-fade">
            <div className="w-full p-3 sm:p-6">
                <div className="flex flex-wrap items-end justify-between gap-3 mb-4">
                    <div>
                        <p className="eyebrow mb-1.5">03 · Review</p>
                        <h1 className="font-display lowercase text-2xl text-ink">Sorter</h1>
                        <p className="text-sm text-muted mt-1 max-w-xl">
                            Watch one clip, then accept it (left), reject it (right), or park it
                            in staging. Rejected clips are deleted from disk.
                        </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="readout px-2 py-1 rounded-input bg-paper2 text-ok">
                            accepted {counts.accepted}
                        </span>
                        <span className="readout px-2 py-1 rounded-input bg-paper2 text-brass">
                            staging {counts.staged}
                        </span>
                        <span className="readout px-2 py-1 rounded-input bg-paper2">
                            unreviewed {counts.unreviewed}
                        </span>
                        {onOpenGallery && (
                            <button type="button" onClick={onOpenGallery} className="btn-quiet text-xs py-1.5 px-2.5">
                                gallery
                            </button>
                        )}
                    </div>
                </div>

                {actionError && (
                    <div className="mb-3 rounded-card border border-danger/40 px-3 py-2 text-xs text-danger flex items-center gap-2">
                        <AlertCircle size={13} /> {actionError}
                        <button type="button" onClick={() => setActionError('')} className="ml-auto" aria-label="Dismiss">
                            <X size={13} />
                        </button>
                    </div>
                )}

                {!current ? (
                    <div className="card p-10 text-center text-muted">
                        <CheckCircle2 size={34} className="mx-auto mb-3 text-ok" />
                        <p className="text-lg lowercase text-ink mb-1">All caught up.</p>
                        <p className="text-sm mb-4">
                            Every clip has been accepted, staged or rejected.
                        </p>
                        {onOpenGallery && (
                            <button type="button" onClick={onOpenGallery} className="btn-primary text-xs py-1.5 px-3">
                                open the gallery
                            </button>
                        )}
                    </div>
                ) : (
                    <>
                        <div className={`card overflow-hidden flex flex-col lg:flex-row ${busy ? 'opacity-80' : ''}`}>
                            <div className="relative bg-black flex items-center justify-center min-h-0 flex-1 lg:max-h-[68vh]">
                                <video
                                    key={keyOf(current)}
                                    ref={videoRef}
                                    src={current.url}
                                    controls
                                    autoPlay
                                    playsInline
                                    className="max-h-[56vh] lg:max-h-[68vh] w-full h-full object-contain"
                                />
                            </div>

                            <aside className="lg:w-[380px] shrink-0 p-4 sm:p-5 space-y-4 border-t lg:border-t-0 lg:border-l border-rule">
                                <div>
                                    <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                                        <span className={`readout px-1.5 py-0.5 rounded-full bg-paper3 ${scoreTone(current.score)}`}>
                                            score {Number.isFinite(Number(current.score)) ? Math.round(Number(current.score)) : '—'}
                                        </span>
                                        <span className="readout">{Number(current.duration || 0).toFixed(1)}s</span>
                                        <span className="readout">{new Date(current.created_at).toLocaleDateString()}</span>
                                    </div>
                                    <h2 className="text-base font-medium text-ink leading-snug">{current.title}</h2>
                                </div>

                                <div className="flex flex-wrap items-center gap-1.5">
                                    {platformBadge('fb', current.platforms?.facebook)}
                                    {platformBadge('yt', current.platforms?.youtube)}
                                    {current.used && (
                                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-ok/20 text-ok lowercase">
                                            used
                                        </span>
                                    )}
                                </div>

                                {current.tags && (
                                    <p className="text-[11px] text-muted leading-relaxed line-clamp-3">
                                        {current.tags}
                                    </p>
                                )}

                                <div className="grid grid-cols-2 gap-2 pt-1">
                                    <button
                                        type="button"
                                        disabled={!!busy}
                                        onClick={() => review(current, 'accepted')}
                                        className="btn-primary flex items-center justify-center gap-1.5 text-sm py-3"
                                        title="Accept this clip (← or A)"
                                    >
                                        {busy === 'accepted'
                                            ? <Loader2 size={15} className="animate-spin" />
                                            : <CheckCircle2 size={15} />}
                                        Accept
                                    </button>
                                    <button
                                        type="button"
                                        disabled={!!busy}
                                        onClick={() => requestReject(current)}
                                        className="rounded-input border border-danger/50 bg-danger/10 text-danger flex items-center justify-center gap-1.5 text-sm py-3 hover:bg-danger/20 transition-colors disabled:opacity-50"
                                        title="Reject and delete this clip (→ or R)"
                                    >
                                        <Trash2 size={15} /> Reject
                                    </button>
                                </div>
                                <button
                                    type="button"
                                    disabled={!!busy}
                                    onClick={() => review(current, 'staged')}
                                    className="btn-quiet w-full flex items-center justify-center gap-1.5 text-xs py-2"
                                    title="Keep it in staging for later (↓ or S)"
                                >
                                    {busy === 'staged'
                                        ? <Loader2 size={13} className="animate-spin" />
                                        : <Clock3 size={13} />}
                                    Stage for later
                                </button>

                                <div className="flex items-center justify-between gap-2 pt-1">
                                    <button
                                        type="button"
                                        onClick={() => setDetails(current)}
                                        className="btn-quiet text-xs py-1.5 px-2.5"
                                    >
                                        <Eye size={13} /> details
                                    </button>
                                    <span className="readout text-[11px] hidden sm:inline">
                                        ← accept · → reject · ↓ stage
                                    </span>
                                </div>

                                {loading && (
                                    <p className="readout flex items-center gap-1.5">
                                        <Loader2 size={11} className="animate-spin" /> loading more
                                    </p>
                                )}
                            </aside>
                        </div>

                        <p className="readout text-[11px] text-muted mt-3">
                            {queue.length > 1
                                ? `${queue.length - 1} more loaded · ${counts.unreviewed} unreviewed left`
                                : `${counts.unreviewed} unreviewed left`}
                        </p>
                    </>
                )}
            </div>

            {details && (
                <ClipModal
                    clip={details}
                    onClose={() => setDetails(null)}
                    onChanged={handleDetailChanged}
                    onDelete={(clip) => { setDetails(null); requestReject(clip); }}
                />
            )}

            <ConfirmDeleteModal
                open={!!pendingReject}
                clips={pendingReject ? [pendingReject] : []}
                busy={deleting}
                error={deleteError}
                onCancel={() => { if (!deleting) { setPendingReject(null); setDeleteError(''); } }}
                onConfirm={confirmReject}
            />
        </div>
    );
}
