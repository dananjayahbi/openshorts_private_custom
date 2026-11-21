import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
    AlertCircle, Calendar, CheckCircle2, ChevronLeft, ChevronRight, Loader2,
    Plus, Search, X,
} from 'lucide-react';
import { getApiUrl } from '../config';
import Modal from './ui/Modal';
import ClipModal from './ClipModal';

// Content Planner: a month calendar of the clips that are ready to publish.
// The plan is stored server-side (content_plan.py) as clip refs per day; the
// card expands each ref with the same metadata/poster/platform marks the Clip
// Gallery uses, so "fb used" / "yt used" and the green "posted" ring stay in
// sync with the gallery's per-platform toggles.

const keyOf = (clip) => `${clip.job_id}:${clip.index}`;
const pad = (n) => String(n).padStart(2, '0');
const isoOf = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const todayISO = () => isoOf(new Date());
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const startOfMonth = (d) => new Date(d.getFullYear(), d.getMonth(), 1);
const startOfWeek = (d) => addDays(d, -d.getDay()); // Sunday, like Creator Studio
const monthLabel = (d) => d.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const readError = async (res) => {
    try {
        const body = await res.json();
        if (typeof body?.detail === 'string') return body.detail;
        if (body?.detail?.message) return body.detail.message;
    } catch (_) { /* not JSON */ }
    return `HTTP ${res.status}`;
};

const withMedia = (clip) => ({
    ...clip,
    url: getApiUrl(clip.url),
    poster: clip.poster ? getApiUrl(clip.poster) : null,
});

function PlannerThumb({ clip, onOpen, onRemove, removing }) {
    const platforms = clip.platforms || {};
    const posted = !!(clip.used || platforms.facebook || platforms.youtube);
    return (
        <div className="relative group/thumb shrink-0">
            <button
                type="button"
                onClick={() => onOpen(clip)}
                title={`${clip.title} — click to watch`}
                className={`relative block w-9 h-14 sm:w-10 sm:h-16 rounded-input overflow-hidden border bg-black transition-all ${posted
                    ? 'border-ok ring-2 ring-ok/40'
                    : 'border-rule hover:border-brass'}`}
            >
                {clip.poster ? (
                    <img
                        src={clip.poster}
                        alt=""
                        loading="lazy"
                        draggable={false}
                        className="absolute inset-0 w-full h-full object-cover pointer-events-none"
                    />
                ) : (
                    <span className="absolute inset-0 flex items-center justify-center text-[8px] text-white/60">
                        clip
                    </span>
                )}
                <span className="absolute inset-x-0 bottom-0 flex items-center justify-center gap-0.5 bg-black/65 py-0.5">
                    {platforms.facebook && <span className="text-[7px] leading-none text-white">fb</span>}
                    {platforms.youtube && <span className="text-[7px] leading-none text-white">yt</span>}
                    {posted && !platforms.facebook && !platforms.youtube && (
                        <CheckCircle2 size={8} className="text-ok" />
                    )}
                </span>
            </button>
            <button
                type="button"
                onClick={() => onRemove(clip)}
                disabled={removing}
                title="Remove from this day"
                aria-label={`Remove ${clip.title} from this day`}
                className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-black/80 text-white/80 hover:text-danger flex items-center justify-center opacity-70 sm:opacity-0 sm:group-hover/thumb:opacity-100"
            >
                {removing ? <Loader2 size={8} className="animate-spin" /> : <X size={8} />}
            </button>
        </div>
    );
}

export default function ContentPlanner({ onOpenGallery, onOpenSorter }) {
    const [cursor, setCursor] = useState(() => startOfMonth(new Date()));
    const [days, setDays] = useState({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');
    const [active, setActive] = useState(null);
    const [removing, setRemoving] = useState('');
    const [picker, setPicker] = useState(null);
    const [pickerStatus, setPickerStatus] = useState('accepted');
    const [pickerQuery, setPickerQuery] = useState('');
    const [pickerPage, setPickerPage] = useState(1);
    const [pickerPages, setPickerPages] = useState(0);
    const [pickerClips, setPickerClips] = useState([]);
    const [pickerLoading, setPickerLoading] = useState(false);
    const [pickerError, setPickerError] = useState('');

    const grid = useMemo(() => {
        const first = startOfMonth(cursor);
        const last = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0);
        const start = startOfWeek(first);
        const end = addDays(startOfWeek(last), 6);
        const cells = [];
        for (let d = start; d <= end; d = addDays(d, 1)) cells.push(d);
        return cells;
    }, [cursor]);
    const range = useMemo(
        () => ({ from: isoOf(grid[0]), to: isoOf(grid[grid.length - 1]) }),
        [grid],
    );

    const loadPlan = useCallback(async () => {
        setLoading(true);
        try {
            const params = new URLSearchParams({ from: range.from, to: range.to });
            const res = await fetch(getApiUrl(`/api/planner?${params.toString()}`));
            if (!res.ok) throw new Error(await readError(res));
            const data = await res.json();
            if (data.media_offline) {
                throw new Error('The media drive is not connected. Plug it back in and retry.');
            }
            const next = {};
            for (const [day, clips] of Object.entries(data.days || {})) {
                next[day] = clips.map(withMedia);
            }
            setDays(next);
            setError('');
        } catch (e) {
            setError(String(e.message || e).slice(0, 240));
        } finally {
            setLoading(false);
        }
    }, [range.from, range.to]);

    useEffect(() => { loadPlan(); }, [loadPlan]);

    // The picker searches the Clip Gallery; accepted is the default because the
    // plan is for publishable clips, but staging/all are one click away.
    useEffect(() => {
        if (!picker) return undefined;
        let cancelled = false;
        const timer = setTimeout(async () => {
            setPickerLoading(true);
            setPickerError('');
            try {
                const params = new URLSearchParams({
                    status: pickerStatus,
                    view: 'active',
                    limit: '24',
                    page: String(pickerPage),
                    sort: 'newest',
                });
                if (pickerQuery.trim()) params.set('q', pickerQuery.trim());
                const res = await fetch(getApiUrl(`/api/gallery/clips?${params.toString()}`));
                if (!res.ok) throw new Error(await readError(res));
                const data = await res.json();
                if (cancelled) return;
                if (data.media_offline) {
                    throw new Error('The media drive is not connected. Plug it back in and retry.');
                }
                setPickerClips((data.clips || []).map(withMedia));
                setPickerPages(data.pages || 0);
            } catch (e) {
                if (!cancelled) setPickerError(String(e.message || e).slice(0, 240));
            } finally {
                if (!cancelled) setPickerLoading(false);
            }
        }, pickerQuery.trim() ? 300 : 0);
        return () => { cancelled = true; clearTimeout(timer); };
    }, [picker, pickerStatus, pickerPage, pickerQuery]);

    const openPicker = (day) => {
        setPicker({ date: day });
        setPickerPage(1);
        setPickerQuery('');
        setPickerClips([]);
        setPickerError('');
        setNotice('');
    };

    const closePicker = () => setPicker(null);

    const dayRefs = picker ? (days[picker.date] || []) : [];
    const plannedKeys = new Set(dayRefs.map(keyOf));

    const addClip = async (clip) => {
        if (!picker) return;
        setPickerError('');
        try {
            const res = await fetch(getApiUrl('/api/planner'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    date: picker.date,
                    job_id: clip.job_id,
                    index: clip.index,
                }),
            });
            if (!res.ok) throw new Error(await readError(res));
            const data = await res.json();
            if (data.clip) {
                const entry = { ...withMedia(data.clip), planned_on: picker.date };
                setDays((prev) => {
                    const refs = prev[picker.date] || [];
                    if (refs.some((c) => keyOf(c) === keyOf(entry))) return prev;
                    return { ...prev, [picker.date]: [...refs, entry] };
                });
            } else {
                await loadPlan();
            }
            setNotice(data.duplicate ? 'Already planned for that day.' : 'Added to the calendar.');
        } catch (e) {
            setPickerError(String(e.message || e).slice(0, 240));
        }
    };

    const removeClip = async (day, clip) => {
        const key = keyOf(clip);
        setRemoving(key);
        setNotice('');
        try {
            const res = await fetch(getApiUrl('/api/planner/remove'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ date: day, job_id: clip.job_id, index: clip.index }),
            });
            if (!res.ok) throw new Error(await readError(res));
            setDays((prev) => {
                const refs = (prev[day] || []).filter((c) => keyOf(c) !== key);
                const next = { ...prev };
                if (refs.length) next[day] = refs;
                else delete next[day];
                return next;
            });
            setNotice('Removed from the calendar.');
        } catch (e) {
            setError(String(e.message || e).slice(0, 240));
        } finally {
            setRemoving('');
        }
    };

    const handleChanged = (clip, next) => {
        // Platform/used marks changed in the modal: refresh the plan so the
        // green posted ring and fb/yt badges update without a reload.
        if (next?.archived) setActive(null);
        else {
            setActive((current) => (
                current && keyOf(current) === keyOf(clip) ? { ...current, ...next } : current));
        }
        loadPlan();
    };

    const total = Object.values(days).reduce((sum, refs) => sum + refs.length, 0);
    const monthDays = Object.entries(days)
        .filter(([day]) => day.startsWith(`${cursor.getFullYear()}-${pad(cursor.getMonth() + 1)}`))
        .reduce((sum, [, refs]) => sum + refs.length, 0);
    const today = todayISO();

    return (
        <div className="h-full overflow-y-auto overscroll-contain custom-scrollbar animate-fade">
            <div className="w-full p-3 sm:p-6">
                <div className="flex flex-wrap items-end justify-between gap-3 mb-4">
                    <div>
                        <p className="eyebrow mb-1.5">04 · Plan</p>
                        <h1 className="font-display lowercase text-2xl text-ink">Content Planner</h1>
                        <p className="text-sm text-muted mt-1 max-w-xl">
                            Add accepted clips to a day, then open any thumbnail to watch it or mark
                            it posted. A green ring means the clip is already used on a platform.
                        </p>
                    </div>
                    <div className="flex items-center gap-1.5 flex-wrap">
                        {onOpenGallery && (
                            <button type="button" onClick={onOpenGallery} className="btn-quiet text-xs py-1.5 px-2.5">
                                gallery
                            </button>
                        )}
                        {onOpenSorter && (
                            <button type="button" onClick={onOpenSorter} className="btn-quiet text-xs py-1.5 px-2.5">
                                sorter
                            </button>
                        )}
                        <span className="readout px-2 py-1 rounded-input bg-paper2">
                            {monthDays} this month · {total} in view
                        </span>
                    </div>
                </div>

                <div className="card p-2.5 sm:p-3 mb-3 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5">
                        <button
                            type="button"
                            onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}
                            className="btn-quiet p-2"
                            aria-label="Previous month"
                        >
                            <ChevronLeft size={15} />
                        </button>
                        <button
                            type="button"
                            onClick={() => setCursor(startOfMonth(new Date()))}
                            className="btn-quiet text-xs py-1.5 px-2.5"
                        >
                            today
                        </button>
                        <button
                            type="button"
                            onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}
                            className="btn-quiet p-2"
                            aria-label="Next month"
                        >
                            <ChevronRight size={15} />
                        </button>
                        <h2 className="font-display lowercase text-lg text-ink ml-1.5 flex items-center gap-2">
                            <Calendar size={16} className="text-brass" />
                            {monthLabel(cursor)}
                        </h2>
                    </div>
                    <div className="flex items-center gap-2">
                        {loading && (
                            <span className="readout flex items-center gap-1.5">
                                <Loader2 size={11} className="animate-spin" /> loading
                            </span>
                        )}
                        <span className="readout text-[11px] hidden sm:inline">
                            click a clip to watch · <span className="text-ok">green</span> = posted
                        </span>
                    </div>
                </div>

                {error && (
                    <div className="mb-3 rounded-card border border-danger/40 px-3 py-2 text-xs text-danger flex items-center gap-2">
                        <AlertCircle size={13} /> {error}
                        <button type="button" onClick={() => setError('')} className="ml-auto" aria-label="Dismiss">
                            <X size={13} />
                        </button>
                    </div>
                )}
                {notice && (
                    <div className="mb-3 rounded-card border border-rule bg-paper2 px-3 py-2 text-xs text-ink2 flex items-center gap-2">
                        <CheckCircle2 size={13} className="text-ok" /> {notice}
                        <button type="button" onClick={() => setNotice('')} className="ml-auto" aria-label="Dismiss">
                            <X size={13} />
                        </button>
                    </div>
                )}

                <div className="rounded-card border border-rule overflow-hidden">
                    <div className="grid grid-cols-7 bg-paper2/70 border-b border-rule">
                        {WEEKDAYS.map((day) => (
                            <div key={day} className="px-1.5 py-1.5 text-center readout text-[10px] border-r border-rule last:border-r-0">
                                {day}
                            </div>
                        ))}
                    </div>
                    <div className="grid grid-cols-7">
                        {grid.map((date, index) => {
                            const day = isoOf(date);
                            const clips = days[day] || [];
                            const inMonth = date.getMonth() === cursor.getMonth();
                            const isToday = day === today;
                            return (
                                <div
                                    key={day}
                                    className={`min-h-[112px] sm:min-h-[132px] p-1 sm:p-1.5 border-r border-b border-rule last:border-r-0 flex flex-col ${inMonth ? 'bg-paper' : 'bg-paper2/30'}
                                        ${isToday ? 'ring-1 ring-inset ring-brass/60' : ''}
                                        ${(index + 1) % 7 === 0 ? 'border-r-0' : ''}`}
                                >
                                    <div className="flex items-center justify-between mb-1">
                                        <span className={`text-[11px] tabular-nums ${isToday ? 'text-brass font-medium' : inMonth ? 'text-ink2' : 'text-muted'}`}>
                                            {date.getDate()}
                                        </span>
                                        {isToday && <span className="text-[8px] uppercase tracking-wide text-brass">today</span>}
                                    </div>
                                    <div className="flex flex-wrap gap-1 content-start flex-1">
                                        {clips.map((clip) => (
                                            <PlannerThumb
                                                key={`${day}:${keyOf(clip)}`}
                                                clip={clip}
                                                onOpen={(c) => setActive({ ...c, planned_on: day })}
                                                onRemove={(c) => removeClip(day, c)}
                                                removing={removing === keyOf(clip)}
                                            />
                                        ))}
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => openPicker(day)}
                                        className="mt-1 inline-flex items-center gap-0.5 text-[10px] text-muted hover:text-brass transition-colors self-start"
                                        title={`Add a clip to ${day}`}
                                    >
                                        <Plus size={10} /> add
                                    </button>
                                </div>
                            );
                        })}
                    </div>
                </div>

                <p className="readout text-[11px] text-muted mt-2">
                    The plan is stored with your settings, so unplugging the media drive keeps the
                    calendar and brings the clips back when you plug it in.
                </p>
            </div>

            {active && (
                <ClipModal
                    clip={active}
                    onClose={() => setActive(null)}
                    onChanged={handleChanged}
                    onDelete={(clip) => {
                        setActive(null);
                        removeClip(clip.planned_on, clip);
                    }}
                    deleteLabel="remove from plan"
                />
            )}

            <Modal
                isOpen={!!picker}
                onClose={closePicker}
                title={picker ? `Add to ${picker.date}` : 'Add clips'}
                eyebrow="Content Planner"
                size="xl"
                layer="z-[135]"
            >
                {picker && (
                    <div className="space-y-3">
                        <div className="flex flex-wrap items-center gap-2">
                            <div className="flex gap-1">
                                {[
                                    ['accepted', 'accepted'],
                                    ['staged', 'staging'],
                                    ['all', 'all'],
                                ].map(([value, label]) => (
                                    <button
                                        key={value}
                                        type="button"
                                        onClick={() => { setPickerStatus(value); setPickerPage(1); }}
                                        className={`px-2.5 py-1.5 rounded-input text-xs border transition-colors ${pickerStatus === value
                                            ? 'border-brass text-ink bg-brass/10'
                                            : 'border-rule text-muted hover:text-ink'}`}
                                    >
                                        {label}
                                    </button>
                                ))}
                            </div>
                            <label className="grow min-w-[160px] relative">
                                <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
                                <input
                                    type="search"
                                    value={pickerQuery}
                                    onChange={(e) => { setPickerQuery(e.target.value); setPickerPage(1); }}
                                    placeholder="search title or tag"
                                    className="input-field w-full text-xs py-1.5 pl-7"
                                />
                            </label>
                        </div>

                        {pickerError && (
                            <p className="text-[11px] text-danger" role="alert">{pickerError}</p>
                        )}
                        {notice && !pickerError && (
                            <p className="text-[11px] text-ok flex items-center gap-1">
                                <CheckCircle2 size={12} /> {notice}
                            </p>
                        )}

                        {pickerLoading && pickerClips.length === 0 ? (
                            <div className="py-10 flex items-center justify-center text-muted text-sm gap-2">
                                <Loader2 size={16} className="animate-spin" /> loading clips…
                            </div>
                        ) : pickerClips.length === 0 ? (
                            <div className="py-10 text-center text-muted text-sm">
                                <p className="lowercase mb-1">No clips match.</p>
                                <p className="text-xs mb-3">
                                    Accepted clips appear here. Review more in the Sorter.
                                </p>
                                {onOpenSorter && (
                                    <button
                                        type="button"
                                        onClick={() => { closePicker(); onOpenSorter(); }}
                                        className="btn-primary text-xs py-1.5 px-3"
                                    >
                                        open sorter
                                    </button>
                                )}
                            </div>
                        ) : (
                            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2">
                                {pickerClips.map((clip) => {
                                    const planned = plannedKeys.has(keyOf(clip));
                                    return (
                                        <button
                                            key={keyOf(clip)}
                                            type="button"
                                            onClick={() => addClip(clip)}
                                            disabled={planned}
                                            title={clip.title}
                                            className={`group relative rounded-input border overflow-hidden text-left transition-colors ${planned
                                                ? 'border-ok/50 opacity-70 cursor-default'
                                                : 'border-rule hover:border-brass'}`}
                                        >
                                            <span className="block relative bg-black aspect-[9/16]">
                                                {clip.poster ? (
                                                    <img
                                                        src={clip.poster}
                                                        alt=""
                                                        loading="lazy"
                                                        draggable={false}
                                                        className="absolute inset-0 w-full h-full object-cover pointer-events-none"
                                                    />
                                                ) : (
                                                    <span className="absolute inset-0 flex items-center justify-center text-[10px] text-white/50">
                                                        clip
                                                    </span>
                                                )}
                                                <span className="absolute bottom-1 left-1 flex gap-0.5">
                                                    {clip.platforms?.facebook && (
                                                        <span className="text-[8px] px-1 rounded bg-black/80 text-white">fb</span>
                                                    )}
                                                    {clip.platforms?.youtube && (
                                                        <span className="text-[8px] px-1 rounded bg-black/80 text-white">yt</span>
                                                    )}
                                                </span>
                                                {planned && (
                                                    <span className="absolute inset-0 bg-black/60 flex items-center justify-center">
                                                        <CheckCircle2 size={18} className="text-ok" />
                                                    </span>
                                                )}
                                            </span>
                                            <span className="block px-1.5 py-1">
                                                <span className="block text-[10px] leading-snug text-ink line-clamp-2">
                                                    {clip.title}
                                                </span>
                                            </span>
                                        </button>
                                    );
                                })}
                            </div>
                        )}

                        {pickerPages > 1 && (
                            <div className="flex items-center justify-center gap-2 pt-1">
                                <button
                                    type="button"
                                    onClick={() => setPickerPage((p) => Math.max(1, p - 1))}
                                    disabled={pickerPage <= 1 || pickerLoading}
                                    className="btn-quiet text-xs py-1.5 px-2.5"
                                >
                                    prev
                                </button>
                                <span className="readout">
                                    page {pickerPage}/{pickerPages}
                                </span>
                                <button
                                    type="button"
                                    onClick={() => setPickerPage((p) => Math.min(pickerPages, p + 1))}
                                    disabled={pickerPage >= pickerPages || pickerLoading}
                                    className="btn-quiet text-xs py-1.5 px-2.5"
                                >
                                    next
                                </button>
                            </div>
                        )}
                    </div>
                )}
            </Modal>
        </div>
    );
}
