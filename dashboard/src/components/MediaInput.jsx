import React, { useState, useEffect, useRef } from 'react';
import { Link2, Upload, FileVideo, X, Info, Loader2, ChevronDown, Layers, ListPlus, Film } from 'lucide-react';
import { track } from '../lib/analytics';
import { apiFetch } from '../lib/api';
import { getApiUrl } from '../config';
import SourceCost from './SourceCost';
import CollectorPicker from './CollectorPicker';
import CaptionControls from './CaptionControls';
import CaptionStage from './CaptionStage';
import { DEFAULT_CAPTION_STYLE, presetToStyle } from '../lib/captionStyles';

const SUPPORTED_PLATFORMS = [
    'YouTube', 'Vimeo', 'TikTok', 'X / Twitter', 'Twitch', 'Kick',
    'Facebook', 'Instagram', 'Dailymotion', 'Reddit', 'Streamable',
];

// Mirrors the server's MIN_SOURCE_SECONDS: shorter sources are rejected with a
// 400 after the whole file was uploaded. Checking the duration in the browser
// says so the moment the file is picked (a 27 s upload used to end in a bare
// "That run failed").
const MIN_SOURCE_SECONDS = 45;

// Duration of a local video file in seconds, or null when the browser cannot
// read it (unsupported codec): then the server stays the judge.
const readVideoDuration = (file) => new Promise((resolve) => {
    try {
        const url = URL.createObjectURL(file);
        const v = document.createElement('video');
        v.preload = 'metadata';
        const done = (d) => { URL.revokeObjectURL(url); resolve(d); };
        v.onloadedmetadata = () => done(Number.isFinite(v.duration) ? v.duration : null);
        v.onerror = () => done(null);
        setTimeout(() => done(null), 8000);
        v.src = url;
    } catch { resolve(null); }
});

const fileKey = (f) => `${f.name}:${f.size}:${f.lastModified}`;

export default function MediaInput({ onProcess, onProcessBatch, isProcessing, initialCollector, onInitialCollectorUsed, initialProfile, onInitialProfileUsed }) {
    const [youtubeUrlEnabled, setYoutubeUrlEnabled] = useState(true);
    // File upload is the primary path; the link and the collector are next.
    const [mode, setMode] = useState('file'); // 'file' | 'url' | 'collector'
    // Bulk mode: the same source tab, but N videos submitted one after another.
    const [bulk, setBulk] = useState(false);
    const [url, setUrl] = useState('');
    const [urlsText, setUrlsText] = useState('');
    const [files, setFiles] = useState([]);
    const [durations, setDurations] = useState({});
    const [picked, setPicked] = useState([]);
    const [pickerOpen, setPickerOpen] = useState(false);
    const [acknowledged, setAcknowledged] = useState(false);
    // {start, end} in seconds when the user picked a stretch under the cost line.
    const [range, setRange] = useState(null);
    const [outputFormat, setOutputFormat] = useState('vertical'); // vertical | horizontal | square
    const [showInfo, setShowInfo] = useState(false);
    // Advanced generation controls — empty string means "let the AI decide",
    // which keeps the default pipeline behavior untouched.
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [targetClips, setTargetClips] = useState('');
    const [clipMinSeconds, setClipMinSeconds] = useState('');
    const [clipMaxSeconds, setClipMaxSeconds] = useState('');
    // Auto-hook: burn the AI hook text into every clip. On by default; the
    // choice persists so turning it off sticks across sessions.
    const [autoHook, setAutoHook] = useState(() => {
        try { return localStorage.getItem('os_auto_hook') !== '0'; } catch { return true; }
    });
    const [autoHookStyle, setAutoHookStyle] = useState(() => {
        // v2 key: the default became 'pill'; an old saved 'classic' was just the old default.
        try { return localStorage.getItem('os_auto_hook_style_v2') || 'pill'; } catch { return 'pill'; }
    });
    // Layout: 'auto' lets the AI pick per video (server default); the others
    // force one on so a podcast host who knows what they uploaded doesn't
    // depend on the detector, and 'none' keeps the plain single crop.
    const [layout, setLayout] = useState(() => {
        try { return localStorage.getItem('os_layout') || 'auto'; } catch { return 'auto'; }
    });
    const [queuedCount, setQueuedCount] = useState(0);
    const [queueError, setQueueError] = useState('');
    // Pre-generation caption look + the profile it came from. The look is
    // sent to /api/process, so captions are styled before the render instead
    // of only after it.
    const [captionStyle, setCaptionStyle] = useState(() => {
        try {
            const saved = JSON.parse(localStorage.getItem('os_caption_style') || 'null');
            return saved ? { ...DEFAULT_CAPTION_STYLE, ...saved } : presetToStyle(null);
        } catch { return presetToStyle(null); }
    });
    const [captionsOn, setCaptionsOn] = useState(() => {
        try { return localStorage.getItem('os_captions') !== '0'; } catch { return true; }
    });
    const [profiles, setProfiles] = useState([]);
    const [styleProfileId, setStyleProfileId] = useState(() => {
        try { return localStorage.getItem('os_style_profile') || ''; } catch { return ''; }
    });
    const infoRef = useRef(null);
    const fileInput = useRef(null);

    const singleFile = files[0] || null;
    const fileSeconds = singleFile ? durations[fileKey(singleFile)] ?? null : null;
    const fileTooShort = fileSeconds != null && fileSeconds < MIN_SOURCE_SECONDS;
    const bulkUrls = urlsText.split('\n').map((s) => s.trim()).filter(Boolean);
    const shortFiles = bulk
        ? files.filter((f) => durations[fileKey(f)] != null && durations[fileKey(f)] < MIN_SOURCE_SECONDS)
        : [];

    // Close the compatibility popover on any outside click.
    useEffect(() => {
        if (!showInfo) return;
        const onClick = (e) => {
            if (infoRef.current && !infoRef.current.contains(e.target)) setShowInfo(false);
        };
        document.addEventListener('mousedown', onClick);
        return () => document.removeEventListener('mousedown', onClick);
    }, [showInfo]);

    // Duration for every picked file (the first one also drives the cost line).
    useEffect(() => {
        let cancelled = false;
        setDurations((prev) => {
            const next = { ...prev };
            for (const f of files) {
                if (!(fileKey(f) in next)) next[fileKey(f)] = null;
            }
            return next;
        });
        (async () => {
            for (const f of files) {
                const key = fileKey(f);
                if (durations[key] !== undefined && durations[key] !== null) continue;
                const d = await readVideoDuration(f);
                if (cancelled) return;
                setDurations((prev) => ({ ...prev, [key]: d }));
                if (d != null && d < MIN_SOURCE_SECONDS) {
                    track('SourceTooShort', { props: { seconds: String(Math.round(d)) } });
                }
            }
        })();
        return () => { cancelled = true; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [files]);

    useEffect(() => {
        fetch(getApiUrl('/api/config'))
            .then((r) => r.ok ? r.json() : null)
            .then((cfg) => {
                if (cfg && cfg.youtubeUrlEnabled === false) {
                    setYoutubeUrlEnabled(false);
                    setMode('file');
                }
            })
            .catch(() => {});
    }, []);

    // A Collector card's "Process" opens this page with its video already
    // selected. Applied once per handover (the same item can be handed over
    // twice by clicking Process again).
    const appliedPrefillRef = useRef(null);
    useEffect(() => {
        const incoming = initialCollector?.item;
        if (!incoming) {
            appliedPrefillRef.current = null;
            return;
        }
        if (appliedPrefillRef.current === incoming.id) return;
        appliedPrefillRef.current = incoming.id;
        setBulk(false);
        setMode('collector');
        setPicked([incoming]);
        onInitialCollectorUsed?.();
    }, [initialCollector, onInitialCollectorUsed]);

    // A Style Profile's "use" hands its look/options to this page. Applied once
    // per handover; every control stays editable afterwards.
    const applyProfile = (profile) => {
        if (!profile) return;
        setStyleProfileId(profile.id);
        setCaptionStyle({ ...DEFAULT_CAPTION_STYLE, ...(profile.caption || {}) });
        const output = profile.output || {};
        if (output.output_format) setOutputFormat(output.output_format);
        if (Array.isArray(output.layouts) && output.layouts.length) setLayout(output.layouts[0]);
        if (typeof output.auto_hook === 'boolean') setAutoHook(output.auto_hook);
        if (output.auto_hook_style) setAutoHookStyle(output.auto_hook_style);
        if (output.target_clips) setTargetClips(String(output.target_clips));
        if (output.clip_min_seconds) setClipMinSeconds(String(output.clip_min_seconds));
        if (output.clip_max_seconds) setClipMaxSeconds(String(output.clip_max_seconds));
    };

    useEffect(() => {
        apiFetch('/api/style-profiles')
            .then((r) => (r.ok ? r.json() : { profiles: [] }))
            .then((d) => setProfiles(d.profiles || []))
            .catch(() => { /* profiles are optional */ });
    }, []);

    const appliedProfileRef = useRef(null);
    useEffect(() => {
        const incoming = initialProfile?.profile;
        if (!incoming) {
            appliedProfileRef.current = null;
            return;
        }
        if (appliedProfileRef.current === incoming.id) return;
        appliedProfileRef.current = incoming.id;
        applyProfile(incoming);
        onInitialProfileUsed?.();
    }, [initialProfile, onInitialProfileUsed]);

    // A link pasted in the landing hero: preload it here so the user picks up
    // where they left off. Not auto-submitted — the rights attestation below
    // has to be ticked by the user.
    useEffect(() => {
        let pending = null;
        try {
            pending = localStorage.getItem('os_pending_url');
            if (pending) localStorage.removeItem('os_pending_url');
        } catch { /* ignore */ }
        if (pending) {
            setMode('url');
            setUrl(pending);
        }
    }, []);

    // The collector queue lives in the backend; refresh the count on arrival
    // and after any bulk switch so the button tells the truth.
    const refreshQueue = async () => {
        try {
            const res = await apiFetch('/api/collector');
            if (!res.ok) return;
            const data = await res.json();
            setQueuedCount((data.items || []).filter((i) => i.queued).length);
        } catch { /* the count is cosmetic */ }
    };
    useEffect(() => { refreshQueue(); }, [mode, bulk]);

    const advanced = () => ({
        targetClips: targetClips || null,
        clipMinSeconds: clipMinSeconds || null,
        clipMaxSeconds: clipMaxSeconds || null,
        autoHook,
        autoHookStyle,
        layout,
        sourceStart: range ? Math.round(range.start) : null,
        sourceEnd: range ? Math.round(range.end) : null,
        captionStyle,
        captions: captionsOn,
        styleProfileId: styleProfileId || null,
    });

    const rememberOptions = () => {
        try {
            localStorage.setItem('os_auto_hook', autoHook ? '1' : '0');
            localStorage.setItem('os_auto_hook_style_v2', autoHookStyle);
            localStorage.setItem('os_layout', layout);
            localStorage.setItem('os_caption_style', JSON.stringify(captionStyle));
            localStorage.setItem('os_captions', captionsOn ? '1' : '0');
            localStorage.setItem('os_style_profile', styleProfileId || '');
        } catch { /* ignore */ }
    };

    const setBulkMode = (next) => {
        setBulk(next);
        if (!next) {
            setFiles((prev) => prev.slice(0, 1));
            setPicked((prev) => prev.slice(0, 1));
        }
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        if (!acknowledged) return;
        rememberOptions();
        const options = advanced();

        if (bulk) {
            let items = [];
            if (mode === 'url') {
                items = bulkUrls.map((u) => ({ type: 'url', payload: u, label: u }));
            } else if (mode === 'file') {
                items = files.map((f) => ({ type: 'file', payload: f, label: f.name }));
            } else {
                items = picked.map((i) => ({ type: 'collector', payload: i.id, label: i.title }));
            }
            if (!items.length) return;
            onProcessBatch?.({ items, outputFormat, acknowledged: true, ...options });
            return;
        }

        if (mode === 'url' && url) {
            onProcess({ type: 'url', payload: url, acknowledged: true, outputFormat, ...options });
        } else if (mode === 'file' && singleFile && !fileTooShort) {
            onProcess({ type: 'file', payload: singleFile, acknowledged: true, outputFormat, ...options });
        } else if (mode === 'collector' && picked[0]) {
            onProcess({ type: 'collector', payload: picked[0].id, acknowledged: true, outputFormat, ...options });
        }
    };

    const startQueue = async () => {
        setQueueError('');
        try {
            const res = await apiFetch('/api/collector');
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();
            const queued = (data.items || []).filter((i) => i.queued);
            if (!queued.length) {
                setQueueError('The queue is empty. Add videos to it on the Collector page.');
                return;
            }
            if (!acknowledged) {
                setQueueError('Tick the rights confirmation below first.');
                return;
            }
            rememberOptions();
            onProcessBatch?.({
                items: queued.map((i) => ({ type: 'collector', payload: i.id, label: i.title })),
                outputFormat,
                acknowledged: true,
                ...advanced(),
            });
        } catch (e) {
            setQueueError(String(e.message || e).slice(0, 240));
        }
    };

    const addFiles = (list) => {
        const incoming = Array.from(list || []).filter((f) => f && f.type.startsWith('video/'));
        if (!incoming.length) return;
        setFiles((prev) => (bulk ? [...prev, ...incoming] : [incoming[0]]));
        setMode('file');
    };

    const removeFile = (index) => {
        setFiles((prev) => prev.filter((_, i) => i !== index));
    };

    const canSubmit = acknowledged && (
        (mode === 'url' && (bulk ? bulkUrls.length > 0 : !!url))
        || (mode === 'file' && (bulk ? files.length > 0 : (!!singleFile && !fileTooShort)))
        || (mode === 'collector' && picked.length > 0)
    );

    return (
        <div className="card p-4 sm:p-6 animate-fade">
            {/* Bulk switch: one toggle for all three source tabs. */}
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                <p className="text-sm text-ink2">
                    {bulk ? 'Bulk mode: several videos are processed one by one.' : 'Single video'}
                </p>
                <label className="flex items-center gap-2 text-xs text-muted cursor-pointer select-none">
                    <input
                        type="checkbox"
                        checked={bulk}
                        onChange={(e) => setBulkMode(e.target.checked)}
                        className="w-4 h-4 accent-[var(--color-accent)] cursor-pointer"
                    />
                    bulk mode
                </label>
            </div>

            <div className="flex gap-4 sm:gap-6 mb-6 border-b border-rule overflow-x-auto" data-tutorial="source-tabs">
                <button
                    onClick={() => setMode('file')}
                    className={`flex items-center gap-2 pb-3 px-1 -mb-px border-b-2 text-sm lowercase whitespace-nowrap transition-colors ${mode === 'file'
                        ? 'text-ink border-brass'
                        : 'text-muted border-transparent hover:text-ink2'
                        }`}
                >
                    <Upload size={16} className={`hidden sm:block ${mode === 'file' ? 'text-brass' : ''}`} />
                    Upload File
                </button>
                {youtubeUrlEnabled && (
                    <button
                        onClick={() => setMode('url')}
                        className={`flex items-center gap-2 pb-3 px-1 -mb-px border-b-2 text-sm lowercase whitespace-nowrap transition-colors ${mode === 'url'
                            ? 'text-ink border-brass'
                            : 'text-muted border-transparent hover:text-ink2'
                            }`}
                    >
                        <Link2 size={16} className={`hidden sm:block ${mode === 'url' ? 'text-brass' : ''}`} />
                        Video URL
                    </button>
                )}
                <button
                    onClick={() => setMode('collector')}
                    className={`flex items-center gap-2 pb-3 px-1 -mb-px border-b-2 text-sm lowercase whitespace-nowrap transition-colors ${mode === 'collector'
                        ? 'text-ink border-brass'
                        : 'text-muted border-transparent hover:text-ink2'
                        }`}
                >
                    <Layers size={16} className={`hidden sm:block ${mode === 'collector' ? 'text-brass' : ''}`} />
                    Collector
                </button>
            </div>

            <form onSubmit={handleSubmit}>
                {mode === 'url' ? (
                    <div className="space-y-4" data-tutorial="drop-zone">
                        {bulk ? (
                            <div>
                                <textarea
                                    value={urlsText}
                                    onChange={(e) => setUrlsText(e.target.value)}
                                    placeholder={'One video link per line\nhttps://youtu.be/...\nhttps://...'}
                                    rows={5}
                                    className="input-field font-mono text-xs leading-relaxed resize-y"
                                />
                                <p className="readout mt-2">{bulkUrls.length} link(s) queued for this batch</p>
                            </div>
                        ) : (
                            <div className="relative">
                                <input
                                    type="url"
                                    value={url}
                                    onChange={(e) => setUrl(e.target.value)}
                                    placeholder="https://... paste a video link"
                                    className="input-field pr-11"
                                    required
                                />
                                <div className="absolute inset-y-0 right-2 flex items-center" ref={infoRef}>
                                    <button
                                        type="button"
                                        onClick={() => setShowInfo((v) => !v)}
                                        aria-label="Supported platforms"
                                        className="p-1.5 text-muted hover:text-brass transition-colors"
                                    >
                                        <Info size={16} />
                                    </button>
                                    {showInfo && (
                                        <div className="absolute right-0 top-full mt-2 w-64 z-20 card p-4 text-left animate-fade">
                                            <p className="eyebrow mb-2">Paste a link from</p>
                                            <div className="flex flex-wrap gap-1.5">
                                                {SUPPORTED_PLATFORMS.map((p) => (
                                                    <span key={p} className="text-xs px-2 py-0.5 rounded-full bg-paper3 text-ink2">
                                                        {p}
                                                    </span>
                                                ))}
                                            </div>
                                            <p className="text-xs text-muted mt-2.5 leading-relaxed">
                                                …and 1,000+ more sites. If a link has a public video, we can usually fetch it.
                                            </p>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                ) : mode === 'collector' ? (
                    <div className="space-y-3" data-tutorial="drop-zone">
                        <div className="flex flex-wrap items-center gap-2">
                            <button
                                type="button"
                                onClick={() => setPickerOpen(true)}
                                className="btn-quiet text-xs py-2 px-3"
                            >
                                <Layers size={14} /> {bulk ? 'select from collector gallery' : 'select from collector gallery'}
                            </button>
                            {queuedCount > 0 && (
                                <button
                                    type="button"
                                    onClick={startQueue}
                                    className="btn-primary text-xs py-2 px-3"
                                    title="Process every queued video, one at a time"
                                >
                                    <ListPlus size={14} /> process queue ({queuedCount})
                                </button>
                            )}
                        </div>
                        {picked.length === 0 ? (
                            <div className="border-2 border-dashed border-rule2 rounded-card p-6 sm:p-8 text-center">
                                <Film size={18} className="mx-auto mb-2 text-muted" />
                                <p className="text-ink2 lowercase">no video selected</p>
                                <p className="readout mt-2">
                                    Open the gallery to pick {bulk ? 'one or more videos' : 'a video'}.
                                </p>
                            </div>
                        ) : (
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                {picked.map((item, i) => (
                                    <div key={item.id} className="flex items-center gap-2 p-2 rounded-input border border-rule2 bg-paper2 min-w-0">
                                        {item.thumbnail ? (
                                            <img src={getApiUrl(item.thumbnail)} alt="" className="w-14 h-9 rounded object-cover shrink-0" />
                                        ) : (
                                            <div className="w-14 h-9 rounded bg-paper3 flex items-center justify-center shrink-0 text-muted">
                                                <Film size={14} />
                                            </div>
                                        )}
                                        <p className="text-xs truncate flex-1" title={item.title}>{item.title}</p>
                                        <button
                                            type="button"
                                            onClick={() => setPicked((prev) => prev.filter((_, idx) => idx !== i))}
                                            className="p-1 text-muted hover:text-ink shrink-0"
                                            aria-label="Remove from selection"
                                        >
                                            <X size={14} />
                                        </button>
                                    </div>
                                ))}
                            </div>
                        )}
                        {queueError && <p className="text-xs text-danger" role="alert">{queueError}</p>}
                    </div>
                ) : (
                    <div
                        data-tutorial="drop-zone"
                        className={`border-2 border-dashed rounded-card p-6 sm:p-8 text-center transition-colors ${files.length ? 'border-brass' : 'border-rule2 hover:border-brass'
                            }`}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={(e) => { e.preventDefault(); addFiles(e.dataTransfer.files); }}
                    >
                        {files.length > 0 && (
                            <div className="space-y-2 mb-4 text-left">
                                {files.map((f, i) => (
                                    <div key={fileKey(f)} className="flex items-center justify-center gap-2 text-ok min-w-0">
                                        <FileVideo size={16} className="shrink-0" />
                                        <span className="text-sm font-medium truncate">{f.name}</span>
                                        {bulk && (
                                            <button
                                                type="button"
                                                onClick={() => removeFile(i)}
                                                className="p-1 text-muted hover:text-ink hover:bg-paper3 rounded-full transition-colors shrink-0"
                                                aria-label={`Remove ${f.name}`}
                                            >
                                                <X size={14} />
                                            </button>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                        {!bulk && singleFile && fileTooShort ? (
                            <p className="text-danger text-sm mt-3" role="alert">
                                This video is {Math.round(fileSeconds)}s long. Clip generation needs at least {MIN_SOURCE_SECONDS}s
                                of footage to cut from: it already is a short. Pick a longer video.
                            </p>
                        ) : null}
                        {shortFiles.length > 0 && (
                            <p className="text-danger text-xs mt-2" role="alert">
                                {shortFiles.length} file(s) are shorter than {MIN_SOURCE_SECONDS}s and will fail:
                                {' '}{shortFiles.map((f) => f.name).join(', ')}
                            </p>
                        )}
                        <input
                            ref={fileInput}
                            type="file"
                            accept="video/*"
                            multiple={bulk}
                            onChange={(e) => addFiles(e.target.files)}
                            className="hidden"
                        />
                        <button
                            type="button"
                            onClick={() => fileInput.current?.click()}
                            className={files.length ? 'btn-quiet text-xs py-2 px-3 mt-2' : 'block w-full'}
                        >
                            <Upload className={`mx-auto mb-2 text-muted ${files.length ? 'hidden' : ''}`} size={18} />
                            <span className={files.length ? '' : 'text-ink2 lowercase'}>
                                {files.length ? `add ${bulk ? 'more files' : 'another file'}` : 'Click to upload or drag and drop'}
                            </span>
                            {!files.length && (
                                <span className="readout block mt-2">
                                    MP4, MOV up to {bulk ? '2 GB each' : '500MB'} · at least {MIN_SOURCE_SECONDS}s long
                                </span>
                            )}
                        </button>
                    </div>
                )}

                {!bulk && mode !== 'collector' && (
                    <SourceCost
                        mode={mode}
                        url={url}
                        fileSeconds={fileSeconds}
                        range={range}
                        onRangeChange={setRange}
                    />
                )}

                {/* Output format selector */}
                <div className="mt-5" data-tutorial="output-format">
                    <p className="eyebrow mb-2">Output format</p>
                    <div className="grid grid-cols-3 gap-2">
                        {[
                            { value: 'vertical', label: '9:16', hint: 'Shorts · Reels · TikTok', w: 18, h: 32 },
                            { value: 'square', label: '1:1', hint: 'Feed posts', w: 28, h: 28 },
                            { value: 'horizontal', label: '16:9', hint: 'Keep landscape · YouTube', w: 36, h: 20 },
                        ].map((f) => {
                            const active = outputFormat === f.value;
                            return (
                                <button
                                    key={f.value}
                                    type="button"
                                    onClick={() => setOutputFormat(f.value)}
                                    className={`py-3 px-2 rounded-input border flex flex-col items-center gap-2 transition-colors
                                        ${active ? 'border-[color:var(--color-accent)] text-ink' : 'border-rule2 text-muted hover:border-[color:var(--color-accent)]'}`}
                                >
                                    {/* Aspect-ratio glyph */}
                                    <span
                                        className="rounded-[3px] border-2 transition-colors"
                                        style={{
                                            width: `${f.w}px`,
                                            height: `${f.h}px`,
                                            borderColor: active ? 'var(--color-accent)' : 'var(--color-rule-2)',
                                            backgroundColor: active ? 'color-mix(in srgb, var(--color-accent) 22%, transparent)' : 'transparent',
                                        }}
                                    />
                                    <span className="block font-mono text-sm leading-none">{f.label}</span>
                                    <span className="block text-[11px] sm:text-[10px] leading-tight text-center text-muted">{f.hint}</span>
                                </button>
                            );
                        })}
                    </div>
                </div>

                {/* Style profile + captions: visible without opening advanced,
                    because the whole point is choosing the look BEFORE the
                    render. A profile can still be tweaked below. */}
                <div className="mt-4 grid sm:grid-cols-2 gap-3">
                    <label className="block">
                        <span className="eyebrow">style profile</span>
                        <select
                            value={styleProfileId}
                            onChange={(e) => {
                                const id = e.target.value;
                                if (!id) {
                                    setStyleProfileId('');
                                    return;
                                }
                                const profile = profiles.find((p) => p.id === id);
                                if (profile) applyProfile(profile);
                            }}
                            className="input-field mt-1 text-sm"
                        >
                            <option value="">custom / shipped default</option>
                            {profiles.map((p) => (
                                <option key={p.id} value={p.id}>{p.name}</option>
                            ))}
                        </select>
                    </label>
                    <label className="flex items-center gap-2 text-xs text-ink2 sm:mt-5 cursor-pointer select-none">
                        <input
                            type="checkbox"
                            checked={captionsOn}
                            onChange={(e) => setCaptionsOn(e.target.checked)}
                            className="w-4 h-4 shrink-0 accent-[var(--color-accent)] cursor-pointer"
                        />
                        burn captions into the clips
                    </label>
                </div>

                {/* Advanced generation controls — collapsed by default; blank = AI decides */}
                <div className="mt-4">
                    <button
                        type="button"
                        onClick={() => setShowAdvanced((v) => !v)}
                        className="flex items-center gap-1.5 text-xs text-muted hover:text-ink2 lowercase transition-colors"
                    >
                        <ChevronDown size={14} className={`transition-transform ${showAdvanced ? 'rotate-180' : ''}`} />
                        advanced options
                        {(targetClips || clipMinSeconds || clipMaxSeconds || !autoHook) && (
                            <span className="text-brass">·</span>
                        )}
                    </button>
                    {showAdvanced && (
                        /* Stacked on a phone: three number fields side by side leaves
                           ~100px each, which crushes both label and value. */
                        <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-2 animate-fade">
                            <div>
                                <p className="eyebrow mb-1.5">clips to aim for</p>
                                <input
                                    type="number" min="1" max="15" step="1"
                                    value={targetClips}
                                    onChange={(e) => setTargetClips(e.target.value)}
                                    placeholder="auto"
                                    className="input-field"
                                />
                            </div>
                            <div>
                                <p className="eyebrow mb-1.5">min length (s)</p>
                                <input
                                    type="number" min="5" max="175" step="1"
                                    value={clipMinSeconds}
                                    onChange={(e) => setClipMinSeconds(e.target.value)}
                                    placeholder="15"
                                    className="input-field"
                                />
                            </div>
                            <div>
                                <p className="eyebrow mb-1.5">max length (s)</p>
                                <input
                                    type="number" min="10" max="180" step="1"
                                    value={clipMaxSeconds}
                                    onChange={(e) => setClipMaxSeconds(e.target.value)}
                                    placeholder="60"
                                    className="input-field"
                                />
                            </div>
                            <p className="col-span-1 sm:col-span-3 text-[11px] leading-relaxed text-muted">
                                Targets, not guarantees: the AI returns fewer clips when the
                                material doesn't hold them. Leave blank to let it decide.
                            </p>
                            <div className="col-span-1 sm:col-span-3 flex flex-wrap items-center justify-between gap-3 pt-3 sm:pt-1 border-t border-rule">
                                <span className="text-xs text-ink2">vertical layout</span>
                                <select
                                    value={layout}
                                    onChange={(e) => setLayout(e.target.value)}
                                    className="input-field !w-auto text-xs py-1.5"
                                    aria-label="vertical layout"
                                >
                                    <option value="auto">Auto (AI picks per video)</option>
                                    <option value="split">Two speakers stacked</option>
                                    <option value="screencast">Screen over presenter</option>
                                    <option value="none">Single crop only</option>
                                </select>
                            </div>
                            <div className="col-span-1 sm:col-span-3 flex flex-wrap items-center justify-between gap-3 pt-3 sm:pt-1 border-t border-rule">
                                <label className="flex items-center gap-2 text-xs text-ink2 cursor-pointer select-none">
                                    <input
                                        type="checkbox"
                                        checked={autoHook}
                                        onChange={(e) => setAutoHook(e.target.checked)}
                                        className="w-4 h-4 shrink-0 accent-[var(--color-accent)] cursor-pointer"
                                    />
                                    auto hook titles on clips
                                </label>
                                {autoHook && (
                                    <select
                                        value={autoHookStyle}
                                        onChange={(e) => setAutoHookStyle(e.target.value)}
                                        className="input-field !w-auto text-xs py-1.5"
                                    >
                                        <option value="pill">Pills</option>
                                        <option value="classic">Classic</option>
                                        <option value="dark">Dark</option>
                                        <option value="yellow">Yellow</option>
                                        <option value="red">Red</option>
                                        <option value="outline">Outline</option>
                                        <option value="outline_yellow">Outline+</option>
                                    </select>
                                )}
                                {autoHook && (
                                    <p className="w-full text-[11px] leading-relaxed text-muted">
                                        You can change each clip&apos;s hook text, style, position and size
                                        afterwards with its hook button.
                                    </p>
                                )}
                            </div>
                            <div className="col-span-1 sm:col-span-3 pt-3 border-t border-rule space-y-3">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <span className="text-xs text-ink2">captions &amp; style</span>
                                    <span className="text-[11px] text-muted">
                                        the Playground has the same controls with a bigger preview
                                    </span>
                                </div>
                                {captionsOn ? (
                                    <div className="flex flex-col lg:flex-row gap-4">
                                        <CaptionStage
                                            style={captionStyle}
                                            playing={false}
                                            className="w-[140px] shrink-0 self-start rounded-input border border-rule"
                                        />
                                        <div className="flex-1 min-w-0">
                                            <CaptionControls value={captionStyle} onChange={setCaptionStyle} />
                                        </div>
                                    </div>
                                ) : (
                                    <p className="text-[11px] leading-relaxed text-muted">
                                        Captions are off for this job. The source may already carry
                                        burned-in subtitles, or you can add them later from the clip’s
                                        subtitle button.
                                    </p>
                                )}
                            </div>
                        </div>
                    )}
                </div>

                <label className="flex items-start gap-2.5 mt-5 text-left text-[13px] sm:text-xs leading-relaxed text-muted cursor-pointer select-none">
                    <input
                        type="checkbox"
                        checked={acknowledged}
                        onChange={(e) => setAcknowledged(e.target.checked)}
                        className="mt-0.5 w-4 h-4 shrink-0 accent-[var(--color-accent)] cursor-pointer"
                    />
                    <span>
                        I confirm I own this content or have the rights to process it. I am responsible for any content I submit.
                    </span>
                </label>

                <button
                    type="submit"
                    data-tutorial="generate"
                    disabled={isProcessing || !canSubmit}
                    className="w-full btn-primary mt-4"
                >
                    {isProcessing ? (
                        <>
                            <Loader2 size={16} className="animate-spin" />
                            Processing Video...
                        </>
                    ) : (
                        <>
                            {bulk
                                ? `Process ${mode === 'url' ? bulkUrls.length : mode === 'file' ? files.length : picked.length || ''} video(s) one by one`
                                : 'Generate Clips'}
                        </>
                    )}
                </button>
            </form>

            <CollectorPicker
                open={pickerOpen}
                multi={bulk}
                onClose={() => setPickerOpen(false)}
                onConfirm={(items) => {
                    setPicked(bulk ? items : items.slice(0, 1));
                    setPickerOpen(false);
                }}
            />
        </div>
    );
}
