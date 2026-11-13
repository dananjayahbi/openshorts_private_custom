import React, { useEffect, useRef } from 'react';
import { AlertTriangle, Loader2, Trash2 } from 'lucide-react';
import Modal from './ui/Modal';

// In-app confirmation for destructive gallery actions. `window.confirm` cannot
// be styled, looks nothing like the workbench, and some in-app browsers
// suppress it — a suppressed confirm returns false, so delete silently did
// nothing. This dialog names exactly what goes, keeps focus on "keep it", and
// sits above the clip player when delete is pressed inside it.
export default function ConfirmDeleteModal({
    open = false, clips = [], busy = false, error = '', onCancel, onConfirm,
}) {
    const cancelRef = useRef(null);

    useEffect(() => {
        if (!open) return undefined;
        // Escape closes this dialog only. The player underneath also listens
        // for Escape, so claim the key in the capture phase before it runs.
        const onKey = (e) => {
            if (e.key !== 'Escape') return;
            e.preventDefault();
            e.stopImmediatePropagation();
            if (!busy) onCancel?.();
        };
        window.addEventListener('keydown', onKey, true);
        const focus = window.setTimeout(() => cancelRef.current?.focus(), 0);
        return () => {
            window.clearTimeout(focus);
            window.removeEventListener('keydown', onKey, true);
        };
    }, [open, busy, onCancel]);

    if (!open || !clips.length) return null;

    const count = clips.length;
    const label = count === 1 ? `"${clips[0].title}"` : `${count} clips`;
    const named = clips.slice(0, 4);
    const more = count - named.length;

    return (
        <Modal
            isOpen
            onClose={busy ? undefined : onCancel}
            eyebrow="DELETE"
            title={count === 1 ? 'Delete this clip?' : `Delete ${count} clips?`}
            size="sm"
            layer="z-[140]"
            footer={(
                <div className="flex items-center justify-between gap-2">
                    <button
                        ref={cancelRef}
                        type="button"
                        onClick={onCancel}
                        disabled={busy}
                        className="btn-quiet text-xs py-1.5 px-2.5"
                    >
                        keep it
                    </button>
                    <button
                        type="button"
                        onClick={onConfirm}
                        disabled={busy}
                        className="btn-danger text-xs py-1.5 px-2.5"
                    >
                        {busy ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                        {busy ? 'deleting…' : count === 1 ? 'delete clip' : `delete ${count} clips`}
                    </button>
                </div>
            )}
        >
            <div className="space-y-3">
                <div className="flex items-start gap-2.5 rounded-card border border-danger/40 bg-danger/5 p-3">
                    <AlertTriangle size={16} className="text-danger shrink-0 mt-0.5" />
                    <p className="text-xs leading-relaxed text-ink2">
                        {label} and every rendered file for {count === 1 ? 'it' : 'them'} are
                        removed from disk. This cannot be undone.
                    </p>
                </div>

                <ul className="space-y-1">
                    {named.map((clip) => (
                        <li
                            key={`${clip.job_id}:${clip.index}`}
                            className="flex items-baseline gap-2 text-xs text-ink2"
                        >
                            <span className="readout shrink-0">#{clip.index + 1}</span>
                            <span className="min-w-0 truncate" title={clip.title}>{clip.title}</span>
                        </li>
                    ))}
                    {more > 0 && (
                        <li className="readout">+{more} more</li>
                    )}
                </ul>

                {error && <p className="text-micro text-danger" role="alert">{error}</p>}
            </div>
        </Modal>
    );
}
