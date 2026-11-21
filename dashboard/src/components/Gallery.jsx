import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
    AlertCircle, Archive, CheckCircle2, ChevronLeft, ChevronRight, Circle,
    Loader2, Trash2, X,
} from 'lucide-react';
import { getApiUrl } from '../config';
import GalleryCard from './GalleryCard';
import ClipModal from './ClipModal';
import ConfirmDeleteModal from './ConfirmDeleteModal';
import SegmentedControl from './ui/SegmentedControl';

// Server-side paging: the page number goes to the API and the answer already
// is the page, so a library with thousands of clips costs one small query.
const PAGE_SIZES = [24, 48, 96];
const DEFAULT_PAGE_SIZE = 24;

const EMPTY_FILTERS = {
    date: 'any',
    from: '',
    to: '',
    platform: 'any',
    // The Sorter's decision. The gallery opens on publishable clips; "all" is
    // there for cleaning up, "staged" for the maybe-later pile.
    status: 'accepted',
    sort: 'newest',
    q: '',
};

const DATE_OPTIONS = [
    { value: 'any', label: 'any time' },
    { value: 'today', label: 'today' },
    { value: 'yesterday', label: 'yesterday' },
    { value: 'week', label: 'this week' },
    { value: 'month', label: 'this month' },
    { value: 'custom', label: 'custom range' },
];

const PLATFORM_OPTIONS = [
    { value: 'any', label: 'any' },
    { value: 'youtube', label: 'youtube' },
    { value: 'facebook', label: 'facebook' },
    { value: 'both', label: 'both' },
    { value: 'none', label: 'not posted' },
];

const STATUS_OPTIONS = [
    { value: 'accepted', label: 'accepted' },
    { value: 'staged', label: 'staging' },
    { value: 'unreviewed', label: 'unreviewed' },
    { value: 'all', label: 'all' },
];

const SORT_OPTIONS = [
    { value: 'newest', label: 'newest first' },
    { value: 'oldest', label: 'oldest first' },
    { value: 'longest', label: 'longest first' },
    { value: 'shortest', label: 'shortest first' },
    { value: 'score', label: 'best score' },
];

// One tab = one server-side filter, so the counts and the pager agree with what
// is on screen (filtering after a page was cut made the numbers lie).
const TABS = [
    { id: 'library', label: 'Library', view: 'active', usage: 'any' },
    { id: 'used', label: 'Used', view: 'active', usage: 'used' },
    { id: 'unused', label: 'Unused', view: 'active', usage: 'unused' },
];

const keyOf = (clip) => `${clip.job_id}:${clip.index}`;

const todayInput = () => {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

// The API's error detail is what the user needs ("still open in another
// program"), not a raw JSON body.
const readError = async (res) => {
    try {
        const body = await res.json();
        if (typeof body?.detail === 'string') return body.detail;
        if (body?.detail?.message) return body.detail.message;
    } catch (_) { /* not JSON */ }
    return `HTTP ${res.status}`;
};

// Windowed page numbers: 1 … 4 5 6 … 12.
const pageList = (page, pages) => {
    if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
    const wanted = [...new Set([1, pages, page - 1, page, page + 1])]
        .filter((n) => n >= 1 && n <= pages)
        .sort((a, b) => a - b);
    const out = [];
    let previous = 0;
    for (const n of wanted) {
        if (previous && n - previous > 1) out.push('…');
        out.push(n);
        previous = n;
    }
    return out;
};

export default function Gallery({ onOpenArchive, onOpenSorter }) {
    const [clips, setClips] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [actionError, setActionError] = useState('');
    const [tab, setTab] = useState('library');
    const [counts, setCounts] = useState({ used: 0, unused: 0, archived: 0 });
    // How many clips sit in each Sorter state, ignoring the status filter, so
    // the filter row can show the backlog at a glance.
    const [statusCounts, setStatusCounts] = useState({
        accepted: 0, staged: 0, unreviewed: 0,
    });
    const [page, setPage] = useState(1);
    const [pages, setPages] = useState(0);
    const [total, setTotal] = useState(0);
    const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
    const [filters, setFilters] = useState(EMPTY_FILTERS);
    const [search, setSearch] = useState('');
    const [archiving, setArchiving] = useState(false);
    // Staged archiving: clips posted on only one platform wait here until the
    // user runs the matching button. Both-platform clips go automatically.
    const [staged, setStaged] = useState({
        enabled: false, days: 0, facebook: [], youtube: [],
    });
    // Full-viewport player: cards are posters, this is the only place a clip
    // plays (and where its copy/platforms are edited).
    const [active, setActive] = useState(null);
    // Selection mode drives bulk delete.
    const [selectMode, setSelectMode] = useState(false);
    const [selected, setSelected] = useState(() => new Set());
    const [deleting, setDeleting] = useState(false);
    // Delete is confirmed in-app (ConfirmDeleteModal), not by window.confirm:
    // the pending list is what that dialog describes and then deletes.
    const [pendingDelete, setPendingDelete] = useState([]);
    const [deleteError, setDeleteError] = useState('');

    const scrollRef = useRef(null);
    const activeTab = TABS.find((t) => t.id === tab) || TABS[0];
    const filtersActive = filters.date !== 'any' || filters.platform !== 'any'
        || filters.status !== 'accepted' || !!filters.q;

    const fetchStaged = useCallback(async () => {
        try {
            const res = await fetch(getApiUrl('/api/gallery/archive-staged'));
            if (!res.ok) return;
            const data = await res.json();
            setStaged({
                enabled: !!data.enabled,
                days: Number(data.days) || 0,
                facebook: data.facebook || [],
                youtube: data.youtube || [],
            });
        } catch (_) {
            // The staging buttons are an extra: a failed refresh hides them
            // rather than blocking the gallery.
        }
    }, []);

    const fetchClips = useCallback(async (targetPage = 1) => {
        // A half-filled custom range is still being edited; keep the last
        // result instead of asking the API for an impossible window.
        if (filters.date === 'custom' && (!filters.from || !filters.to)) {
            setLoading(false);
            return;
        }
        setLoading(true);
        try {
            const params = new URLSearchParams({
                limit: String(pageSize),
                page: String(Math.max(1, targetPage)),
                view: activeTab.view,
                usage: activeTab.usage,
                platform: filters.platform,
                status: filters.status,
                sort: filters.sort,
            });
            if (filters.date !== 'any') params.set('date', filters.date);
            if (filters.date === 'custom') {
                params.set('date_from', filters.from);
                params.set('date_to', filters.to);
            }
            if (filters.q) params.set('q', filters.q);

            const res = await fetch(getApiUrl(`/api/gallery/clips?${params.toString()}`));
            if (!res.ok) throw new Error(await readError(res));
            const data = await res.json();

            setClips((data.clips || []).map((c) => ({
                ...c,
                url: getApiUrl(c.url),
                poster: c.poster ? getApiUrl(c.poster) : null,
            })));
            if (data.counts) setCounts(data.counts);
            if (data.status_counts) setStatusCounts(data.status_counts);
            setPage(data.page || 1);
            setPages(data.pages || 0);
            setTotal(data.total || 0);
            setError(null);
            fetchStaged();
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [activeTab.view, activeTab.usage, filters, pageSize, fetchStaged]);

    // Initial load, and a fresh first page whenever a tab/filter/page size
    // changes: staying on page 7 of a narrower result set would be confusing.
    useEffect(() => {
        setSelected(new Set());
        setSelectMode(false);
        fetchClips(1);
    }, [fetchClips]);

    // Typing is debounced so a search does not fire one query per keystroke.
    useEffect(() => {
        const id = setTimeout(() => {
            setFilters((prev) => (prev.q === search ? prev : { ...prev, q: search.trim() }));
        }, 350);
        return () => clearTimeout(id);
    }, [search]);

    const goToPage = (next) => {
        if (loading || next === page || next < 1 || (pages && next > pages)) return;
        setSelected(new Set());
        fetchClips(next);
        scrollRef.current?.scrollTo({ top: 0 });
    };

    const updateFilter = (patch) => {
        setFilters((prev) => ({ ...prev, ...patch }));
    };

    const resetFilters = () => {
        setSearch('');
        setFilters(EMPTY_FILTERS);
    };

    // A clip that changed is re-read from the server: with platform/date/search
    // filters, local guessing about whether it still matches would lie.
    const handleChanged = (clip, flags) => {
        const merged = { ...clip, ...flags };
        setActive((current) => (current && keyOf(current) === keyOf(clip) ? merged : current));
        // Archiving moved the file into the Archive page: the player has
        // nothing left to play, so close it instead of leaving a broken <video>.
        if (flags?.archived) setActive(null);
        // Changing the review status can move a clip out of the current filter
        // (accepted -> staged, for example); close the player rather than
        // leaving it on a clip the grid no longer lists.
        if (filters.status !== 'all' && flags?.status
                && flags.status !== filters.status) {
            setActive(null);
        }
        fetchClips(page);
    };

    const archiveAllUsed = async () => {
        if (!window.confirm(`Archive all ${counts.used} clip(s) marked used? They move out of the gallery into the Archive page (and can be pushed to a vault from there).`)) return;
        setArchiving(true);
        setActionError('');
        try {
            const res = await fetch(getApiUrl('/api/gallery/archive-used'), { method: 'POST' });
            if (!res.ok) throw new Error(await readError(res));
            await fetchClips(1);
        } catch (e) {
            setActionError(String(e.message || e).slice(0, 200));
        } finally {
            setArchiving(false);
        }
    };

    const archiveSelected = async () => {
        const targets = clips.filter((c) => selected.has(keyOf(c)));
        if (!targets.length || archiving) return;
        setArchiving(true);
        setActionError('');
        try {
            const res = await fetch(getApiUrl('/api/archive/clips'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    clips: targets.map((c) => ({ job_id: c.job_id, index: c.index })),
                }),
            });
            if (!res.ok) throw new Error(await readError(res));
            const data = await res.json();
            const failed = data.failed || [];
            if (failed.length) {
                setActionError(
                    `${failed.length} clip(s) could not be archived — `
                    + (failed[0].error || 'another program has the file open.'));
            }
            setSelected(new Set());
            setSelectMode(false);
            // Archiving moves the file out of /videos; a player still on it
            // would only show a broken frame.
            setActive((current) => (
                current && targets.some((t) => keyOf(t) === keyOf(current)) ? null : current));
            await fetchClips(page);
        } catch (e) {
            setActionError(String(e.message || e).slice(0, 240));
        } finally {
            setArchiving(false);
        }
    };

    const archiveStagedGroup = async (platform) => {
        const refs = staged[platform] || [];
        if (!refs.length || archiving) return;
        const label = platform === 'youtube' ? 'YouTube' : 'Facebook';
        if (!window.confirm(
            `Archive ${refs.length} clip(s) posted only on ${label}? `
            + 'They move to the Archive page.',
        )) return;
        setArchiving(true);
        setActionError('');
        try {
            const res = await fetch(getApiUrl('/api/gallery/archive-staged'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ platform }),
            });
            if (!res.ok) throw new Error(await readError(res));
            const data = await res.json();
            const failed = data.failed || [];
            if (failed.length) {
                setActionError(
                    `${failed.length} clip(s) could not be archived — `
                    + (failed[0].error || 'another program has the file open.'));
            }
            await fetchClips(page);
        } catch (e) {
            setActionError(String(e.message || e).slice(0, 240));
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

    const requestDelete = (targets) => {
        if (!targets?.length || deleting) return;
        setActionError('');
        setDeleteError('');
        setPendingDelete(targets);
    };

    const cancelDelete = () => {
        if (deleting) return;
        setPendingDelete([]);
        setDeleteError('');
    };

    const deleteClips = async (targets) => {
        if (!targets.length || deleting) return;
        setDeleting(true);
        setDeleteError('');
        setActionError('');
        try {
            const res = await fetch(getApiUrl('/api/gallery/delete'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    clips: targets.map((c) => ({ job_id: c.job_id, index: c.index })),
                }),
            });
            if (!res.ok) throw new Error(await readError(res));
            const data = await res.json();
            const failed = data.failed || [];
            const failedKeys = new Set(failed.map((f) => `${f.job_id}:${f.index}`));
            if (failed.length) {
                // Some files are still open in a player/download manager: keep
                // just those in the dialog so the message names what stayed.
                setPendingDelete(targets.filter((t) => failedKeys.has(keyOf(t))));
                setDeleteError(
                    `${failed.length} clip(s) could not be deleted because a file is still `
                    + "open in another program (the clip player or a download manager). "
                    + "Close it and try again.",
                );
            } else {
                setPendingDelete([]);
                setSelected(new Set());
                setSelectMode(false);
            }
            setActive((current) => (
                current && targets.some((t) => keyOf(t) === keyOf(current)
                    && !failedKeys.has(keyOf(t))) ? null : current));
            if (!data.deleted && !failed.length) {
                setActionError('Nothing was deleted — the files were already gone.');
            }
            await fetchClips(page);
        } catch (e) {
            // Keep the dialog open so the message is next to the action that
            // failed. 409 means a file is locked; say so in plain words.
            setDeleteError(String(e.message || e).slice(0, 240));
        } finally {
            setDeleting(false);
        }
    };

    if (error) {
        return (
            <div className="h-full flex flex-col items-center justify-center text-danger p-6">
                <AlertCircle size={32} className="mb-4" />
                <p>Error loading gallery: {error}</p>
                <div className="flex items-center gap-2 mt-4">
                    <button
                        onClick={() => {
                            setError(null);
                            fetchClips(page);
                        }}
                        className="btn-quiet"
                    >
                        retry
                    </button>
                    <button
                        onClick={() => {
                            setError(null);
                            resetFilters();
                        }}
                        className="btn-quiet"
                    >
                        reset filters
                    </button>
                </div>
            </div>
        );
    }

    if (loading && clips.length === 0) {
        return (
            <div className="h-full flex flex-col items-center justify-center text-muted animate-fade">
                <Loader2 size={32} className="animate-spin mb-4 text-brass" />
                <p className="lowercase">Loading your viral history...</p>
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
    const firstShown = total === 0 ? 0 : (page - 1) * pageSize + 1;
    const lastShown = (page - 1) * pageSize + clips.length;

    return (
        <div ref={scrollRef} className="h-full overflow-y-auto overscroll-contain custom-scrollbar animate-fade">
            <div className="w-full p-3 sm:p-6">
                <div className="flex flex-wrap items-end justify-between gap-3 mb-4">
                    <div>
                        <p className="eyebrow mb-1.5">Library</p>
                        <h1 className="font-display lowercase text-2xl text-ink">Clip Gallery</h1>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                        {staged.youtube.length > 0 && (
                            <button
                                type="button"
                                onClick={() => archiveStagedGroup('youtube')}
                                disabled={archiving}
                                className="btn-quiet text-xs py-1.5 px-2.5 text-brass"
                                title={`Posted only on YouTube — staged for your permission; clips posted on both auto-archive after ${staged.days} day(s)`}
                            >
                                {archiving ? <Loader2 size={13} className="animate-spin" /> : <Archive size={13} />}
                                archive yt-only ({staged.youtube.length})
                            </button>
                        )}
                        {staged.facebook.length > 0 && (
                            <button
                                type="button"
                                onClick={() => archiveStagedGroup('facebook')}
                                disabled={archiving}
                                className="btn-quiet text-xs py-1.5 px-2.5 text-brass"
                                title={`Posted only on Facebook — staged for your permission; clips posted on both auto-archive after ${staged.days} day(s)`}
                            >
                                {archiving ? <Loader2 size={13} className="animate-spin" /> : <Archive size={13} />}
                                archive fb-only ({staged.facebook.length})
                            </button>
                        )}
                        {counts.used > 0 && !filtersActive && (
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
                        {onOpenSorter && statusCounts.unreviewed > 0 && (
                            <button
                                type="button"
                                onClick={onOpenSorter}
                                className="btn-quiet text-xs py-1.5 px-2.5 text-brass"
                                title="Review the clips that have not been accepted or staged yet"
                            >
                                <CheckCircle2 size={13} /> sorter
                                <span className="readout ml-1">{statusCounts.unreviewed}</span>
                            </button>
                        )}
                        {onOpenArchive && (
                            <button
                                type="button"
                                onClick={onOpenArchive}
                                className="btn-quiet text-xs py-1.5 px-2.5"
                                title="Open the Archive page"
                            >
                                <Archive size={13} /> archive page
                                {counts.archived > 0 && (
                                    <span className="readout ml-1">{counts.archived}</span>
                                )}
                            </button>
                        )}
                        <span className="readout tabular-nums">
                            {total === 0 ? '0 clips' : `${firstShown}–${lastShown} of ${total}`}
                            {' · '}page {page}/{pages || 1}
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

                {/* Filters: all server-side, so they narrow the whole library,
                    not just the page in hand. */}
                <div className="card p-2.5 sm:p-3 mb-3">
                    <div className="flex flex-wrap items-end gap-2">
                        <label className="grow min-w-[170px]">
                            <span className="eyebrow block mb-1">search</span>
                            <input
                                type="search"
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                                placeholder="title, tag or job id"
                                className="input-field w-full text-xs py-1.5"
                            />
                        </label>

                        <label>
                            <span className="eyebrow block mb-1">rendered</span>
                            <select
                                value={filters.date}
                                onChange={(e) => {
                                    const date = e.target.value;
                                    if (date === 'custom') {
                                        const start = filters.from || todayInput();
                                        updateFilter({ date, from: start, to: filters.to || start });
                                    } else {
                                        updateFilter({ date });
                                    }
                                }}
                                className="input-field text-xs py-1.5"
                            >
                                {DATE_OPTIONS.map((o) => (
                                    <option key={o.value} value={o.value}>{o.label}</option>
                                ))}
                            </select>
                        </label>

                        {filters.date === 'custom' && (
                            <>
                                <label>
                                    <span className="eyebrow block mb-1">from</span>
                                    <input
                                        type="date"
                                        value={filters.from}
                                        max={filters.to || undefined}
                                        onChange={(e) => updateFilter({ from: e.target.value })}
                                        className="input-field text-xs py-1.5"
                                    />
                                </label>
                                <label>
                                    <span className="eyebrow block mb-1">to</span>
                                    <input
                                        type="date"
                                        value={filters.to}
                                        min={filters.from || undefined}
                                        onChange={(e) => updateFilter({ to: e.target.value })}
                                        className="input-field text-xs py-1.5"
                                    />
                                </label>
                            </>
                        )}

                        <label>
                            <span className="eyebrow block mb-1">sort</span>
                            <select
                                value={filters.sort}
                                onChange={(e) => updateFilter({ sort: e.target.value })}
                                className="input-field text-xs py-1.5"
                            >
                                {SORT_OPTIONS.map((o) => (
                                    <option key={o.value} value={o.value}>{o.label}</option>
                                ))}
                            </select>
                        </label>

                        <label>
                            <span className="eyebrow block mb-1">per page</span>
                            <select
                                value={pageSize}
                                onChange={(e) => setPageSize(Number(e.target.value))}
                                className="input-field text-xs py-1.5"
                            >
                                {PAGE_SIZES.map((n) => (
                                    <option key={n} value={n}>{n}</option>
                                ))}
                            </select>
                        </label>

                        {(filtersActive || filters.sort !== 'newest' || search) && (
                            <button
                                type="button"
                                onClick={resetFilters}
                                className="btn-quiet text-xs py-1.5 px-2.5"
                            >
                                <X size={12} /> reset filters
                            </button>
                        )}
                    </div>

                    <div className="mt-2.5 grid gap-2.5 sm:grid-cols-2">
                        <div>
                            <span className="eyebrow block mb-1">review status</span>
                            <SegmentedControl
                                options={STATUS_OPTIONS}
                                value={filters.status}
                                onChange={(status) => updateFilter({ status })}
                                size="sm"
                                columns={4}
                            />
                            <p className="readout normal-case text-[11px] text-muted mt-1">
                                accepted {statusCounts.accepted} · staging {statusCounts.staged}
                                {' · '}unreviewed {statusCounts.unreviewed}
                            </p>
                        </div>
                        <div>
                            <span className="eyebrow block mb-1">posted on</span>
                            <SegmentedControl
                                options={PLATFORM_OPTIONS}
                                value={filters.platform}
                                onChange={(platform) => updateFilter({ platform })}
                                size="sm"
                                columns={5}
                            />
                        </div>
                    </div>
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
                                onClick={archiveSelected}
                                disabled={!selected.size || archiving}
                                className="btn-quiet text-xs py-1.5 px-2.5"
                            >
                                {archiving ? <Loader2 size={13} className="animate-spin" /> : <Archive size={13} />}
                                archive ({selected.size})
                            </button>
                            <button
                                type="button"
                                onClick={() => requestDelete(selectedClips)}
                                disabled={!selected.size || deleting}
                                className="btn-quiet text-xs py-1.5 px-2.5 text-danger"
                            >
                                {deleting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                                delete ({selected.size})
                            </button>
                        </>
                    )}
                    {loading && (
                        <span className="readout flex items-center gap-1.5">
                            <Loader2 size={12} className="animate-spin" /> loading
                        </span>
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
                        {filtersActive ? (
                            <>
                                <p className="text-lg mb-2 lowercase">No clips match these filters.</p>
                                <button type="button" onClick={resetFilters} className="btn-quiet text-xs py-1.5 px-2.5">
                                    reset filters
                                </button>
                            </>
                        ) : (
                            <>
                                <p className="text-lg mb-2 lowercase">
                                    {filters.status === 'accepted'
                                        ? 'No accepted clips yet.'
                                        : 'No clips found yet.'}
                                </p>
                                <p className="text-sm lowercase mb-3">
                                    {filters.status === 'accepted'
                                        ? 'Review the new clips in the Sorter — accepted ones appear here.'
                                        : 'Process some videos to populate your gallery!'}
                                </p>
                                {onOpenSorter && statusCounts.unreviewed > 0 && (
                                    <button
                                        type="button"
                                        onClick={onOpenSorter}
                                        className="btn-primary text-xs py-1.5 px-3"
                                    >
                                        <CheckCircle2 size={13} /> open sorter ({statusCounts.unreviewed})
                                    </button>
                                )}
                            </>
                        )}
                    </div>
                ) : (
                    <>
                        <div className={`grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-7 gap-2.5 sm:gap-3 pb-4 items-start transition-opacity ${loading ? 'opacity-60' : ''}`}>
                            {clips.map((clip) => (
                                <GalleryCard
                                    key={keyOf(clip)}
                                    clip={clip}
                                    selectMode={selectMode}
                                    selected={selected.has(keyOf(clip))}
                                    onToggleSelect={toggleSelected}
                                    onOpen={setActive}
                                    onDelete={(c) => requestDelete([c])}
                                />
                            ))}
                        </div>

                        {pages > 1 && (
                            <div className="flex flex-wrap items-center justify-center gap-1.5 py-6">
                                <button
                                    type="button"
                                    onClick={() => goToPage(page - 1)}
                                    disabled={page <= 1 || loading}
                                    className="btn-quiet text-xs py-1.5 px-2.5 flex items-center gap-1"
                                    aria-label="Previous page"
                                >
                                    <ChevronLeft size={13} /> prev
                                </button>
                                {pageList(page, pages).map((n, i) => (
                                    n === '…' ? (
                                        <span key={`gap-${i}`} className="readout px-1">…</span>
                                    ) : (
                                        <button
                                            key={n}
                                            type="button"
                                            onClick={() => goToPage(n)}
                                            disabled={loading}
                                            aria-current={n === page ? 'page' : undefined}
                                            className={`min-w-8 text-xs py-1.5 px-2 rounded-input tabular-nums transition-colors ${n === page
                                                ? 'bg-[color:var(--color-accent)] text-brassink'
                                                : 'btn-quiet'}`}
                                        >
                                            {n}
                                        </button>
                                    )
                                ))}
                                <button
                                    type="button"
                                    onClick={() => goToPage(page + 1)}
                                    disabled={page >= pages || loading}
                                    className="btn-quiet text-xs py-1.5 px-2.5 flex items-center gap-1"
                                    aria-label="Next page"
                                >
                                    next <ChevronRight size={13} />
                                </button>
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
                    onDelete={(c) => requestDelete([c])}
                />
            )}

            <ConfirmDeleteModal
                open={pendingDelete.length > 0}
                clips={pendingDelete}
                busy={deleting}
                error={deleteError}
                onCancel={cancelDelete}
                onConfirm={() => deleteClips(pendingDelete)}
            />
        </div>
    );
}
