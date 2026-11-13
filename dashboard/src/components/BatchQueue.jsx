import React from 'react';
import {
    AlertTriangle, CheckCircle2, Clock, ExternalLink, LayoutGrid, Loader2, X,
} from 'lucide-react';

const LABELS = {
    waiting: 'waiting',
    submitting: 'submitting',
    running: 'processing',
    done: 'done',
    failed: 'failed',
    cancelled: 'cancelled',
};

const StateIcon = ({ state }) => {
    if (state === 'done') return <CheckCircle2 size={15} className="text-ok" />;
    if (state === 'failed') return <AlertTriangle size={15} className="text-danger" />;
    if (state === 'running' || state === 'submitting') return <Loader2 size={15} className="text-brass animate-spin" />;
    if (state === 'cancelled') return <X size={15} className="text-muted" />;
    return <Clock size={15} className="text-muted" />;
};

export default function BatchQueue({ batch, onCancel, onOpenGallery, onDismiss }) {
    const rows = batch?.rows || [];
    const done = rows.filter((r) => r.state === 'done' || r.state === 'failed' || r.state === 'cancelled').length;
    const ok = rows.filter((r) => r.state === 'done').length;
    const running = !!batch?.running;
    const pct = rows.length ? Math.round((done / rows.length) * 100) : 0;

    return (
        <div className="h-full overflow-y-auto custom-scrollbar">
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
                                <X size={13} /> stop after this video
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
                    <p className="readout mt-2">{pct}%</p>
                </div>

                <div className="card divide-y divide-rule overflow-hidden">
                    {rows.map((row, i) => (
                        <div key={row.key || i} className="flex items-center gap-3 px-3 sm:px-4 py-3">
                            <span className="readout w-7 shrink-0">{String(i + 1).padStart(2, '0')}</span>
                            <StateIcon state={row.state} />
                            <div className="min-w-0 flex-1">
                                <p className="text-sm truncate" title={row.label}>{row.label}</p>
                                {row.error && (
                                    <p className="text-[11px] text-danger line-clamp-2" title={row.error}>{row.error}</p>
                                )}
                            </div>
                            <span className="text-[11px] text-muted shrink-0">{LABELS[row.state] || row.state}</span>
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
                    ))}
                </div>

                <p className="text-[11px] text-muted mt-3">
                    Clips from every finished job are in the Clip Gallery. You can leave this
                    page while the batch runs; it keeps going in this browser tab.
                </p>
            </div>
        </div>
    );
}
