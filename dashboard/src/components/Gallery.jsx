import React, { useState, useEffect, useRef, useCallback } from 'react';
import { AlertCircle, Loader2, Archive } from 'lucide-react';
import { getApiUrl } from '../config';
import GalleryCard from './GalleryCard';

const CLIPS_PER_PAGE = 20;

// One tab = one server-side filter, so the page counts and the infinite scroll
// agree with what is on screen (filtering after a page was cut made it lie).
const TABS = [
    { id: 'library', label: 'Library', view: 'active', usage: 'any' },
    { id: 'used', label: 'Used', view: 'active', usage: 'used' },
    { id: 'unused', label: 'Unused', view: 'active', usage: 'unused' },
    { id: 'archived', label: 'Archived', view: 'archived', usage: 'any' },
];

const bucketOf = (flags) => (flags.archived ? 'archived' : flags.used ? 'used' : 'unused');

export default function Gallery() {
    const [clips, setClips] = useState([]);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [error, setError] = useState(null);
    const [hasMore, setHasMore] = useState(true);
    const [offset, setOffset] = useState(0);
    const [tab, setTab] = useState('library');
    const [counts, setCounts] = useState({ used: 0, unused: 0, archived: 0 });
    const [archiving, setArchiving] = useState(false);

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

    // A clip that changed stay on screen only while it still matches the tab;
    // the counts move with it either way.
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
        setClips((prev) => (
            stillMatches
                ? prev.map((c) => (c.job_id === clip.job_id && c.index === clip.index ? { ...c, ...flags } : c))
                : prev.filter((c) => !(c.job_id === clip.job_id && c.index === clip.index))
        ));
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

    return (
        <div className="h-full overflow-y-auto overscroll-contain custom-scrollbar p-3 sm:p-6 animate-fade">
            <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
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
                        {clips.length} {clips.length === 1 ? 'Clip' : 'Clips'}{hasMore ? '+' : ''}
                    </span>
                </div>
            </div>

            <div className="flex gap-1 mb-5 border-b border-rule overflow-x-auto">
                {TABS.map((t) => {
                    const active = t.id === tab;
                    return (
                        <button
                            key={t.id}
                            type="button"
                            onClick={() => setTab(t.id)}
                            className={`relative pb-2.5 px-2.5 text-sm lowercase whitespace-nowrap border-b-2 -mb-px transition-colors flex items-center gap-1.5 ${active
                                ? 'text-ink border-brass'
                                : 'text-muted border-transparent hover:text-ink2'}`}
                        >
                            {t.label}
                            <span className={`readout ${active ? 'text-brass' : ''}`}>{tabCount(t.id)}</span>
                        </button>
                    );
                })}
            </div>

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
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-6 pb-10">
                        {clips.map((clip) => (
                            <GalleryCard
                                key={`${clip.job_id}-${clip.index}`}
                                clip={clip}
                                onChanged={handleChanged}
                            />
                        ))}
                    </div>

                    {/* Infinite scroll loader trigger */}
                    {hasMore && (
                        <div
                            ref={loaderRef}
                            className="flex justify-center py-8"
                        >
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
    );
}
