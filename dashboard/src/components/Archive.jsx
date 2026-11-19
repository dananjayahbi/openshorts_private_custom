import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
    AlertTriangle, Archive, ArrowLeft, CheckCircle2, ChevronLeft, ChevronRight,
    Circle, Database, Download, Folder, FolderOpen, HardDrive, Loader2, Play,
    Plus, RefreshCw, Trash2, Unplug, Upload, X,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { getApiUrl } from '../config';
import Modal from './ui/Modal';
import SegmentedControl from './ui/SegmentedControl';

// The Archive: clips that are done with the working folders, kept forever in
// Storage/archive, plus the external vaults they can be pushed to. The index
// lives in SQLite server-side, so every filter/sort/page is one small query —
// a library of thousands of clips never scans folders to render this page.

const PAGE_SIZES = [24, 48, 96];
const DATE_OPTIONS = [
    { value: 'any', label: 'any time' },
    { value: 'today', label: 'today' },
    { value: 'yesterday', label: 'yesterday' },
    { value: 'week', label: 'this week' },
    { value: 'month', label: 'this month' },
    { value: 'custom', label: 'custom range' },
];
const STATE_OPTIONS = [
    { value: 'any', label: 'any' },
    { value: 'local', label: 'on this PC' },
    { value: 'vaulted', label: 'in a vault' },
    { value: 'pending_delete', label: 'queued delete' },
    { value: 'missing', label: 'missing' },
];
const PLATFORM_OPTIONS = [
    { value: 'any', label: 'any' },
    { value: 'youtube', label: 'youtube' },
    { value: 'facebook', label: 'facebook' },
    { value: 'both', label: 'both' },
    { value: 'none', label: 'not posted' },
];
const SORT_OPTIONS = [
    { value: 'newest', label: 'newest first' },
    { value: 'oldest', label: 'oldest first' },
    { value: 'longest', label: 'longest first' },
    { value: 'shortest', label: 'shortest first' },
    { value: 'score', label: 'best score' },
    { value: 'largest', label: 'largest first' },
    { value: 'smallest', label: 'smallest first' },
];
const EMPTY_FILTERS = {
    date: 'any', from: '', to: '', vault: 'any', state: 'any',
    platform: 'any', sort: 'newest', q: '',
};

const fmtBytes = (bytes) => {
    const n = Number(bytes) || 0;
    if (!n) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = n;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    return `${value >= 10 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
};

const fmtDuration = (seconds) => {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    if (!total) return '—';
    const m = Math.floor(total / 60);
    const s = total % 60;
    return m ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`;
};

const todayInput = () => {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

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

const request = async (path, options = {}) => {
    const res = await apiFetch(path, options);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
    return body;
};

const stateTone = (state) => {
    if (state === 'local') return 'text-ok';
    if (state === 'vaulted') return 'text-brass';
    if (state === 'pending_delete') return 'text-danger';
    if (state === 'missing') return 'text-danger';
    return 'text-muted';
};

const itemStateLabel = (item) => {
    if (item.state === 'vaulted') return item.vault_name || 'in a vault';
    if (item.state === 'pushing') return 'copying to vault…';
    if (item.state === 'pending_delete') return 'delete when connected';
    if (item.state === 'missing') return 'file missing';
    return 'on this pc';
};

export default function ArchivePage({ onOpenGallery }) {
    const [items, setItems] = useState([]);
    const [total, setTotal] = useState(0);
    const [pages, setPages] = useState(0);
    const [page, setPage] = useState(1);
    const [counts, setCounts] = useState({});
    const [stats, setStats] = useState({ items: 0, bytes: 0, bytes_local: 0, bytes_vaulted: 0 });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');

    const [filters, setFilters] = useState(EMPTY_FILTERS);
    const [search, setSearch] = useState('');
    const [pageSize, setPageSize] = useState(48);

    const [vaults, setVaults] = useState([]);
    const [unrecognized, setUnrecognized] = useState([]);
    const [settings, setSettings] = useState({
        auto_archive_enabled: false, auto_archive_days: 7, job_retention_seconds: 0,
    });
    const [retentionInput, setRetentionInput] = useState('7');

    const [selectMode, setSelectMode] = useState(false);
    const [selected, setSelected] = useState(() => new Set());
    const [pendingDelete, setPendingDelete] = useState([]);
    const [deleting, setDeleting] = useState(false);
    const [busy, setBusy] = useState('');
    const [pushVault, setPushVault] = useState('');

    const [player, setPlayer] = useState(null);
    const [picker, setPicker] = useState(null);
    const [vaultForm, setVaultForm] = useState({ name: '', sizeGb: '100' });
    const [pickerBusy, setPickerBusy] = useState(false);
    const [expandInputs, setExpandInputs] = useState({});
    const [expanding, setExpanding] = useState('');
    const [confirmVaultDelete, setConfirmVaultDelete] = useState('');

    const connectedVaults = useMemo(
        () => vaults.filter((vault) => vault.connected), [vaults]);

    const loadItems = useCallback(async (targetPage = 1) => {
        if (filters.date === 'custom' && (!filters.from || !filters.to)) {
            setLoading(false);
            return;
        }
        setLoading(true);
        try {
            const params = new URLSearchParams({
                limit: String(pageSize),
                page: String(Math.max(1, targetPage)),
                date: filters.date,
                vault: filters.vault,
                state: filters.state,
                platform: filters.platform,
                sort: filters.sort,
            });
            if (filters.date === 'custom') {
                params.set('date_from', filters.from);
                params.set('date_to', filters.to);
            }
            if (filters.q) params.set('q', filters.q);
            const data = await request(`/api/archive/items?${params.toString()}`);
            setItems(data.items || []);
            setTotal(data.total || 0);
            setPages(data.pages || 0);
            setPage(data.page || 1);
            setCounts(data.counts || {});
            setStats(data.stats || {});
            setPlayer((current) => {
                if (!current) return current;
                return (data.items || []).find((item) => item.id === current.id) || current;
            });
            setError('');
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setLoading(false);
        }
    }, [filters, pageSize]);

    const loadVaults = useCallback(async () => {
        try {
            const data = await request('/api/archive/vaults');
            setVaults(data.vaults || []);
            setUnrecognized(data.unrecognized || []);
        } catch (_) { /* polling retries */ }
    }, []);

    const loadSettings = useCallback(async () => {
        try {
            const data = await request('/api/archive/settings');
            setSettings(data);
            setRetentionInput(String(data.auto_archive_days ?? 7));
        } catch (_) { /* defaults stay */ }
    }, []);

    useEffect(() => {
        setSelected(new Set());
        setSelectMode(false);
        loadItems(1);
    }, [loadItems]);

    useEffect(() => {
        loadVaults();
        loadSettings();
    }, [loadVaults, loadSettings]);

    useEffect(() => {
        const id = setTimeout(() => {
            setFilters((prev) => (prev.q === search ? prev : { ...prev, q: search.trim() }));
        }, 350);
        return () => clearTimeout(id);
    }, [search]);

    const hasActive = items.some((item) => item.state === 'pushing')
        || vaults.some((vault) => ['creating', 'expanding'].includes(vault.state));
    useEffect(() => {
        if (!hasActive) return undefined;
        const id = setInterval(() => {
            loadItems(page);
            loadVaults();
        }, 2500);
        return () => clearInterval(id);
    }, [hasActive, page, loadItems, loadVaults]);

    const updateFilter = (patch) => setFilters((prev) => ({ ...prev, ...patch }));
    const resetFilters = () => {
        setSearch('');
        setFilters(EMPTY_FILTERS);
    };

    const goToPage = (next) => {
        if (loading || next === page || next < 1 || (pages && next > pages)) return;
        setSelected(new Set());
        loadItems(next);
    };

    const selectedItems = items.filter((item) => selected.has(item.id));
    const allSelected = items.length > 0 && selectedItems.length === items.length;

    const toggleSelected = (item) => {
        setSelected((prev) => {
            const next = new Set(prev);
            if (next.has(item.id)) next.delete(item.id);
            else next.add(item.id);
            return next;
        });
    };

    const refreshAll = async () => {
        await Promise.all([loadItems(page), loadVaults()]);
    };

    const saveSettings = async (patch) => {
        setBusy('settings');
        setError('');
        try {
            const data = await request('/api/archive/settings', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(patch),
            });
            setSettings((prev) => ({ ...prev, ...data }));
            setRetentionInput(String(data.auto_archive_days ?? 7));
            setNotice('Auto-archive rule saved.');
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setBusy('');
        }
    };

    const push = async (targets) => {
        if (!targets.length) return;
        const vault = pushVault || connectedVaults[0]?.id;
        if (!vault) {
            setError('Connect a vault before pushing clips.');
            return;
        }
        setBusy('push');
        setError('');
        try {
            const data = await request('/api/archive/items/push', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: targets.map((item) => item.id), vault_id: vault }),
            });
            setNotice(`Queued ${data.queued?.length || 0} clip(s) for a verified move.`);
            setSelected(new Set());
            setSelectMode(false);
            await refreshAll();
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setBusy('');
        }
    };

    const runAction = async (action, targets) => {
        if (!targets.length) return;
        setBusy(action);
        setError('');
        try {
            const data = await request(`/api/archive/items/${action}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: targets.map((item) => item.id) }),
            });
            const failed = data.failed || [];
            const done = (data.restored || data.unarchived || []).length;
            if (failed.length) {
                setError(failed[0].error || `${failed.length} clip(s) could not be processed.`);
            } else if (done) {
                setNotice(action === 'restore'
                    ? `Restored ${done} clip(s) to this PC.`
                    : `Returned ${done} clip(s) to the Clip Gallery.`);
            }
            setSelected(new Set());
            setSelectMode(false);
            await refreshAll();
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setBusy('');
        }
    };

    const deleteClips = async () => {
        const targets = pendingDelete;
        if (!targets.length || deleting) return;
        setDeleting(true);
        setError('');
        try {
            const data = await request('/api/archive/items/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: targets.map((item) => item.id) }),
            });
            const failed = data.failed || [];
            if (failed.length) {
                setError(failed[0].error || `${failed.length} clip(s) could not be deleted.`);
            }
            if (data.queued?.length) {
                setNotice(`${data.queued.length} clip(s) will be deleted when their vault reconnects.`);
            }
            setPendingDelete([]);
            setSelected(new Set());
            setSelectMode(false);
            setPlayer((current) => (current && targets.some((item) => item.id === current.id)
                ? null : current));
            await refreshAll();
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setDeleting(false);
        }
    };

    const createVault = async () => {
        if (!picker?.path) {
            setError('Choose a folder on the device first.');
            return;
        }
        const gb = Number(vaultForm.sizeGb);
        if (!Number.isFinite(gb) || gb <= 0) {
            setError('Enter the vault size in GB.');
            return;
        }
        setPickerBusy(true);
        setError('');
        try {
            await request('/api/archive/vaults', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    folder: picker.path,
                    name: vaultForm.name.trim(),
                    size_bytes: Math.round(gb * 1024 ** 3),
                }),
            });
            setPicker(null);
            setNotice(
                'Vault created. The app is writing its file now so the space is really '
                + 'reserved — this can take a while on a large vault.',
            );
            await loadVaults();
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setPickerBusy(false);
        }
    };

    const expandVault = async (vault) => {
        const gb = Number(expandInputs[vault.id]);
        if (!Number.isFinite(gb) || gb <= Number(vault.capacity_bytes) / 1024 ** 3) {
            setError('The new size has to be larger than the vault.');
            return;
        }
        setExpanding(vault.id);
        setError('');
        try {
            await request(`/api/archive/vaults/${vault.id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ size_bytes: Math.round(gb * 1024 ** 3) }),
            });
            setNotice(`Growing “${vault.name}”…`);
            await loadVaults();
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setExpanding('');
        }
    };

    const deleteVault = async (vault) => {
        if (confirmVaultDelete !== vault.id) {
            setConfirmVaultDelete(vault.id);
            return;
        }
        setConfirmVaultDelete('');
        setBusy(`vault-${vault.id}`);
        setError('');
        try {
            await request(`/api/archive/vaults/${vault.id}?confirm=true`, { method: 'DELETE' });
            setNotice(`Deleted “${vault.name}” and the archived clips inside it.`);
            await refreshAll();
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setBusy('');
        }
    };

    const adopt = async (path) => {
        setBusy('adopt');
        setError('');
        try {
            const data = await request('/api/archive/vaults/adopt', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path }),
            });
            setNotice(`Adopted “${data.vault?.name}” (${data.imported || 0} clip(s) found).`);
            await refreshAll();
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setBusy('');
        }
    };

    const openPicker = async () => {
        setError('');
        setVaultForm({ name: '', sizeGb: '100' });
        setPickerBusy(true);
        try {
            const data = await request('/api/archive/devices');
            setPicker({ path: '', parent: null, directories: [], devices: data.devices || [] });
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setPickerBusy(false);
        }
    };

    const browseTo = async (path) => {
        setPickerBusy(true);
        try {
            const data = await request(`/api/archive/browse?path=${encodeURIComponent(path)}`);
            setPicker((prev) => ({ ...prev, ...data }));
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setPickerBusy(false);
        }
    };

    const rescan = async () => {
        setBusy('scan');
        try {
            await request('/api/archive/vaults/scan', { method: 'POST' });
            await loadVaults();
            setNotice('Devices rescanned.');
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            setBusy('');
        }
    };

    const filtersActive = filters.date !== 'any' || filters.vault !== 'any'
        || filters.state !== 'any' || filters.platform !== 'any' || !!filters.q;

    const firstShown = total === 0 ? 0 : (page - 1) * pageSize + 1;
    const lastShown = (page - 1) * pageSize + items.length;
    const retentionDays = Math.max(0, (Number(settings.job_retention_seconds) || 0) / 86400);
    const autoTooSlow = settings.auto_archive_enabled && retentionDays > 0
        && Number(settings.auto_archive_days) >= retentionDays;

    const openItem = (item) => {
        setPlayer(item);
        if (!item.playable) {
            setNotice(item.state === 'vaulted'
                ? `Connect the device that holds “${item.vault_name}” to play this clip.`
                : 'This clip is not available to play.');
        }
    };

    return (
        <div className="h-full overflow-y-auto overscroll-contain custom-scrollbar animate-fade">
            <div className="w-full p-3 sm:p-6 space-y-5">
                <header className="flex flex-wrap items-end justify-between gap-3">
                    <div>
                        <p className="eyebrow flex items-center gap-2"><Archive size={12} /> ARCHIVE</p>
                        <h1 className="font-display lowercase text-3xl md:text-4xl text-ink">
                            Archive &amp; vaults
                        </h1>
                        <p className="text-muted text-sm md:text-base leading-relaxed max-w-2xl mt-2">
                            Finished clips live here for good, out of the working folders. Filter
                            them, push them onto an external device, and delete when you need the
                            space back. The poster and details stay on this PC even when the video
                            is in a vault.
                        </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <button type="button" onClick={rescan} disabled={busy === 'scan'}
                            className="btn-quiet px-3 py-1.5 text-xs">
                            <RefreshCw size={13} className={busy === 'scan' ? 'animate-spin' : ''} /> rescan
                        </button>
                        {onOpenGallery && (
                            <button type="button" onClick={onOpenGallery} className="btn-quiet px-3 py-1.5 text-xs">
                                <ArrowLeft size={13} /> clip gallery
                            </button>
                        )}
                        <button type="button" onClick={openPicker} disabled={pickerBusy}
                            className="btn-primary px-4 py-2 text-sm">
                            {pickerBusy ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}
                            add vault
                        </button>
                    </div>
                </header>

                <div className="flex flex-wrap gap-2">
                    <span className="readout card px-3 py-1.5">
                        <span className="text-ink">{stats.items || 0}</span> archived clips
                    </span>
                    <span className="readout card px-3 py-1.5">
                        <span className="text-ink">{fmtBytes(stats.bytes_local)}</span> on this pc
                    </span>
                    <span className="readout card px-3 py-1.5">
                        <span className="text-ink">{fmtBytes(stats.bytes_vaulted)}</span> in vaults
                    </span>
                    {counts.pending_delete > 0 && (
                        <span className="readout card px-3 py-1.5 text-danger">
                            {counts.pending_delete} queued delete
                        </span>
                    )}
                </div>

                {error && (
                    <div role="alert" className="px-4 py-3 rounded-card border border-danger/40 bg-paper2 text-sm text-danger flex items-start gap-2">
                        <AlertTriangle size={15} className="shrink-0 mt-0.5" />
                        <span className="flex-1 break-words">{error}</span>
                        <button type="button" onClick={() => setError('')} className="text-muted hover:text-ink" aria-label="dismiss">×</button>
                    </div>
                )}
                {notice && (
                    <div className="px-4 py-3 rounded-card border border-rule bg-paper2 text-sm text-ink2 flex items-start gap-2">
                        <CheckCircle2 size={15} className="shrink-0 mt-0.5 text-ok" />
                        <span className="flex-1 break-words">{notice}</span>
                        <button type="button" onClick={() => setNotice('')} className="text-muted hover:text-ink" aria-label="dismiss">×</button>
                    </div>
                )}

                {/* ---- vaults ------------------------------------------------- */}
                <section className="space-y-3">
                    <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-sm text-ink lowercase flex items-center gap-2">
                            <HardDrive size={14} className="text-brass" /> storage vaults
                        </h2>
                        {!vaults.length && <span className="readout">none yet</span>}
                    </div>

                    {unrecognized.length > 0 && (
                        <div className="card border border-brass/40 p-3 space-y-2">
                            {unrecognized.map((foreign) => (
                                <div key={foreign.path} className="flex flex-wrap items-center gap-2 text-xs">
                                    <Database size={13} className="text-brass shrink-0" />
                                    <span className="text-ink">Found “{foreign.name}”</span>
                                    <span className="readout break-all flex-1 min-w-0">{foreign.path}</span>
                                    <button
                                        type="button"
                                        onClick={() => adopt(foreign.path)}
                                        disabled={busy === 'adopt'}
                                        className="btn-quiet px-2.5 py-1 text-xs"
                                    >
                                        {busy === 'adopt' ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                                        adopt
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}

                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                        {vaults.map((vault) => {
                            const busyHere = vault.state === 'creating' || vault.state === 'expanding';
                            const pct = vault.usable_bytes
                                ? Math.min(100, Math.round((vault.used_bytes / vault.usable_bytes) * 100))
                                : 0;
                            return (
                                <div key={vault.id} className="card p-4 space-y-3">
                                    <div className="flex items-start gap-2">
                                        <div className={`w-8 h-8 rounded-input flex items-center justify-center shrink-0 ${vault.connected ? 'bg-paper3 text-brass' : 'bg-paper3 text-muted'}`}>
                                            <HardDrive size={15} />
                                        </div>
                                        <div className="min-w-0 flex-1">
                                            <h3 className="text-sm text-ink truncate" title={vault.name}>{vault.name}</h3>
                                            <p className="readout break-all line-clamp-1" title={vault.path || vault.folder}>
                                                {vault.path || vault.folder || 'not located yet'}
                                            </p>
                                        </div>
                                        <span className={`readout shrink-0 flex items-center gap-1 ${vault.connected ? 'text-ok' : 'text-danger'}`}>
                                            {vault.connected ? <CheckCircle2 size={11} /> : <Unplug size={11} />}
                                            {busyHere ? (vault.state === 'creating' ? 'preparing' : 'growing')
                                                : vault.connected ? 'connected' : 'disconnected'}
                                        </span>
                                    </div>

                                    {busyHere ? (
                                        <div className="space-y-1">
                                            <div className="h-1.5 rounded-full bg-paper3 overflow-hidden">
                                                <div className="h-full bg-brass transition-all" style={{ width: `${vault.progress || 0}%` }} />
                                            </div>
                                            <p className="text-[11px] text-muted">
                                                {vault.progress || 0}% · {fmtBytes(vault.progress_bytes)} written
                                            </p>
                                        </div>
                                    ) : (
                                        <div className="space-y-1">
                                            <div className="h-1.5 rounded-full bg-paper3 overflow-hidden">
                                                <div className={`h-full transition-all ${pct > 90 ? 'bg-danger' : 'bg-brass'}`} style={{ width: `${pct}%` }} />
                                            </div>
                                            <div className="flex justify-between readout">
                                                <span>{fmtBytes(vault.used_bytes)} used</span>
                                                <span>{fmtBytes(vault.free_bytes)} free</span>
                                            </div>
                                        </div>
                                    )}

                                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
                                        <span>{vault.items} clip{vault.items === 1 ? '' : 's'}</span>
                                        <span>size {fmtBytes(vault.capacity_bytes)}</span>
                                    </div>

                                    {vault.error && <p className="text-xs text-danger break-words">{vault.error}</p>}

                                    <div className="flex flex-wrap items-center gap-2 pt-1">
                                        {vault.state === 'ready' && (
                                            <>
                                                <label className="flex items-center gap-1.5 text-[11px] text-muted">
                                                    grow to
                                                    <input
                                                        type="number"
                                                        min={Math.ceil(vault.capacity_bytes / 1024 ** 3)}
                                                        step="1"
                                                        value={expandInputs[vault.id] ?? ''}
                                                        placeholder={String(Math.ceil(vault.capacity_bytes / 1024 ** 3) + 10)}
                                                        onChange={(e) => setExpandInputs((current) => ({ ...current, [vault.id]: e.target.value }))}
                                                        className="input-field !w-20 text-xs py-1"
                                                        aria-label={`new size for ${vault.name} in GB`}
                                                    />
                                                    GB
                                                </label>
                                                <button
                                                    type="button"
                                                    onClick={() => expandVault(vault)}
                                                    disabled={expanding === vault.id}
                                                    className="btn-quiet px-2.5 py-1 text-xs"
                                                >
                                                    {expanding === vault.id
                                                        ? <Loader2 size={12} className="animate-spin" />
                                                        : <Plus size={12} />} grow
                                                </button>
                                            </>
                                        )}
                                        {vault.state === 'error' && (
                                            <button
                                                type="button"
                                                onClick={() => deleteVault(vault)}
                                                className={`btn-quiet px-2.5 py-1 text-xs ml-auto ${confirmVaultDelete === vault.id ? 'text-danger' : ''}`}
                                            >
                                                <Trash2 size={12} /> remove the failed vault
                                            </button>
                                        )}
                                        {vault.state !== 'creating' && (
                                            <button
                                                type="button"
                                                onClick={() => deleteVault(vault)}
                                                disabled={!!busy.startsWith('vault-') || (vault.state === 'ready' && !vault.connected)}
                                                title={vault.state === 'ready' && !vault.connected
                                                    ? 'Connect the device before deleting this vault' : undefined}
                                                className={`btn-quiet px-2.5 py-1 text-xs ml-auto ${confirmVaultDelete === vault.id ? 'text-danger' : ''}`}
                                            >
                                                {busy === `vault-${vault.id}`
                                                    ? <Loader2 size={12} className="animate-spin" />
                                                    : <Trash2 size={12} />}
                                                {confirmVaultDelete === vault.id ? 'wipe vault?' : 'delete'}
                                            </button>
                                        )}
                                        {confirmVaultDelete === vault.id && (
                                            <button type="button" onClick={() => setConfirmVaultDelete('')} className="btn-quiet px-2.5 py-1 text-xs">
                                                cancel
                                            </button>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>

                    <div className="card p-3 flex flex-wrap items-end gap-3">
                        <label className="flex items-center gap-2 text-xs text-ink2">
                            <input
                                type="checkbox"
                                checked={!!settings.auto_archive_enabled}
                                onChange={(e) => saveSettings({ auto_archive_enabled: e.target.checked })}
                                className="accent-[color:var(--color-accent)]"
                            />
                            auto-archive clips this many days after posting
                        </label>
                        <label className="flex items-center gap-1.5 text-xs text-muted">
                            <input
                                type="number"
                                min="0"
                                max="365"
                                value={retentionInput}
                                onChange={(e) => setRetentionInput(e.target.value)}
                                className="input-field !w-20 text-xs py-1"
                                aria-label="auto-archive delay in days"
                            />
                            days
                        </label>
                        <button
                            type="button"
                            onClick={() => saveSettings({ auto_archive_days: Number(retentionInput) })}
                            disabled={busy === 'settings'}
                            className="btn-quiet px-3 py-1.5 text-xs"
                        >
                            {busy === 'settings' ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
                            save rule
                        </button>
                        {autoTooSlow && (
                            <span className="text-[11px] text-danger flex items-center gap-1">
                                <AlertTriangle size={12} />
                                unarchived clips are swept after {retentionDays.toFixed(1)} day(s); use a shorter delay
                            </span>
                        )}
                    </div>
                </section>

                {/* ---- filters ------------------------------------------------ */}
                <section className="card p-2.5 sm:p-3 space-y-2">
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
                            <span className="eyebrow block mb-1">archived</span>
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
                                {DATE_OPTIONS.map((option) => (
                                    <option key={option.value} value={option.value}>{option.label}</option>
                                ))}
                            </select>
                        </label>

                        {filters.date === 'custom' && (
                            <>
                                <label>
                                    <span className="eyebrow block mb-1">from</span>
                                    <input type="date" value={filters.from} max={filters.to || undefined}
                                        onChange={(e) => updateFilter({ from: e.target.value })}
                                        className="input-field text-xs py-1.5" />
                                </label>
                                <label>
                                    <span className="eyebrow block mb-1">to</span>
                                    <input type="date" value={filters.to} min={filters.from || undefined}
                                        onChange={(e) => updateFilter({ to: e.target.value })}
                                        className="input-field text-xs py-1.5" />
                                </label>
                            </>
                        )}

                        <label>
                            <span className="eyebrow block mb-1">vault</span>
                            <select
                                value={filters.vault}
                                onChange={(e) => updateFilter({ vault: e.target.value })}
                                className="input-field text-xs py-1.5 max-w-[11rem]"
                            >
                                <option value="any">any</option>
                                <option value="local">on this pc</option>
                                <option value="missing">missing</option>
                                {vaults.map((vault) => (
                                    <option key={vault.id} value={vault.id}>{vault.name}</option>
                                ))}
                            </select>
                        </label>

                        <label>
                            <span className="eyebrow block mb-1">state</span>
                            <select
                                value={filters.state}
                                onChange={(e) => updateFilter({ state: e.target.value })}
                                className="input-field text-xs py-1.5"
                            >
                                {STATE_OPTIONS.map((option) => (
                                    <option key={option.value} value={option.value}>{option.label}</option>
                                ))}
                            </select>
                        </label>

                        <label>
                            <span className="eyebrow block mb-1">sort</span>
                            <select
                                value={filters.sort}
                                onChange={(e) => updateFilter({ sort: e.target.value })}
                                className="input-field text-xs py-1.5"
                            >
                                {SORT_OPTIONS.map((option) => (
                                    <option key={option.value} value={option.value}>{option.label}</option>
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
                                {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
                            </select>
                        </label>

                        {(filtersActive || filters.sort !== 'newest' || search) && (
                            <button type="button" onClick={resetFilters} className="btn-quiet text-xs py-1.5 px-2.5">
                                <X size={12} /> reset filters
                            </button>
                        )}
                    </div>

                    <div>
                        <span className="eyebrow block mb-1">posted on</span>
                        <div className="max-w-md">
                            <SegmentedControl
                                options={PLATFORM_OPTIONS}
                                value={filters.platform}
                                onChange={(platform) => updateFilter({ platform })}
                                size="sm"
                                columns={5}
                            />
                        </div>
                    </div>
                </section>

                {/* ---- bulk actions ------------------------------------------- */}
                <div className="flex flex-wrap items-center gap-2">
                    <button
                        type="button"
                        onClick={() => { setSelectMode((v) => !v); setSelected(new Set()); }}
                        className={`btn-quiet text-xs py-1.5 px-2.5 ${selectMode ? 'text-brass' : ''}`}
                    >
                        {selectMode ? <X size={13} /> : <CheckCircle2 size={13} />}
                        {selectMode ? 'cancel selection' : 'select'}
                    </button>

                    {selectMode && (
                        <>
                            <button
                                type="button"
                                onClick={() => setSelected(allSelected ? new Set() : new Set(items.map((item) => item.id)))}
                                className="btn-quiet text-xs py-1.5 px-2.5"
                            >
                                {allSelected ? <Circle size={13} /> : <CheckCircle2 size={13} />}
                                {allSelected ? 'clear all' : 'select page'}
                            </button>
                            <span className="readout">{selected.size} selected</span>

                            <select
                                value={pushVault}
                                onChange={(e) => setPushVault(e.target.value)}
                                className="input-field text-xs py-1.5 max-w-[10rem]"
                                aria-label="push to vault"
                            >
                                <option value="">push to…</option>
                                {connectedVaults.map((vault) => (
                                    <option key={vault.id} value={vault.id}>{vault.name}</option>
                                ))}
                            </select>
                            <button
                                type="button"
                                onClick={() => push(selectedItems)}
                                disabled={!selected.size || busy === 'push' || !connectedVaults.length}
                                className="btn-quiet text-xs py-1.5 px-2.5"
                            >
                                {busy === 'push' ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
                                push ({selected.size})
                            </button>
                            <button
                                type="button"
                                onClick={() => runAction('restore', selectedItems)}
                                disabled={!selected.size || busy === 'restore'}
                                className="btn-quiet text-xs py-1.5 px-2.5"
                            >
                                <Download size={13} /> restore
                            </button>
                            <button
                                type="button"
                                onClick={() => runAction('unarchive', selectedItems)}
                                disabled={!selected.size || busy === 'unarchive'}
                                className="btn-quiet text-xs py-1.5 px-2.5"
                            >
                                <ArrowLeft size={13} /> to gallery
                            </button>
                            <button
                                type="button"
                                onClick={() => setPendingDelete(selectedItems)}
                                disabled={!selected.size || deleting}
                                className="btn-quiet text-xs py-1.5 px-2.5 text-danger"
                            >
                                <Trash2 size={13} /> delete ({selected.size})
                            </button>
                        </>
                    )}

                    {loading && <span className="readout flex items-center gap-1.5"><Loader2 size={12} className="animate-spin" /> loading</span>}
                    <span className="ml-auto readout tabular-nums">
                        {total === 0 ? '0 clips' : `${firstShown}–${lastShown} of ${total}`} · page {page}/{pages || 1}
                    </span>
                </div>

                {/* ---- grid --------------------------------------------------- */}
                {items.length === 0 ? (
                    <div className="card p-10 text-center text-sm text-muted">
                        {filtersActive ? (
                            <>
                                <p className="mb-2 lowercase">No archived clips match these filters.</p>
                                <button type="button" onClick={resetFilters} className="btn-quiet text-xs py-1.5 px-2.5">reset filters</button>
                            </>
                        ) : (
                            <>
                                <p className="mb-2 lowercase">Nothing archived yet.</p>
                                <p>Open the Clip Gallery and press “archive” on a clip you are done with.</p>
                            </>
                        )}
                    </div>
                ) : (
                    <>
                        <div className={`grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-7 gap-2.5 sm:gap-3 pb-4 items-start transition-opacity ${loading ? 'opacity-60' : ''}`}>
                            {items.map((item) => {
                                const width = Number(item.poster_width);
                                const height = Number(item.poster_height);
                                const ratio = Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0
                                    ? `${width} / ${height}` : '9 / 16';
                                return (
                                    <div
                                        key={item.id}
                                        className={`card card-hover overflow-hidden group relative ${selected.has(item.id) ? 'ring-2 ring-[color:var(--color-accent)]' : ''}`}
                                    >
                                        <button
                                            type="button"
                                            onClick={() => (selectMode ? toggleSelected(item) : openItem(item))}
                                            className="block w-full text-left"
                                            aria-label={selectMode ? `Select ${item.title}` : `Open ${item.title}`}
                                        >
                                            <div className="relative bg-black overflow-hidden" style={{ aspectRatio: ratio }}>
                                                {item.poster ? (
                                                    <img src={getApiUrl(item.poster)} alt="" loading="lazy" decoding="async"
                                                        draggable={false} className="absolute inset-0 w-full h-full object-cover pointer-events-none" />
                                                ) : (
                                                    <div className="absolute inset-0 flex items-center justify-center text-white/30">
                                                        <Archive size={26} />
                                                    </div>
                                                )}
                                                <div className="absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-black/80 to-transparent" />
                                                <span className="absolute bottom-1.5 left-1.5 readout text-white/90">
                                                    {fmtDuration(item.duration)}
                                                </span>
                                                <span className={`absolute bottom-1.5 right-1.5 text-[9px] px-1 py-0.5 rounded bg-black/75 lowercase ${item.state === 'vaulted' ? 'text-white' : 'text-white/80'}`}>
                                                    {item.state === 'vaulted' ? 'vault' : item.state === 'local' ? 'local' : item.state === 'pushing' ? 'copying' : 'queued'}
                                                </span>
                                                {!item.playable && (
                                                    <span className="absolute top-1.5 left-1.5 text-[9px] px-1.5 py-0.5 rounded-full bg-black/80 text-white flex items-center gap-1">
                                                        <Unplug size={9} /> {item.state === 'vaulted' ? 'connect' : 'offline'}
                                                    </span>
                                                )}
                                                {selectMode ? (
                                                    <span className={`absolute top-1.5 right-1.5 w-5 h-5 rounded-full border flex items-center justify-center ${selected.has(item.id)
                                                        ? 'bg-[color:var(--color-accent)] border-[color:var(--color-accent)] text-paper'
                                                        : 'bg-black/50 border-white/60 text-transparent'}`}>
                                                        <CheckCircle2 size={12} />
                                                    </span>
                                                ) : item.playable ? (
                                                    <span className="absolute top-1.5 right-1.5 w-6 h-6 rounded-full bg-black/55 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                                                        <Play size={12} className="ml-0.5" />
                                                    </span>
                                                ) : null}
                                            </div>
                                            <div className="px-2 py-1.5">
                                                <p className="text-[11px] leading-snug text-ink line-clamp-2" title={item.title}>{item.title}</p>
                                                <div className="flex items-center justify-between mt-1 gap-1">
                                                    <span className={`readout truncate ${stateTone(item.state)}`} title={itemStateLabel(item)}>
                                                        {itemStateLabel(item)}
                                                    </span>
                                                    <span className="readout shrink-0">{fmtBytes(item.size_bytes)}</span>
                                                </div>
                                            </div>
                                        </button>

                                        {item.state === 'pushing' && (
                                            <div className="absolute inset-x-0 bottom-0 h-1 bg-paper3">
                                                <div className="h-full bg-brass transition-all" style={{ width: `${item.progress || 0}%` }} />
                                            </div>
                                        )}

                                        {!selectMode && (
                                            <div className="absolute top-1.5 right-1.5 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                                {item.playable && (
                                                    <a href={getApiUrl(`${item.video}?download=1`)} download
                                                        className="w-6 h-6 rounded-full bg-black/65 text-white/85 hover:text-white flex items-center justify-center"
                                                        title="Download this clip" aria-label={`Download ${item.title}`}>
                                                        <Download size={12} />
                                                    </a>
                                                )}
                                                <button
                                                    type="button"
                                                    onClick={(e) => { e.stopPropagation(); setPendingDelete([item]); }}
                                                    className="w-6 h-6 rounded-full bg-black/65 text-white/80 hover:text-danger hover:bg-black/85 flex items-center justify-center"
                                                    title="Delete this clip" aria-label={`Delete ${item.title}`}
                                                >
                                                    <Trash2 size={12} />
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>

                        {pages > 1 && (
                            <div className="flex flex-wrap items-center justify-center gap-1.5 py-6">
                                <button type="button" onClick={() => goToPage(page - 1)} disabled={page <= 1 || loading}
                                    className="btn-quiet text-xs py-1.5 px-2.5 flex items-center gap-1" aria-label="Previous page">
                                    <ChevronLeft size={13} /> prev
                                </button>
                                {pageList(page, pages).map((n, i) => (
                                    n === '…' ? (
                                        <span key={`gap-${i}`} className="readout px-1">…</span>
                                    ) : (
                                        <button key={n} type="button" onClick={() => goToPage(n)} disabled={loading}
                                            aria-current={n === page ? 'page' : undefined}
                                            className={`min-w-8 text-xs py-1.5 px-2 rounded-input tabular-nums transition-colors ${n === page ? 'bg-[color:var(--color-accent)] text-brassink' : 'btn-quiet'}`}>
                                            {n}
                                        </button>
                                    )
                                ))}
                                <button type="button" onClick={() => goToPage(page + 1)} disabled={page >= pages || loading}
                                    className="btn-quiet text-xs py-1.5 px-2.5 flex items-center gap-1" aria-label="Next page">
                                    next <ChevronRight size={13} />
                                </button>
                            </div>
                        )}
                    </>
                )}
            </div>

            {/* ---- player ---------------------------------------------------- */}
            <Modal
                isOpen={!!player}
                onClose={() => setPlayer(null)}
                eyebrow="ARCHIVED CLIP"
                title={player?.title}
                size="xl"
                layer="z-[120]"
            >
                {player && (
                    <div className="space-y-3">
                        {player.playable ? (
                            <video
                                key={player.id}
                                src={getApiUrl(player.video)}
                                controls
                                autoPlay
                                playsInline
                                className="w-full max-h-[66vh] bg-black rounded-card"
                            />
                        ) : (
                            <div className="rounded-card border border-rule bg-paper2 p-6 text-center space-y-3">
                                <Unplug size={28} className="mx-auto text-muted" />
                                <p className="text-sm text-ink">
                                    {player.state === 'vaulted'
                                        ? <>Connect the device that holds “{player.vault_name}”.</>
                                        : player.state === 'pending_delete'
                                            ? 'This clip is queued for deletion.'
                                            : 'This clip is not available right now.'}
                                </p>
                                <p className="text-xs text-muted">
                                    The card, poster and details stay here; the video plays again as
                                    soon as the vault is connected.
                                </p>
                                <button type="button" onClick={rescan} className="btn-quiet text-xs py-1.5 px-3">
                                    <RefreshCw size={13} /> rescan devices
                                </button>
                            </div>
                        )}

                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted">
                            <span>{fmtDuration(player.duration)}</span>
                            <span>{fmtBytes(player.size_bytes)}</span>
                            <span>{new Date(player.archived_at * 1000).toLocaleString()}</span>
                            <span className={stateTone(player.state)}>{itemStateLabel(player)}</span>
                            {(player.platforms?.youtube || player.platforms?.facebook) && (
                                <span>
                                    posted {player.platforms.youtube ? 'yt' : ''}
                                    {player.platforms.youtube && player.platforms.facebook ? ' + ' : ''}
                                    {player.platforms.facebook ? 'fb' : ''}
                                </span>
                            )}
                        </div>

                        {player.error && <p className="text-xs text-danger">{player.error}</p>}

                        <div className="flex flex-wrap items-center gap-2">
                            {player.state === 'vaulted' && (
                                <button type="button" onClick={() => runAction('restore', [player])}
                                    disabled={busy === 'restore'} className="btn-quiet text-xs py-1.5 px-2.5">
                                    <Download size={13} /> restore to this pc
                                </button>
                            )}
                            {(player.state === 'local'
                                || (player.state === 'vaulted' && player.vault_connected)) && (
                                <button type="button" onClick={() => runAction('unarchive', [player])}
                                    disabled={busy === 'unarchive'} className="btn-quiet text-xs py-1.5 px-2.5">
                                    <ArrowLeft size={13} /> return to gallery
                                </button>
                            )}
                            {connectedVaults.length > 0 && player.state === 'local' && (
                                <button type="button" onClick={() => push([player])}
                                    disabled={busy === 'push'} className="btn-quiet text-xs py-1.5 px-2.5">
                                    <Upload size={13} /> push to vault
                                </button>
                            )}
                            <button type="button" onClick={() => { setPendingDelete([player]); setPlayer(null); }}
                                className="btn-quiet text-xs py-1.5 px-2.5 text-danger ml-auto">
                                <Trash2 size={13} /> delete
                            </button>
                        </div>
                    </div>
                )}
            </Modal>

            {/* ---- delete confirmation -------------------------------------- */}
            <Modal
                isOpen={pendingDelete.length > 0}
                onClose={deleting ? undefined : () => setPendingDelete([])}
                eyebrow="DELETE"
                title={pendingDelete.length === 1 ? 'Delete this archived clip?' : `Delete ${pendingDelete.length} archived clips?`}
                size="sm"
                layer="z-[130]"
                footer={(
                    <div className="flex items-center justify-between gap-2">
                        <button type="button" onClick={() => setPendingDelete([])} disabled={deleting} className="btn-quiet text-xs py-1.5 px-2.5">
                            keep {pendingDelete.length === 1 ? 'it' : 'them'}
                        </button>
                        <button type="button" onClick={deleteClips} disabled={deleting} className="btn-danger text-xs py-1.5 px-2.5">
                            {deleting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                            {deleting ? 'deleting…' : 'delete permanently'}
                        </button>
                    </div>
                )}
            >
                <div className="space-y-3">
                    <div className="flex items-start gap-2.5 rounded-card border border-danger/40 bg-danger/5 p-3">
                        <AlertTriangle size={16} className="text-danger shrink-0 mt-0.5" />
                        <p className="text-xs leading-relaxed text-ink2">
                            The archived file and its poster are removed for good. A clip in a
                            disconnected vault is deleted automatically the next time that vault
                            is connected.
                        </p>
                    </div>
                    <ul className="space-y-1">
                        {pendingDelete.slice(0, 5).map((item) => (
                            <li key={item.id} className="text-xs text-ink2 truncate">{item.title}</li>
                        ))}
                        {pendingDelete.length > 5 && <li className="readout">+{pendingDelete.length - 5} more</li>}
                    </ul>
                </div>
            </Modal>

            {/* ---- vault picker --------------------------------------------- */}
            <Modal
                isOpen={!!picker}
                onClose={pickerBusy ? undefined : () => setPicker(null)}
                eyebrow="NEW VAULT"
                title="Choose a device folder"
                size="lg"
                layer="z-[130]"
            >
                {picker && (
                    <div className="space-y-4">
                        <p className="text-xs text-muted leading-relaxed">
                            Pick the root of the flash drive, external drive or SSD. The vault is one
                            file inside it; only the size you set is reserved, and the rest of the
                            device stays usable.
                        </p>

                        {!picker.path ? (
                            <div className="space-y-2">
                                <p className="eyebrow">devices</p>
                                <div className="grid gap-2 sm:grid-cols-2">
                                    {(picker.devices || []).map((device) => (
                                        <button
                                            key={device.path}
                                            type="button"
                                            onClick={() => browseTo(device.path)}
                                            className="card card-hover p-3 text-left flex items-center gap-3"
                                        >
                                            <HardDrive size={18} className="text-brass shrink-0" />
                                            <span className="min-w-0 flex-1">
                                                <span className="block text-sm text-ink truncate">{device.label}</span>
                                                <span className="readout block truncate">
                                                    {device.free_bytes == null ? device.path
                                                        : `${fmtBytes(device.free_bytes)} free of ${fmtBytes(device.total_bytes)}`}
                                                </span>
                                            </span>
                                            <ChevronRight size={14} className="text-muted shrink-0" />
                                        </button>
                                    ))}
                                </div>
                            </div>
                        ) : (
                            <div className="space-y-2">
                                <div className="flex flex-wrap items-center gap-2">
                                    <button type="button" onClick={() => setPicker({ ...picker, path: '' })} className="btn-quiet px-2 py-1 text-xs">
                                        <ArrowLeft size={12} /> devices
                                    </button>
                                    {picker.parent && (
                                        <button type="button" onClick={() => browseTo(picker.parent)} disabled={pickerBusy} className="btn-quiet px-2 py-1 text-xs">
                                            up
                                        </button>
                                    )}
                                    <span className="readout break-all min-w-0 flex-1">{picker.path}</span>
                                </div>
                                <div className="max-h-56 overflow-y-auto custom-scrollbar border border-rule rounded-card divide-y divide-rule">
                                    {(picker.directories || []).length === 0 ? (
                                        <p className="p-3 text-xs text-muted">No sub-folders here.</p>
                                    ) : picker.directories.map((directory) => (
                                        <button
                                            key={directory.path}
                                            type="button"
                                            onClick={() => browseTo(directory.path)}
                                            className="w-full flex items-center gap-2 px-3 py-2 text-left text-xs text-ink2 hover:bg-paper3"
                                        >
                                            <Folder size={13} className="text-brass shrink-0" />
                                            <span className="truncate">{directory.name}</span>
                                        </button>
                                    ))}
                                </div>
                                <p className="readout">
                                    {picker.free_bytes == null ? '' : `${fmtBytes(picker.free_bytes)} free here`}
                                </p>
                            </div>
                        )}

                        {picker.path && (
                            <div className="grid gap-3 sm:grid-cols-2">
                                <label>
                                    <span className="eyebrow block mb-1">vault name</span>
                                    <input
                                        type="text"
                                        value={vaultForm.name}
                                        onChange={(e) => setVaultForm((prev) => ({ ...prev, name: e.target.value }))}
                                        placeholder="Backup SSD"
                                        maxLength={60}
                                        className="input-field w-full text-sm"
                                    />
                                </label>
                                <label>
                                    <span className="eyebrow block mb-1">size (GB)</span>
                                    <input
                                        type="number"
                                        min="0.1"
                                        step="0.5"
                                        value={vaultForm.sizeGb}
                                        onChange={(e) => setVaultForm((prev) => ({ ...prev, sizeGb: e.target.value }))}
                                        className="input-field w-full text-sm"
                                    />
                                </label>
                            </div>
                        )}

                        <p className="text-[11px] text-muted leading-relaxed flex items-start gap-1.5">
                            <FolderOpen size={12} className="shrink-0 mt-0.5" />
                            Creating a vault writes its file out to the full size, so the space is
                            truly reserved. A large vault can take several minutes on a slow drive.
                        </p>

                        <div className="flex items-center justify-end gap-2">
                            <button type="button" onClick={() => setPicker(null)} disabled={pickerBusy} className="btn-quiet text-xs py-1.5 px-2.5">
                                cancel
                            </button>
                            <button
                                type="button"
                                onClick={createVault}
                                disabled={!picker.path || pickerBusy || !vaultForm.name.trim()}
                                className="btn-primary text-xs py-2 px-4"
                            >
                                {pickerBusy ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
                                create vault
                            </button>
                        </div>
                    </div>
                )}
            </Modal>
        </div>
    );
}
