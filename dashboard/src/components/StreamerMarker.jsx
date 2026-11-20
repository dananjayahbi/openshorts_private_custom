import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Crosshair, EyeOff, Pause, Play, RotateCcw, Trash2, X } from 'lucide-react';

// Draw the streamer's box on the ORIGINAL source, at its true aspect ratio.
// The rectangle is stored as fractions of the source frame, so the renderer can
// map it to the full-resolution source whatever the preview size was. The box's
// shape sets the split: the top panel keeps that aspect exactly and the viral
// clip takes the rest of the 9:16 frame. These bounds mirror streamer_layout.py.
//
// A second, independent box is the prevention area: the streamer's whole cam
// (or any overlay) that the bottom half must never show. It cannot reuse the
// streamer box, because that one is often only a zoom on the face while the
// whole cam is much bigger. The renderer slides the clip's crop around it.

const OUTPUT_ASPECT = 9 / 16;
const DEFAULT_MARKER_ASPECT = 9 / 8; // the classic even 50/50 split
const MIN_SHARE = 0.15;
const MAX_SHARE = 0.85;
const MIN_ASPECT = OUTPUT_ASPECT / MAX_SHARE; // ~0.66: a tall box
const MAX_ASPECT = OUTPUT_ASPECT / MIN_SHARE; // 3.75: a very wide box
const MIN_H = 0.08;
const MIN_W = 0.02;
const MIN_AVOID = 0.03; // an overlay strip can be thin, but not a click
const HANDLE = 14; // px, visual size of the bottom-right grip
const COMMON_RATIOS = [
    [16, 9], [9, 8], [4, 3], [3, 2], [16, 10], [5, 4], [1, 1], [21, 9], [9, 16],
];

const clamp = (value, lo, hi) => Math.min(hi, Math.max(lo, value));

const pixelAspect = (w, h, videoW, videoH) => {
    if (!videoW || !videoH || !w || !h) return DEFAULT_MARKER_ASPECT;
    return (w * videoW) / (h * videoH);
};

const aspectLabel = (aspect) => {
    const match = COMMON_RATIOS.find(([a, b]) => Math.abs(aspect - a / b) < 0.012);
    return match ? `${match[0]}:${match[1]}` : `${aspect.toFixed(2)}:1`;
};

// How much of the delivered height the box will take. The width is always the
// output width, so a panel of aspect r is (9/16)/r of the frame; clamped so
// neither panel can disappear.
const splitShare = (aspect) => clamp(OUTPUT_ASPECT / aspect, MIN_SHARE, MAX_SHARE);

const defaultRect = (videoW, videoH) => {
    // A person-sized box: 45% of the source height, the classic 9:8 shape.
    const ratio = (DEFAULT_MARKER_ASPECT * videoH) / videoW; // wNorm / hNorm
    const h = 0.45;
    const w = Math.min(0.9, h * ratio);
    return { x: (1 - w) / 2, y: 0.12, w, h };
};

// The prevention area is free-form: its only job is to cover what must not be
// shown, so no aspect is enforced.
const freeShape = (w, h, maxW, maxH) => ({
    w: clamp(w, MIN_AVOID, maxW),
    h: clamp(h, MIN_AVOID, maxH),
});

export default function StreamerMarker({
    open, src, title, initialRect, initialAvoid, initialMode, onSave, onClose,
}) {
    const [rect, setRect] = useState(initialRect || null);
    const [avoid, setAvoid] = useState(initialAvoid || null);
    const [mode, setMode] = useState(initialMode === 'avoid' ? 'avoid' : 'streamer');
    const [size, setSize] = useState({ w: 0, h: 0 });
    const [error, setError] = useState('');
    const [playing, setPlaying] = useState(true);
    const [drag, setDrag] = useState(null);
    const boxRef = useRef(null);
    const videoRef = useRef(null);

    const aspect = rect
        ? pixelAspect(rect.w, rect.h, size.w, size.h)
        : DEFAULT_MARKER_ASPECT;
    const share = splitShare(aspect);

    useEffect(() => {
        if (!open) return;
        setError('');
        setRect(initialRect || null);
        setAvoid(initialAvoid || null);
        setMode(initialMode === 'avoid' ? 'avoid' : 'streamer');
    }, [open, initialRect, initialAvoid, initialMode]);

    useEffect(() => {
        if (!open) return;
        const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
        window.addEventListener('keydown', onKey);
        const previous = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            window.removeEventListener('keydown', onKey);
            document.body.style.overflow = previous;
        };
    }, [open, onClose]);

    // First open (or no saved box): start with a plausible centred marker.
    useEffect(() => {
        if (open && !rect && size.w && size.h) setRect(defaultRect(size.w, size.h));
    }, [open, rect, size]);

    const point = useCallback((event) => {
        const box = boxRef.current?.getBoundingClientRect();
        if (!box || !box.width || !box.height) return { x: 0, y: 0 };
        return {
            x: clamp((event.clientX - box.left) / box.width, 0, 1),
            y: clamp((event.clientY - box.top) / box.height, 0, 1),
        };
    }, []);

    // Keep the box's pixel aspect inside the range the renderer supports, then
    // shrink it to the space left without distorting it.
    const shape = useCallback((w, h, maxW, maxH) => {
        let width = clamp(w, MIN_W, maxW);
        let height = clamp(h, MIN_H, maxH);
        if (!size.w || !size.h) return { w: width, h: height };

        const raw = pixelAspect(width, height, size.w, size.h);
        const ratio = clamp(raw, MIN_ASPECT, MAX_ASPECT);
        if (raw > MAX_ASPECT) {
            width = (ratio * height * size.h) / size.w;
        } else if (raw < MIN_ASPECT) {
            height = (width * size.w) / (ratio * size.h);
        }
        if (width < MIN_W) {
            width = MIN_W;
            height = Math.min(maxH, (width * size.w) / (ratio * size.h));
        }
        const fit = Math.min(1, maxW / width, maxH / height);
        return { w: width * fit, h: height * fit };
    }, [size]);

    // Pointer-down on a box starts moving it; its handle resizes it; the video
    // background draws a new box for whichever mode is active.
    const startDrag = (target, kind, event, startRect = null) => {
        event.preventDefault();
        event.stopPropagation();
        setMode(target);
        setDrag({ target, kind, start: point(event), rect0: startRect || null });
    };

    useEffect(() => {
        if (!drag) return undefined;
        const setBox = drag.target === 'avoid' ? setAvoid : setRect;
        const constrain = drag.target === 'avoid'
            ? freeShape
            : shape;
        const onMove = (event) => {
            const p = point(event);
            if (drag.kind === 'move' && drag.rect0) {
                const base = drag.rect0;
                setBox({
                    ...base,
                    x: clamp(base.x + (p.x - drag.start.x), 0, 1 - base.w),
                    y: clamp(base.y + (p.y - drag.start.y), 0, 1 - base.h),
                });
                return;
            }
            if (drag.kind === 'resize' && drag.rect0) {
                const base = drag.rect0;
                const next = constrain(
                    p.x - base.x,
                    p.y - base.y,
                    1 - base.x,
                    1 - base.y,
                );
                setBox({ ...base, ...next });
                return;
            }
            // New box: the drag's bounding box is the box. For the streamer crop
            // its aspect comes from the gesture itself, so any cam shape can be
            // marked; the prevention area keeps whatever shape is drawn.
            const x0 = Math.min(drag.start.x, p.x);
            const y0 = Math.min(drag.start.y, p.y);
            const next = constrain(
                Math.abs(p.x - drag.start.x),
                Math.abs(p.y - drag.start.y),
                Math.max(0.001, 1 - x0),
                Math.max(0.001, 1 - y0),
            );
            const min = drag.target === 'avoid'
                ? [MIN_AVOID, MIN_AVOID]
                : [MIN_W, MIN_H];
            if (next.w < min[0] || next.h < min[1]) return;
            setBox({ x: x0, y: y0, ...next });
        };
        const onUp = () => setDrag(null);
        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
        window.addEventListener('pointercancel', onUp);
        return () => {
            window.removeEventListener('pointermove', onMove);
            window.removeEventListener('pointerup', onUp);
            window.removeEventListener('pointercancel', onUp);
        };
    }, [drag, point, shape]);

    const togglePlay = () => {
        const video = videoRef.current;
        if (!video) return;
        if (video.paused) video.play().catch(() => {});
        else video.pause();
        setPlaying(!video.paused);
    };

    if (!open) return null;

    const boxStyle = (value) => ({
        left: `${value.x * 100}%`,
        top: `${value.y * 100}%`,
        width: `${value.w * 100}%`,
        height: `${value.h * 100}%`,
    });

    return (
        <div
            className="fixed inset-0 z-[140] bg-black/90 backdrop-blur-sm flex items-center justify-center p-0 sm:p-6 animate-fade"
            onClick={onClose}
            role="dialog"
            aria-modal="true"
            aria-label="Mark the streamer box"
        >
            <div
                className="w-full h-full sm:h-auto sm:max-h-[94vh] sm:max-w-6xl bg-paper border-0 sm:border border-rule sm:rounded-card overflow-hidden flex flex-col"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-start justify-between gap-3 px-4 sm:px-5 py-3 border-b border-rule">
                    <div className="min-w-0">
                        <p className="eyebrow mb-1">streamed video</p>
                        <h2 className="text-sm font-medium text-ink truncate">
                            Mark the streamer&apos;s box
                        </h2>
                        <p className="text-[11px] text-muted mt-1">
                            Two separate boxes. The <span className="text-brass">streamer box</span> is the
                            crop shown on top, and its shape sets the split (16:9 takes about a third of the
                            frame, 9:8 is the even 50/50). The <span className="text-danger">prevent area</span>{' '}
                            is the streamer&apos;s full cam or overlay — the clip&apos;s half is framed
                            around it, so it never shows there. Pick which one you are drawing with the
                            chips below, then drag to draw, drag inside to move, or use the bottom-right
                            handle to resize. While a box is active the other one is only a reference.
                            {title ? <> Source: <span className="text-ink2">{title}</span>.</> : null}
                        </p>
                    </div>
                    <button type="button" onClick={onClose} className="btn-quiet p-2 shrink-0" aria-label="Close">
                        <X size={16} />
                    </button>
                </div>

                <div className="bg-black flex items-center justify-center min-h-0 p-2 sm:p-4">
                    <div
                        ref={boxRef}
                        className="relative inline-block select-none touch-none cursor-crosshair"
                        onPointerDown={(e) => startDrag(mode, 'new', e)}
                    >
                        <video
                            ref={videoRef}
                            src={src}
                            autoPlay
                            muted
                            loop
                            playsInline
                            className="block max-h-[62vh] sm:max-h-[68vh] max-w-full"
                            onLoadedMetadata={(e) => {
                                const v = e.currentTarget;
                                setSize({ w: v.videoWidth || 0, h: v.videoHeight || 0 });
                                setPlaying(!v.paused);
                            }}
                            onPlay={() => setPlaying(true)}
                            onPause={() => setPlaying(false)}
                        />
                        <div className="absolute inset-0 overflow-hidden">
                            {/* What a drag on the video draws right now. The boxes
                                are separate selections, so the inactive one is a
                                reference only: it never takes the pointer (a drag
                                over the streamer box in prevent mode still draws
                                the prevent area, it does not move the streamer
                                box). Swim between them with the chips below. */}
                            <div
                                className="pointer-events-none absolute left-1/2 top-2 z-30 -translate-x-1/2 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-medium shadow-lg"
                                style={mode === 'avoid'
                                    ? { background: 'var(--color-danger)', color: '#fff' }
                                    : { background: 'var(--color-accent)', color: '#000' }}
                            >
                                {mode === 'avoid'
                                    ? 'drawing prevent area · kept out of the clip'
                                    : 'drawing streamer box · shown on top'}
                            </div>
                            {avoid && (
                                <div
                                    role="presentation"
                                    data-box="avoid"
                                    className={`absolute border-2 border-danger bg-danger/10 ${mode === 'avoid'
                                        ? 'cursor-move border-solid'
                                        : 'pointer-events-none border-dashed opacity-70'}`}
                                    style={{ ...boxStyle(avoid), zIndex: mode === 'avoid' ? 20 : 10 }}
                                    onPointerDown={(e) => startDrag('avoid', 'move', e, avoid)}
                                >
                                    <span className="absolute -top-6 left-0 whitespace-nowrap rounded bg-danger px-1.5 py-0.5 text-[10px] text-white font-medium">
                                        prevent · not in the clip
                                    </span>
                                    <span
                                        role="presentation"
                                        className="absolute rounded-sm bg-danger"
                                        style={{ width: HANDLE, height: HANDLE, right: -HANDLE / 2, bottom: -HANDLE / 2, cursor: 'nwse-resize' }}
                                        onPointerDown={(e) => startDrag('avoid', 'resize', e, avoid)}
                                    />
                                </div>
                            )}
                            {rect && (
                                <div
                                    role="presentation"
                                    data-box="streamer"
                                    className={`absolute border-2 border-brass bg-brass/10 ${mode === 'streamer'
                                        ? 'cursor-move shadow-[0_0_0_9999px_rgba(0,0,0,0.45)]'
                                        : 'pointer-events-none border-dashed opacity-70'}`}
                                    style={{ ...boxStyle(rect), zIndex: mode === 'streamer' ? 20 : 10 }}
                                    onPointerDown={(e) => startDrag('streamer', 'move', e, rect)}
                                >
                                    <span className="absolute -top-6 left-0 whitespace-nowrap rounded bg-brass px-1.5 py-0.5 text-[10px] text-black font-medium">
                                        streamer {aspectLabel(aspect)}
                                    </span>
                                    <span
                                        role="presentation"
                                        className="absolute rounded-sm bg-brass"
                                        style={{ width: HANDLE, height: HANDLE, right: -HANDLE / 2, bottom: -HANDLE / 2, cursor: 'nwse-resize' }}
                                        onPointerDown={(e) => startDrag('streamer', 'resize', e, rect)}
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                </div>

                <div className="flex flex-wrap items-center gap-2 px-4 sm:px-5 py-3 border-t border-rule">
                    <button type="button" onClick={togglePlay} className="btn-quiet text-xs py-1.5 px-2.5">
                        {playing ? <Pause size={13} /> : <Play size={13} />}
                        {playing ? 'pause' : 'play'}
                    </button>
                    <div className="flex items-center gap-1 rounded-full border border-rule p-0.5" role="group" aria-label="Which box to edit">
                        <button
                            type="button"
                            onClick={() => setMode('streamer')}
                            aria-pressed={mode === 'streamer'}
                            className={`rounded-full px-2.5 py-1 text-[11px] ${mode === 'streamer' ? 'bg-brass text-black font-medium' : 'text-muted'}`}
                        >
                            streamer box
                        </button>
                        <button
                            type="button"
                            onClick={() => setMode('avoid')}
                            aria-pressed={mode === 'avoid'}
                            className={`rounded-full px-2.5 py-1 text-[11px] ${mode === 'avoid' ? 'bg-danger text-white font-medium' : 'text-muted'}`}
                        >
                            prevent area
                        </button>
                    </div>
                    {mode === 'streamer' && (
                        <button
                            type="button"
                            onClick={() => size.w && setRect(defaultRect(size.w, size.h))}
                            className="btn-quiet text-xs py-1.5 px-2.5"
                        >
                            <RotateCcw size={13} /> reset streamer box
                        </button>
                    )}
                    {mode === 'avoid' && rect && (
                        <button
                            type="button"
                            onClick={() => setAvoid({ ...rect })}
                            className="btn-quiet text-xs py-1.5 px-2.5"
                        >
                            <EyeOff size={13} /> copy streamer box
                        </button>
                    )}
                    {avoid && (
                        <button
                            type="button"
                            onClick={() => setAvoid(null)}
                            className="btn-quiet text-xs py-1.5 px-2.5"
                        >
                            <Trash2 size={13} /> clear prevent area
                        </button>
                    )}
                    <span className="readout text-[11px] text-muted">
                        {size.w && size.h ? `${size.w}x${size.h}` : 'reading video...'}
                        {rect && size.w && size.h
                            ? ` · split ${Math.round(share * 100)}% / ${100 - Math.round(share * 100)}%`
                            : ''}
                        {rect ? ' · streamer box set' : ' · streamer box missing'}
                        {avoid ? ' · prevent area set' : ' · prevent area not marked'}
                    </span>
                    {mode === 'avoid' && !avoid && !error && (
                        <span className="text-[11px] text-[var(--color-warn)]">
                            draw the cam/overlay on the video to add the prevent area
                        </span>
                    )}
                    {error && <span className="text-[11px] text-danger" role="alert">{error}</span>}
                    <div className="ml-auto flex items-center gap-2">
                        <button type="button" onClick={onClose} className="btn-quiet text-xs py-1.5 px-3">
                            cancel
                        </button>
                        <button
                            type="button"
                            disabled={!rect}
                            onClick={() => {
                                if (!rect) {
                                    setError('Draw a box on the video first.');
                                    return;
                                }
                                onSave?.(rect, avoid);
                            }}
                            className="btn-primary text-xs py-1.5 px-3"
                        >
                            <Crosshair size={13} /> save boxes
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
