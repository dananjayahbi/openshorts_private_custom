import React, { useEffect, useMemo, useState } from 'react';
import {
    AlertTriangle, CheckCircle2, ChevronDown, Clock, ExternalLink, LayoutGrid,
    Loader2, RefreshCw, Terminal, X,
} from 'lucide-react';

const LABELS = {
    waiting: 'waiting',
    submitting: 'submitting',
    running: 'processing',
    done: 'done',
    failed: 'failed',
    cancelled: 'cancelled',
};

const TERMINAL_STATES = new Set(['done', 'failed', 'cancelled']);

const StateIcon = ({ state }) => {
    if (state === 'done') return <CheckCircle2 size={15} className="text-ok" />;
    if (state === 'failed') return <AlertTriangle size={15} className="text-danger" />;
    if (state === 'running' || state === 'submitting') return <Loader2 size={15} className="text-brass animate-spin" />;
    if (state === 'cancelled') return <X size={15} className="text-muted" />;
    return <Clock size={15} className="text-muted" />;
};

const elapsed = (row, now) => {
    if (!row.startedAt) return '';
    const end = row.finishedAt || now;
    const s = Math.max(0, Math.round((end - row.startedAt) / 1000));
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    return `${m}m ${String(s % 60).padStart(2, '0')}s`;
};

// One terminal per video: the batch used to say only "processing" and, on a
// failure, not why. The line the pipeline printed is the diagnosis ("AI
// provider returned an empty body", "no audio", "download failed"), so each
// row keeps the same log tail the single-job screen shows.
const RowLogs = ({ row }) => (
    <div className="mx-3 sm:mx-4 mb-3 rounded-input border border-rule bg-paper px-3 py-2.5 max-h-48 overflow-y-auto overscroll-contain custom-scrollbar font-mono text-[11px] leading-relaxed">
        {(row.logs || []).length === 0 ? (
            <p className="text-muted">
                {row.state === 'waiting' ? 'Waiting for its turn…' : 'No output yet.'}
            </p>
        ) : (
            (row.logs || []).map((line, i) => (
                <div
                    key={i}
                    className={`flex gap-2 ${/error|failed|traceback/i.test(line) ? 'text-danger' : 'text-muted'}`}
                >
                    <span className="shrink-0 tabular-nums opacity-50 hidden sm:inline">
                        {row.logTimes?.[i]
                            ? new Date(row.logTimes[i] * 1000).toLocaleTimeString()
                            : ''}
                    </span>
                    <span className="min-w-0 break-words">{line}</span>
                </div>
            ))
        )}
        {row.state === 'running' && <div className="animate-pulse text-brass">_</div>}
    </div>
);

export default function BatchQueue({ batch, onCancel, onOpenGallery, onRetryFailed, onDismiss }) {
    const rows = batch?.rows || [];
    const running = !!batch?.running;
    const [open, setOpen] = useState({});
    const [now, setNow] = useState(Date.now());

    const done = rows.filter((r) => TERMINAL_STATES.has(r.state)).length;
    const ok = rows.filter((r) => r.state === 'done').length;
    const failed = rows.filter((r) => r.state === 'failed' || r.state === 'cancelled').length;
    const pct = rows.length ? Math.round((done / rows.length) * 100) : 0;
    const runningIndex = rows.findIndex((r) => r.state === 'running' || r.state === 'submitting');

    // Keep the row that is working expanded: its log is the live progress.
    useEffect(() => {
        if (runningIndex < 0) return;
        const key = rows[runningIndex]?.key;
        if (!key) return;
        setOpen((prev) => (prev[key] ? prev : { ...prev, [key]: true }));
    }, [runningIndex, rows]);

    useEffect(() => {
        if (!running) return undefined;
        const id = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(id);
    }, [running]);

    const toggle = (key) => setOpen((prev) => ({ ...prev, [key]: !prev[key] }));
    const failedCount = useMemo(
        () => rows.filter((r) => r.state === 'failed' || r.state === 'cancelled').length,
        [rows],
    );

    return (
        <div className="h-full overflow-y-auto overscroll-contain custom-scrollbar">
            <div className="w-full px-3 sm:px-6 py-4 sm:py-6">
                <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                    <div>
                        <p className="eyebrow mb-1">bulk mode</p>
                        <h1 className="text-xl sm:text-2xl font-semibold">
                            {running ? 'Processing your queue' : 'Queue finished'}
                        </h1>
                        <p className="text-sm text-muted mt-1">
                            {done} of {rows.length} finished{ok !== done ? ` · ${done - ok} failed` : ''}.
                            {' '}Each video is processed one at a time.
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        {running && (
                            <button type="button" onClick={onCancel} className="btn-quiet text-xs py-1.5 px-2.5">
                                <X size={13} /> stop
                            </button>
                        )}
                        {!running && failedCount > 0 && (
                            <button type="button" onClick={onRetryFailed} className="btn-quiet text-xs py-1.5 px-2.5">
                                <RefreshCw size={13} /> retry failed ({failedCount})
                            </button>
                        )}
                        <button type="button" onClick={onOpenGallery} className="btn-quiet text-xs py-1.5 px-2.5">
                            <LayoutGrid size={13} /> clip gallery
                        </button>
                        {!running && (
                            <button type="button" onClick={onDismiss} className="btn-primary text-xs py-1.5 px-2.5">
                                new batch
                            </button>
                        )}
                    </div>
                </div>

                <div className="card p-3 sm:p-4 mb-4">
                    <div className="h-1.5 rounded-full bg-paper3 overflow-hidden">
                        <div
                            className="h-full bg-[color:var(--color-accent)] transition-[width] duration-500"
                            style={{ width: `${pct}%` }}
                        />
                    </div>
                    <div className="flex items-center justify-between mt-2">
                        <p className="readout">{pct}%</p>
                        <p className="readout normal-case text-muted">
                            {failed ? `${failed} failed` : 'queue healthy'}
                        </p>
                    </div>
                </div>

                <div className="card divide-y divide-rule overflow-hidden">
                    {rows.map((row, i) => {
                        const key = row.key || String(i);
                        const isOpen = !!open[key];
                        const lastLine = [...(row.logs || [])].reverse().find((l) => l && String(l).trim());
                        return (
                            <div key={key}>
                                <div className="flex items-center gap-2.5 px-3 sm:px-4 py-3">
                                    <span className="readout w-7 shrink-0">{String(i + 1).padStart(2, '0')}</span>
                                    <StateIcon state={row.state} />
                                    <button
                                        type="button"
                                        onClick={() => toggle(key)}
                                        aria-expanded={isOpen}
                                        className="min-w-0 flex-1 text-left group"
                                        title={isOpen ? 'Hide this video’s log' : 'Show this video’s log'}
                                    >
                                        <p className="text-sm truncate group-hover:text-brass transition-colors" title={row.label}>
                                            {row.label}
                                        </p>
                                        {row.error ? (
                                            <p className="text-[11px] text-danger line-clamp-2" title={row.error}>{row.error}</p>
                                        ) : (!isOpen && lastLine ? (
                                            <p className="text-[11px] text-muted truncate" title={String(lastLine)}>
                                                {String(lastLine)}
                                            </p>
                                        ) : null)}
                                    </button>
                                    {row.startedAt && (
                                        <span className="readout shrink-0 hidden sm:inline">{elapsed(row, now)}</span>
                                    )}
                                    <span className="text-[11px] text-muted shrink-0">{LABELS[row.state] || row.state}</span>
                                    <button
                                        type="button"
                                        onClick={() => toggle(key)}
                                        className="p-1 text-muted hover:text-ink transition-colors shrink-0"
                                        aria-label={isOpen ? 'Hide log' : 'Show log'}
                                    >
                                        <ChevronDown size={15} className={isOpen ? 'rotate-180' : ''} />
                                    </button>
                                    {row.jobId && (
                                        <a
                                            href={`#app?tab=gallery`}
                                            className="text-muted hover:text-brass shrink-0"
                                            title={`Open the clip gallery (job ${row.jobId})`}
                                        >
                                            <ExternalLink size={14} />
                                        </a>
                                    )}
                                </div>
                                {isOpen && <RowLogs row={row} />}
                            </div>
                        );
                    })}
                </div>

                <p className="text-[11px] text-muted mt-3 flex items-center gap-1.5">
                    <Terminal size={11} /> Click a video to open its log. Clips from every finished job are
                    in the Clip Gallery; you can leave this page while the batch runs.
                </p>
            </div>
        </div>
    );
}
