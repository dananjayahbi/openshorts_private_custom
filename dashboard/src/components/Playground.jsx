import React, { useEffect, useMemo, useState } from 'react';
import {
    AlertCircle, Check, Loader2, Pause, Play, RotateCcw, Save, Sparkles,
    Wand2,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import { getApiUrl } from '../config';
import CaptionControls from './CaptionControls';
import CaptionStage from './CaptionStage';
import {
    DEFAULT_CAPTION_STYLE, OUTPUT_FORMATS, HOOK_STYLES, presetToStyle,
} from '../lib/captionStyles';

const SAMPLE_TEXT = 'this is how your captions will look on the clip';

// Playground: find a look before spending a render. Every caption control the
// pipeline understands is here, previewed live over a real clip (or a neutral
// stage), and the result can be saved as a Style Profile for the Clip
// Generator. Prompts come from Settings unless a profile overrides them.

export default function Playground({ initialProfile = null, onSaved, onOpenProfiles }) {
    const [style, setStyle] = useState(DEFAULT_CAPTION_STYLE);
    const [outputFormat, setOutputFormat] = useState('vertical');
    const [autoHook, setAutoHook] = useState(false);
    const [autoHookStyle, setAutoHookStyle] = useState('pill');
    const [playing, setPlaying] = useState(true);
    const [sampleText, setSampleText] = useState(SAMPLE_TEXT);
    const [clips, setClips] = useState([]);
    const [sourceId, setSourceId] = useState('');
    const [profiles, setProfiles] = useState([]);
    const [profileId, setProfileId] = useState(initialProfile?.id || '');
    const [name, setName] = useState(initialProfile?.name || '');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [saved, setSaved] = useState('');

    useEffect(() => {
        apiFetch('/api/gallery/clips?limit=24')
            .then((r) => (r.ok ? r.json() : { clips: [] }))
            .then((d) => setClips((d.clips || []).map((c) => ({ ...c, url: getApiUrl(c.url) }))))
            .catch(() => {});
        apiFetch('/api/style-profiles')
            .then((r) => (r.ok ? r.json() : { profiles: [] }))
            .then((d) => setProfiles(d.profiles || []))
            .catch(() => {});
    }, []);

    useEffect(() => {
        if (!initialProfile) return;
        setProfileId(initialProfile.id);
        setName(initialProfile.name || '');
        setStyle({ ...DEFAULT_CAPTION_STYLE, ...(initialProfile.caption || {}) });
        const output = initialProfile.output || {};
        setOutputFormat(output.output_format || 'vertical');
        setAutoHook(!!output.auto_hook);
        setAutoHookStyle(output.auto_hook_style || 'pill');
    }, [initialProfile]);

    const source = clips.find((c) => `${c.job_id}:${c.index}` === sourceId);
    const words = useMemo(() => {
        const list = String(sampleText || '').trim().split(/\s+/).filter(Boolean);
        return list.length ? list : SAMPLE_TEXT.split(' ');
    }, [sampleText]);
    const aspect = outputFormat === 'square' ? '1 / 1'
        : outputFormat === 'horizontal' ? '16 / 9' : '9 / 16';

    const applyProfile = (id) => {
        setProfileId(id);
        const profile = profiles.find((p) => p.id === id);
        if (!profile) return;
        setName(profile.name || '');
        setStyle({ ...DEFAULT_CAPTION_STYLE, ...(profile.caption || {}) });
        const output = profile.output || {};
        setOutputFormat(output.output_format || 'vertical');
        setAutoHook(!!output.auto_hook);
        setAutoHookStyle(output.auto_hook_style || 'pill');
    };

    const save = async () => {
        if (!name.trim()) {
            setError('Give the profile a name first.');
            return;
        }
        setSaving(true);
        setError('');
        setSaved('');
        try {
            const body = {
                name,
                caption: style,
                output: {
                    output_format: outputFormat,
                    auto_hook: autoHook,
                    auto_hook_style: autoHookStyle,
                },
            };
            const res = await apiFetch(
                profileId ? `/api/style-profiles/${profileId}` : '/api/style-profiles',
                {
                    method: profileId ? 'PATCH' : 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                },
            );
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
            setProfileId(data.id);
            setSaved(profileId ? 'Profile updated.' : 'Profile saved.');
            onSaved?.(data);
            const list = await apiFetch('/api/style-profiles');
            if (list.ok) setProfiles((await list.json()).profiles || []);
        } catch (e) {
            setError(String(e.message || e).slice(0, 300));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="h-full w-full overflow-y-auto overscroll-contain custom-scrollbar animate-fade">
            <div className="w-full p-3 sm:p-6">
                <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
                    <div>
                        <p className="eyebrow mb-1.5">04 · PLAYGROUND</p>
                        <h1 className="font-display lowercase text-2xl text-ink">style playground</h1>
                        <p className="text-sm text-muted mt-1.5 max-w-2xl">
                            Try a caption look and an output shape before rendering. Save the
                            combination as a profile; the Clip Generator applies it in one click.
                        </p>
                    </div>
                    <span className="readout">live preview</span>
                </div>

                {error && (
                    <div className="card p-3 mb-4 border-danger/40 text-danger text-sm flex items-center gap-2">
                        <AlertCircle size={14} /> {error}
                    </div>
                )}

                <div className="grid lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)] gap-5">
                    {/* Stage */}
                    <div className="space-y-3">
                        <div className={`mx-auto w-full ${outputFormat === 'horizontal' ? 'max-w-none' : 'max-w-[380px]'}`}>
                            <CaptionStage
                                style={style}
                                videoUrl={source?.url}
                                posterUrl={source?.thumbnail}
                                playing={playing}
                                words={words}
                                aspect={aspect}
                                className="rounded-card border border-rule shadow-lg"
                            />
                        </div>

                        <div className="flex flex-wrap items-center gap-2">
                            <button
                                type="button"
                                onClick={() => setPlaying((p) => !p)}
                                className="btn-quiet text-xs px-2.5 py-1.5"
                            >
                                {playing ? <Pause size={12} /> : <Play size={12} />}
                                {playing ? 'pause' : 'play'}
                            </button>
                            <select
                                value={sourceId}
                                onChange={(e) => setSourceId(e.target.value)}
                                className="input-field text-xs py-1.5 flex-1 min-w-[160px]"
                            >
                                <option value="">neutral stage</option>
                                {clips.map((c) => (
                                    <option key={`${c.job_id}:${c.index}`} value={`${c.job_id}:${c.index}`}>
                                        {c.title}
                                    </option>
                                ))}
                            </select>
                        </div>

                        <label className="block">
                            <span className="eyebrow">sample text</span>
                            <input
                                value={sampleText}
                                onChange={(e) => setSampleText(e.target.value)}
                                className="input-field mt-1 text-sm"
                                placeholder="words to preview"
                            />
                        </label>

                        <div className="card p-4 space-y-3">
                            <p className="eyebrow">output</p>
                            <div className="grid grid-cols-3 gap-1.5">
                                {OUTPUT_FORMATS.map((f) => (
                                    <button
                                        key={f.id}
                                        type="button"
                                        onClick={() => setOutputFormat(f.id)}
                                        className={`rounded-input border px-2 py-1.5 text-center transition-colors ${outputFormat === f.id
                                            ? 'border-brass bg-brass/10 text-ink'
                                            : 'border-rule text-muted hover:text-ink2'}`}
                                    >
                                        <span className="block text-sm">{f.label}</span>
                                        <span className="block text-[9px] lowercase">{f.hint}</span>
                                    </button>
                                ))}
                            </div>
                            <label className="flex items-center gap-2 text-xs text-ink2">
                                <input
                                    type="checkbox"
                                    checked={autoHook}
                                    onChange={(e) => setAutoHook(e.target.checked)}
                                    className="accent-brass"
                                />
                                burn the hook text
                            </label>
                            {autoHook && (
                                <select
                                    value={autoHookStyle}
                                    onChange={(e) => setAutoHookStyle(e.target.value)}
                                    className="input-field text-sm"
                                >
                                    {HOOK_STYLES.map((h) => (
                                        <option key={h.id} value={h.id}>{h.label}</option>
                                    ))}
                                </select>
                            )}
                        </div>
                    </div>

                    {/* Controls */}
                    <div className="space-y-4">
                        <div className="card p-4 sm:p-5">
                            <div className="flex items-center justify-between gap-2 mb-4">
                                <h2 className="font-display lowercase text-lg text-ink flex items-center gap-2">
                                    <Wand2 size={16} className="text-brass" /> captions
                                </h2>
                                <button
                                    type="button"
                                    onClick={() => setStyle(presetToStyle(null))}
                                    className="btn-quiet text-xs px-2.5 py-1.5"
                                >
                                    <RotateCcw size={12} /> reset look
                                </button>
                            </div>
                            <CaptionControls value={style} onChange={setStyle} />
                        </div>

                        <div className="card p-4 sm:p-5">
                            <h2 className="font-display lowercase text-lg text-ink flex items-center gap-2 mb-3">
                                <Sparkles size={16} className="text-brass" /> save as profile
                            </h2>
                            <p className="text-xs text-muted mb-3 leading-relaxed">
                                Prompts come from Settings. A profile stores this caption look,
                                the output shape and the hook choice; it can also carry its own
                                prompt overrides when saved through the API.
                            </p>
                            <div className="flex flex-wrap items-center gap-2">
                                <select
                                    value={profileId}
                                    onChange={(e) => applyProfile(e.target.value)}
                                    className="input-field text-sm flex-1 min-w-[180px]"
                                >
                                    <option value="">new profile</option>
                                    {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                                </select>
                                <input
                                    value={name}
                                    onChange={(e) => setName(e.target.value)}
                                    placeholder="profile name"
                                    className="input-field text-sm flex-1 min-w-[180px]"
                                />
                                <button onClick={save} disabled={saving} className="btn-primary px-4 py-2 text-sm">
                                    {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
                                    {profileId ? 'update' : 'save'}
                                </button>
                            </div>
                            {saved && (
                                <p className="text-xs text-ok mt-2 flex items-center gap-1.5">
                                    <Check size={13} /> {saved}
                                    {onOpenProfiles && (
                                        <button
                                            type="button"
                                            onClick={onOpenProfiles}
                                            className="text-brass underline underline-offset-2 ml-1"
                                        >
                                            view profiles
                                        </button>
                                    )}
                                </p>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
