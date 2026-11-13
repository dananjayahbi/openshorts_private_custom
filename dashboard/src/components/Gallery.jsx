import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
    AlertCircle, Archive, CheckCircle2, Circle, Loader2, Trash2, X,
} from 'lucide-react';
import { getApiUrl } from '../config';
import GalleryCard from './GalleryCard';
import ClipModal from './ClipModal';

const CLIPS_PER_PAGE = 24;

// One tab = one server-side filter, so the page counts and the infinite scroll
// agree with what is on screen (filtering after a page was cut made it lie).
const TABS = [
    { id: 'library', label: 'Library', view: 'active', usage: 'any' },
    { id: 'used', label: 'Used', view: 'active', usage: 'used' },
    { id: 'unused', label: 'Unused', view: 'active', usage: 'unused' },
    { id: 'archived', label: 'Archived', view: 'archived', usage: 'any' },
];

const bucketOf = (flags) => (flags.archived ? 'archived' : flags.used ? 'used' : 'unused');
const keyOf = (clip) => `${clip.job_id}:${clip.index}`;

export default function Gallery() {
    const [clips, setClips] = useState([]);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [error, setError] = useState(null);
    const [actionError, setActionError] = useState('');
    const [hasMore, setHasMore] = useState(true);
    const [offset, setOffset] = useState(0);
    const [tab, setTab] = useState('library');
    const [counts, setCounts] = useState({ used: 0, unused: 0, archived: 0 });
    const [archiving, setArchiving] = useState(false);
    // Full-viewport player: cards are posters, this is the only place a clip
    // plays (and where its copy/platforms are edited).
    const [active, setActive] = useState(null);
    // Selection mode drives bulk delete.
    const [selectMode, setSelectMode] = useState(false);
    const [selected, setSelected] = useState(() => new Set());
    const [deleting, setDeleting] = useState(false);

    const loaderRef = useRef(null);
    const activeTab = TABS.find((t) => t.id === tab) || TABS[0];

    const fetchClips = useCallback(async (currentOffset = 0, append = false) => {
        try {
            if (currentOffset === 0) setLoading(true);
            else setLoadingMore(true);

            const params = new URLSearchParams({
                limit: String(CLIPS_PER_PAGE),
                offset: String(currentOffset),
                view: activeTab.view,
                usage: activeTab.usage,
            });
            const res = await fetch(getApiUrl(`/api/gallery/clips?${params.toString()}`));
            if (!res.ok) throw new Error('Failed to fetch clips');
            const data = await res.json();

            const newClips = (data.clips || []).map((c) => ({ ...c, url: getApiUrl(c.url) }));

            if (append) {
                setClips(prev => [...prev, ...newClips]);
            } else {
                setClips(newClips);
            }
            if (data.counts) setCounts(data.counts);

            setHasMore(data.has_more ?? newClips.length === CLIPS_PER_PAGE);
            setOffset(currentOffset + newClips.length);
            setError(null);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
            setLoadingMore(false);
        }
    }, [activeTab.view, activeTab.usage]);

    // Initial load, and a fresh page whenever the tab changes.
    useEffect(() => {
        setClips([]);
        setOffset(0);
        setHasMore(true);
        setSelected(new Set());
        setSelectMode(false);
        fetchClips(0, false);
    }, [fetchClips]);

    // Infinite scroll observer
    useEffect(() => {
        if (!hasMore || loadingMore || loading) return;

        const observer = new IntersectionObserver(
            (entries) => {
                if (entries[0].isIntersecting && hasMore && !loadingMore) {
                    fetchClips(offset, true);
                }
            },
            { rootMargin: '200px', threshold: 0.1 }
        );

        const node = loaderRef.current;
        if (node) {
            observer.observe(node);
        }

        return () => {
            if (node) {
                observer.unobserve(node);
            }
        };
    }, [hasMore, loadingMore, loading, offset, fetchClips]);

    // A clip that changed stays only while it still matches the tab; the counts
    // move with it either way.
    const handleChanged = (clip, flags) => {
        setCounts((prev) => {
            const next = { ...prev };
            next[bucketOf(clip)] = Math.max(0, (next[bucketOf(clip)] || 0) - 1);
            next[bucketOf(flags)] = (next[bucketOf(flags)] || 0) + 1;
            return next;
        });
        const stillMatches = (activeTab.view === 'archived'
            ? flags.archived
            : !flags.archived)
            && (activeTab.usage === 'any'
                || (activeTab.usage === 'used' ? flags.used : !flags.used));
        const merged = { ...clip, ...flags };
        setClips((prev) => {
            if (flags.archived && activeTab.view !== 'archived' && activeTab.view !== 'all') {
                return prev.filter((c) => keyOf(c) !== keyOf(clip));
            }
            return stillMatches
                ? prev.map((c) => (keyOf(c) === keyOf(clip) ? merged : c))
                : prev.filter((c) => keyOf(c) !== keyOf(clip));
        });
        setActive((current) => (current && keyOf(current) === keyOf(clip) ? merged : current));
    };

    const archiveAllUsed = async () => {
        if (!window.confirm(`Archive all ${counts.used} clip(s) marked used? The files stay on disk; they move to the Archived tab.`)) return;
        setArchiving(true);
        setError(null);
        try {
            const res = await fetch(getApiUrl('/api/gallery/archive-used'), { method: 'POST' });
            if (!res.ok) throw new Error((await res.text()).slice(0, 200) || 'Archive failed');
            await fetchClips(0, false);
        } catch (e) {
            setError(String(e.message || e).slice(0, 200));
        } finally {
            setArchiving(false);
        }
    };

    const toggleSelected = (clip) => {
        const key = keyOf(clip);
        setSelected((prev) => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    };

    const deleteClips = async (targets) => {
        if (!targets.length || deleting) return;
        const label = targets.length === 1
            ? `"${targets[0].title}"`
            : `${targets.length} clips`;
        if (!window.confirm(
            `Delete ${label}? The rendered file(s) are removed from disk and cannot be recovered.`)) return;
        setDeleting(true);
        setActionError('');
        try {
            const res = await fetch(getApiUrl('/api/gallery/delete'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    clips: targets.map((c) => ({ job_id: c.job_id, index: c.index })),
                }),
            });
            if (!res.ok) throw new Error((await res.text()).slice(0, 240) || `HTTP ${res.status}`);
            const data = await res.json();
            setSelected(new Set());
            setSelectMode(false);
            setActive((current) => (
                current && targets.some((c) => keyOf(c) === keyOf(current)) ? null : current));
            if (!data.deleted) {
                setActionError('Nothing was deleted — the files were already gone.');
            }
            await fetchClips(0, false);
        } catch (e) {
            setActionError(String(e.message || e).slice(0, 240));
        } finally {
            setDeleting(false);
        }
    };

    if (loading) {
        return (
            <div className="h-full flex flex-col items-center justify-center text-muted animate-fade">
                <Loader2 size={32} className="animate-spin mb-4 text-brass" />
                <p className="lowercase">Loading your viral history...</p>
            </div>
        );
    }

    if (error) {
        return (
            <div className="h-full flex flex-col items-center justify-center text-danger p-6">
                <AlertCircle size={32} className="mb-4" />
                <p>Error loading gallery: {error}</p>
                <button
                    onClick={() => {
                        setError(null);
                        setOffset(0);
                        fetchClips(0, false);
                    }}
                    className="btn-quiet mt-4"
                >
                    Retry
                </button>
            </div>
        );
    }

    const tabCount = (id) => {
        if (id === 'library') return counts.used + counts.unused;
        if (id === 'used') return counts.used;
        if (id === 'unused') return counts.unused;
        return counts.archived;
    };

    const selectedClips = clips.filter((c) => selected.has(keyOf(c)));
    const allSelected = clips.length > 0 && selectedClips.length === clips.length;

    return (
        <div className="h-full overflow-y-auto overscroll-contain custom-scrollbar animate-fade">
            <div className="w-full p-3 sm:p-6">
                <div className="flex flex-wrap items-end justify-between gap-3 mb-4">
                    <div>
                        <p className="eyebrow mb-1.5">Library</p>
                        <h1 className="font-display lowercase text-2xl text-ink">Clip Gallery</h1>
                    </div>
                    <div className="flex items-center gap-2">
                        {counts.used > 0 && tab !== 'archived' && (
                            <button
                                type="button"
                                onClick={archiveAllUsed}
                                disabled={archiving}
                                className="btn-quiet text-xs py-1.5 px-2.5"
                                title="Archive every clip marked used"
                            >
                                {archiving ? <Loader2 size={13} className="animate-spin" /> : <Archive size={13} />}
                                archive used ({counts.used})
                            </button>
                        )}
                        <span className="readout">
                            {clips.length}{hasMore ? '+' : ''} shown · {counts.used + counts.unused + counts.archived} total
                        </span>
                    </div>
                </div>

                <div className="flex gap-1 mb-4 border-b border-rule overflow-x-auto">
                    {TABS.map((t) => {
                        const activeButton = t.id === tab;
                        return (
                            <button
                                key={t.id}
                                type="button"
                                onClick={() => setTab(t.id)}
                                className={`relative pb-2.5 px-2.5 text-sm lowercase whitespace-nowrap border-b-2 -mb-px transition-colors flex items-center gap-1.5 ${activeButton
                                    ? 'text-ink border-brass'
                                    : 'text-muted border-transparent hover:text-ink2'}`}
                            >
                                {t.label}
                                <span className={`readout ${activeButton ? 'text-brass' : ''}`}>{tabCount(t.id)}</span>
                            </button>
                        );
                    })}
                </div>

                {/* Select / bulk delete toolbar */}
                <div className="flex flex-wrap items-center gap-2 mb-3">
                    <button
                        type="button"
                        onClick={() => {
                            setSelectMode((v) => !v);
                            setSelected(new Set());
                        }}
                        className={`btn-quiet text-xs py-1.5 px-2.5 ${selectMode ? 'text-brass' : ''}`}
                    >
                        {selectMode ? <X size={13} /> : <CheckCircle2 size={13} />}
                        {selectMode ? 'cancel selection' : 'select'}
                    </button>
                    {selectMode && (
                        <>
                            <button
                                type="button"
                                onClick={() => setSelected(allSelected
                                    ? new Set()
                                    : new Set(clips.map(keyOf)))}
                                className="btn-quiet text-xs py-1.5 px-2.5"
                            >
                                {allSelected ? <Circle size={13} /> : <CheckCircle2 size={13} />}
                                {allSelected ? 'clear all' : 'select all'}
                            </button>
                            <span className="readout">{selected.size} selected</span>
                            <button
                                type="button"
                                onClick={() => deleteClips(selectedClips)}
                                disabled={!selected.size || deleting}
                                className="btn-quiet text-xs py-1.5 px-2.5 text-danger"
                            >
                                {deleting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                                delete ({selected.size})
                            </button>
                        </>
                    )}
                    <span className="ml-auto readout hidden sm:inline">click a clip to play</span>
                </div>

                {actionError && (
                    <div className="mb-3 rounded-card border border-danger/40 px-3 py-2 text-xs text-danger flex items-center gap-2">
                        <AlertCircle size={13} /> {actionError}
                        <button type="button" onClick={() => setActionError('')} className="ml-auto" aria-label="Dismiss">
                            <X size={13} />
                        </button>
                    </div>
                )}

                {clips.length === 0 ? (
                    <div className="text-center py-20 text-muted">
                        {tab === 'archived' ? (
                            <>
                                <p className="text-lg mb-2 lowercase">Nothing archived.</p>
                                <p className="text-sm lowercase">Archive clips you are done with; the files stay on disk.</p>
                            </>
                        ) : (
                            <>
                                <p className="text-lg mb-2 lowercase">No clips found yet.</p>
                                <p className="text-sm lowercase">Process some videos to populate your gallery!</p>
                            </>
                        )}
                    </div>
                ) : (
                    <>
                        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-7 gap-2.5 sm:gap-3 pb-10">
                            {clips.map((clip) => (
                                <GalleryCard
                                    key={keyOf(clip)}
                                    clip={clip}
                                    selectMode={selectMode}
                                    selected={selected.has(keyOf(clip))}
                                    onToggleSelect={toggleSelected}
                                    onOpen={setActive}
                                    onDelete={(c) => deleteClips([c])}
                                />
                            ))}
                        </div>

                        {/* Infinite scroll loader trigger */}
                        {hasMore && (
                            <div ref={loaderRef} className="flex justify-center py-8">
                                {loadingMore && (
                                    <div className="flex items-center gap-2 text-muted">
                                        <Loader2 size={20} className="animate-spin" />
                                        <span className="text-sm lowercase">Loading more clips...</span>
                                    </div>
                                )}
                            </div>
                        )}
                    </>
                )}
            </div>

            {active && (
                <ClipModal
                    clip={active}
                    onClose={() => setActive(null)}
                    onChanged={handleChanged}
                    onDelete={(c) => deleteClips([c])}
                />
            )}
        </div>
    );
}
