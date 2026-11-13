import React from 'react';
import {
    Archive, CheckCircle2, Play, Trash2,
} from 'lucide-react';

// A compact gallery tile: the video is only a poster (no controls, no inline
// playback — clicking opens the full-viewport player). Everything editorial
// (title/caption/tags/platforms/archive/delete) lives in that modal, so a page
// of clips stays scannable and small.

const scoreTone = (score) => {
    const n = Number(score);
    if (!Number.isFinite(n)) return 'bg-black/70 text-white';
    if (n >= 80) return 'bg-ok/25 text-ok';
    if (n >= 60) return 'bg-[color:var(--color-accent)]/25 text-brass';
    return 'bg-black/70 text-white';
};

export default function GalleryCard({
    clip, selectMode = false, selected = false, onToggleSelect, onOpen, onDelete,
}) {
    const platforms = clip.platforms || {};
    const onAnyPlatform = !!(platforms.facebook || platforms.youtube);

    const activate = () => {
        if (selectMode) onToggleSelect?.(clip);
        else onOpen?.(clip);
    };

    return (
        <div
            className={`card card-hover overflow-hidden group animate-fade relative ${selected ? 'ring-2 ring-[color:var(--color-accent)]' : ''} ${clip.archived ? 'opacity-70 hover:opacity-100' : ''}`}
        >
            <button
                type="button"
                onClick={activate}
                aria-label={selectMode ? `Select ${clip.title}` : `Open ${clip.title}`}
                className="block w-full text-left"
            >
                <div className="relative aspect-square bg-black overflow-hidden">
                    {/* A poster, not a player: metadata only, no controls. The
                        #t fragment makes the browser paint a frame instead of
                        the first black frame some captures start on. */}
                    <video
                        src={`${clip.url}#t=0.1`}
                        preload="metadata"
                        muted
                        playsInline
                        tabIndex={-1}
                        aria-hidden="true"
                        className="w-full h-full object-cover pointer-events-none"
                    />

                    <div className="absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-black/80 to-transparent" />

                    {Number.isFinite(Number(clip.score)) && (
                        <span className={`absolute top-1.5 left-1.5 readout px-1.5 py-0.5 rounded-full ${scoreTone(clip.score)}`}>
                            {Math.round(Number(clip.score))}
                        </span>
                    )}

                    <span className="absolute bottom-1.5 left-1.5 readout text-white/90">
                        {clip.duration.toFixed(1)}s
                    </span>

                    <div className="absolute bottom-1.5 right-1.5 flex items-center gap-1">
                        {platforms.facebook && (
                            <span className="text-[9px] px-1 py-0.5 rounded bg-black/75 text-white lowercase">fb</span>
                        )}
                        {platforms.youtube && (
                            <span className="text-[9px] px-1 py-0.5 rounded bg-black/75 text-white lowercase">yt</span>
                        )}
                        {clip.archived && (
                            <span className="text-[9px] px-1 py-0.5 rounded bg-black/75 text-white lowercase flex items-center gap-0.5">
                                <Archive size={9} /> ar
                            </span>
                        )}
                        {clip.used && !onAnyPlatform && (
                            <span className="text-[9px] px-1 py-0.5 rounded bg-[color:var(--color-accent)] text-paper lowercase flex items-center gap-0.5">
                                <CheckCircle2 size={9} /> used
                            </span>
                        )}
                    </div>

                    {selectMode ? (
                        <span className={`absolute top-1.5 right-1.5 w-5 h-5 rounded-full border flex items-center justify-center ${selected
                            ? 'bg-[color:var(--color-accent)] border-[color:var(--color-accent)] text-paper'
                            : 'bg-black/50 border-white/60 text-transparent'}`}
                        >
                            <CheckCircle2 size={12} />
                        </span>
                    ) : (
                        <span className="absolute top-1.5 right-1.5 w-6 h-6 rounded-full bg-black/55 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                            <Play size={12} className="ml-0.5" />
                        </span>
                    )}
                </div>

                <div className="px-2 py-1.5">
                    <p className="text-[11px] leading-snug text-ink line-clamp-2" title={clip.title}>
                        {clip.title}
                    </p>
                    <div className="flex items-center justify-between mt-1">
                        <span className="readout">{new Date(clip.created_at).toLocaleDateString()}</span>
                        <span className="readout truncate max-w-[55%]" title={clip.job_id}>
                            {clip.job_id.slice(0, 8)}
                        </span>
                    </div>
                </div>
            </button>

            {!selectMode && (
                <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); onDelete?.(clip); }}
                    className="absolute top-1.5 right-1.5 w-6 h-6 rounded-full bg-black/65 text-white/80 hover:text-danger hover:bg-black/85 items-center justify-center hidden group-hover:flex"
                    title="Delete this clip from disk"
                    aria-label={`Delete ${clip.title}`}
                >
                    <Trash2 size={12} />
                </button>
            )}
        </div>
    );
}
