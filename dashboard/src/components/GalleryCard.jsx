import React, { useRef, useState, useEffect } from 'react';
import {
    Download, Copy, Check, Play, CheckCircle2, Circle, Archive, ArchiveRestore,
    Loader2,
} from 'lucide-react';
import { getApiUrl } from '../config';

export default function GalleryCard({ clip, onChanged }) {
    const [copied, setCopied] = useState(null);
    const [isVisible, setIsVisible] = useState(false);
    const [_hasLoaded, setHasLoaded] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    // The card used to hardcode 9:16 and crop everything else. The real ratio
    // arrives with the first metadata event; until then 9:16 is the pipeline's
    // default for vertical output.
    const [aspect, setAspect] = useState('9 / 16');
    const cardRef = useRef(null);
    const videoRef = useRef(null);

    // Lazy loading with IntersectionObserver
    useEffect(() => {
        const observer = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        setIsVisible(true);
                        // Once loaded, we don't need to observe anymore
                        observer.unobserve(entry.target);
                    }
                });
            },
            {
                rootMargin: '200px', // Start loading 200px before entering viewport
                threshold: 0.1
            }
        );

        const node = cardRef.current;
        if (node) {
            observer.observe(node);
        }

        return () => {
            if (node) {
                observer.unobserve(node);
            }
        };
    }, []);

    const handleCopy = (text, field) => {
        navigator.clipboard.writeText(text);
        setCopied(field);
        setTimeout(() => setCopied(null), 2000);
    };

    const handleDownload = async (e) => {
        e.preventDefault();
        try {
            const response = await fetch(clip.url);
            if (!response.ok) throw new Error('Download failed');
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = `clip_${clip.job_id}_${clip.index + 1}.mp4`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (err) {
            console.error('Download error:', err);
            window.open(clip.url, '_blank');
        }
    };

    const patchClip = async (patch) => {
        setBusy(true);
        setError('');
        try {
            const res = await fetch(getApiUrl(`/api/gallery/clip/${clip.job_id}/${clip.index}`), {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(patch),
            });
            if (!res.ok) throw new Error((await res.text()).slice(0, 200) || `HTTP ${res.status}`);
            const flags = await res.json();
            onChanged?.(clip, flags);
        } catch (e) {
            setError(String(e.message || e).slice(0, 200));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div
            ref={cardRef}
            className={`card card-hover overflow-hidden flex flex-col group animate-fade ${clip.archived ? 'opacity-70 hover:opacity-100' : ''}`}
        >
            {/* Video Player - Lazy loaded. The box follows the clip's own ratio:
                vertical 9:16, square and 16:9 outputs were being cropped. */}
            <div className="bg-black relative group/video" style={{ aspectRatio: aspect }}>
                {isVisible ? (
                    <video
                        ref={videoRef}
                        src={clip.url}
                        controls
                        className="w-full h-full object-cover"
                        playsInline
                        preload="metadata"
                        onLoadedMetadata={(e) => {
                            const { videoWidth, videoHeight } = e.target;
                            if (videoWidth && videoHeight) setAspect(`${videoWidth} / ${videoHeight}`);
                        }}
                        onLoadedData={() => setHasLoaded(true)}
                    />
                ) : (
                    <div className="w-full h-full flex items-center justify-center bg-paper absolute inset-0">
                        <div className="w-12 h-12 rounded-full bg-paper3 flex items-center justify-center">
                            <Play size={24} className="text-muted ml-1" />
                        </div>
                    </div>
                )}
                <div className="absolute top-2 left-2">
                    <span className="readout bg-black/70 px-2 py-1 rounded-full">
                        {new Date(clip.created_at).toLocaleDateString()}
                    </span>
                </div>
                <div className="absolute top-2 right-2 flex flex-col items-end gap-1">
                    {clip.archived ? (
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-black/75 text-white lowercase flex items-center gap-1">
                            <Archive size={10} /> archived
                        </span>
                    ) : clip.used ? (
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[color:var(--color-accent)] text-paper lowercase flex items-center gap-1">
                            <CheckCircle2 size={10} /> used
                        </span>
                    ) : null}
                </div>
            </div>

            {/* Content & Details */}
            <div className="flex-1 p-4 flex flex-col min-w-0">
                <div className="mb-3">
                    <h3 className="text-sm font-semibold text-ink leading-tight line-clamp-2 mb-2 break-words" title={clip.title}>
                        {clip.title}
                    </h3>
                    <div className="flex flex-wrap gap-2">
                        <span className="readout bg-paper3 px-1.5 py-0.5 rounded-full">{clip.duration.toFixed(1)}s</span>
                        <span className="readout bg-paper3 px-1.5 py-0.5 rounded-full truncate max-w-[150px]" title={clip.job_id}>ID: {clip.job_id.substring(0, 8)}</span>
                    </div>
                </div>

                <div className="space-y-2 flex-1 overflow-y-auto custom-scrollbar max-h-[150px] pr-1 mb-3">
                    {/* YouTube Title */}
                    <div className="bg-paper rounded-input p-2 relative group/item">
                        <p className="eyebrow mb-1">YouTube Title</p>
                        <p className="text-xs text-ink2 select-all line-clamp-2 hover:line-clamp-none transition-all">{clip.title}</p>
                        <button
                            onClick={() => handleCopy(clip.title, 'yt')}
                            className="absolute top-2 right-2 p-1 text-muted hover:text-brass transition-colors opacity-0 group-hover/item:opacity-100"
                            title="Copy Title"
                        >
                            {copied === 'yt' ? <Check size={12} className="text-ok" /> : <Copy size={12} />}
                        </button>
                    </div>

                    {/* TikTok / IG Caption */}
                    <div className="bg-paper rounded-input p-2 relative group/item">
                        <p className="eyebrow mb-1">TikTok · IG Caption</p>
                        <p className="text-xs text-ink2 select-all line-clamp-3 hover:line-clamp-none transition-all cursor-pointer">
                            {clip.tiktok_desc || clip.insta_desc}
                        </p>
                        <button
                            onClick={() => handleCopy(clip.tiktok_desc || clip.insta_desc, 'caption')}
                            className="absolute top-2 right-2 p-1 text-muted hover:text-brass transition-colors opacity-0 group-hover/item:opacity-100"
                            title="Copy Caption"
                        >
                            {copied === 'caption' ? <Check size={12} className="text-ok" /> : <Copy size={12} />}
                        </button>
                    </div>
                </div>

                {error && <p className="text-[11px] text-danger mb-2" role="alert">{error}</p>}

                {/* Footer actions: mark posted, archive, download */}
                <div className="flex items-center gap-1.5">
                    <button
                        onClick={() => patchClip({ used: !clip.used })}
                        disabled={busy || clip.archived}
                        className={`btn-quiet flex-1 text-xs py-1.5 px-2 ${clip.used ? 'text-brass' : ''}`}
                        title={clip.used ? 'Mark as not used' : 'Mark as used (already posted)'}
                    >
                        {busy ? <Loader2 size={13} className="animate-spin" />
                            : clip.used ? <CheckCircle2 size={13} /> : <Circle size={13} />}
                        {clip.used ? 'used' : 'mark used'}
                    </button>
                    <button
                        onClick={() => patchClip({ archived: !clip.archived })}
                        disabled={busy}
                        className="btn-quiet text-xs py-1.5 px-2"
                        title={clip.archived ? 'Restore to the library' : 'Archive (hide from the library, keep the file)'}
                    >
                        {clip.archived ? <ArchiveRestore size={13} /> : <Archive size={13} />}
                        {clip.archived ? 'restore' : 'archive'}
                    </button>
                    <button
                        onClick={handleDownload}
                        className="btn-quiet text-xs py-1.5 px-2"
                        title="Download clip"
                    >
                        <Download size={13} />
                    </button>
                </div>
            </div>
        </div>
    );
}
