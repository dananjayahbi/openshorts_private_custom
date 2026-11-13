import React, { useCallback, useEffect, useState } from 'react';
import {
    AlertCircle, Loader2, Pencil, Play, Plus, Trash2,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import CaptionStage from './CaptionStage';
import { DEFAULT_CAPTION_STYLE, OUTPUT_FORMATS } from '../lib/captionStyles';

const formatLabel = (id) => (OUTPUT_FORMATS.find((f) => f.id === id) || OUTPUT_FORMATS[0]).label;

// Style Profiles: the playlists of looks. The Clip Generator applies one and
// still lets every control be changed afterwards; a profile is a starting
// point, not a lock.

export default function StyleProfiles({ onUse, onEdit, onCreate }) {
    const [profiles, setProfiles] = useState(null);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState('');

    const load = useCallback(async () => {
        try {
            const res = await apiFetch('/api/style-profiles');
            if (!res.ok) throw new Error(await res.text());
            const body = await res.json();
            setProfiles(body.profiles || []);
            setError('');
        } catch (e) {
            setError(String(e.message || e).slice(0, 300));
            setProfiles([]);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const remove = async (profile) => {
        if (!window.confirm(`Delete the profile "${profile.name}"? Clips already rendered are not touched.`)) return;
        setBusy(profile.id);
        try {
            const res = await apiFetch(`/api/style-profiles/${profile.id}`, { method: 'DELETE' });
            if (!res.ok) throw new Error(await res.text());
            await load();
        } catch (e) {
            setError(String(e.message || e).slice(0, 300));
        } finally {
            setBusy('');
        }
    };

    return (
        <div className="h-full w-full overflow-y-auto overscroll-contain custom-scrollbar animate-fade">
            <div className="w-full p-3 sm:p-6">
                <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
                    <div>
                        <p className="eyebrow mb-1.5">05 · STYLE PROFILES</p>
                        <h1 className="font-display lowercase text-2xl text-ink">style profiles</h1>
                        <p className="text-sm text-muted mt-1.5 max-w-2xl">
                            Saved caption looks and output shapes. Pick one in the Clip Generator,
                            then override anything you like before generating.
                        </p>
                    </div>
                    <button onClick={onCreate} className="btn-primary px-4 py-2 text-sm">
                        <Plus size={15} /> new in playground
                    </button>
                </div>

                {error && (
                    <div className="card p-3 mb-4 border-danger/40 text-danger text-sm flex items-center gap-2">
                        <AlertCircle size={14} /> {error}
                    </div>
                )}

                {profiles === null ? (
                    <div className="card p-8 flex items-center gap-2 text-muted text-sm">
                        <Loader2 size={16} className="animate-spin" /> loading profiles…
                    </div>
                ) : profiles.length === 0 ? (
                    <div className="card p-10 text-center text-muted">
                        <p className="text-lg lowercase mb-2">No profiles yet.</p>
                        <p className="text-sm lowercase mb-5">
                            Build a look in the Playground and save it; it shows up here and in the
                            Clip Generator.
                        </p>
                        <button onClick={onCreate} className="btn-primary px-4 py-2 text-sm">
                            <Plus size={15} /> open playground
                        </button>
                    </div>
                ) : (
                    <div className="grid sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-5">
                        {profiles.map((profile) => {
                            const style = { ...DEFAULT_CAPTION_STYLE, ...(profile.caption || {}) };
                            const output = profile.output || {};
                            return (
                                <div key={profile.id} className="card overflow-hidden flex flex-col">
                                    <div className="bg-black">
                                        <CaptionStage
                                            style={style}
                                            playing={false}
                                            className="max-h-[300px] object-cover"
                                        />
                                    </div>
                                    <div className="p-4 flex flex-col flex-1">
                                        <h2 className="font-medium text-ink lowercase truncate" title={profile.name}>
                                            {profile.name}
                                        </h2>
                                        <div className="flex flex-wrap gap-1.5 mt-2 mb-3">
                                            <span className="readout bg-paper3 px-1.5 py-0.5 rounded-full">
                                                {formatLabel(output.output_format)}
                                            </span>
                                            <span className="readout bg-paper3 px-1.5 py-0.5 rounded-full">
                                                {style.font_name}
                                            </span>
                                            {output.auto_hook && (
                                                <span className="readout bg-paper3 px-1.5 py-0.5 rounded-full">
                                                    hook
                                                </span>
                                            )}
                                            {profile.prompts && Object.keys(profile.prompts).length > 0 && (
                                                <span className="readout bg-paper3 px-1.5 py-0.5 rounded-full">
                                                    {Object.keys(profile.prompts).length} prompt override(s)
                                                </span>
                                            )}
                                        </div>
                                        <p className="text-[11px] text-muted mb-3">
                                            {style.style === 'karaoke' ? 'karaoke' : 'classic'} ·{' '}
                                            {style.position} · {style.font_size}px · {style.effect}
                                        </p>
                                        <div className="mt-auto flex items-center gap-1.5">
                                            <button
                                                onClick={() => onUse?.(profile)}
                                                className="btn-primary flex-1 text-xs py-1.5 px-2"
                                            >
                                                <Play size={12} /> use
                                            </button>
                                            <button
                                                onClick={() => onEdit?.(profile)}
                                                className="btn-quiet text-xs py-1.5 px-2"
                                                title="Edit in the Playground"
                                            >
                                                <Pencil size={12} />
                                            </button>
                                            <button
                                                onClick={() => remove(profile)}
                                                disabled={busy === profile.id}
                                                className="btn-quiet text-xs py-1.5 px-2 text-danger"
                                                title="Delete this profile"
                                            >
                                                {busy === profile.id
                                                    ? <Loader2 size={12} className="animate-spin" />
                                                    : <Trash2 size={12} />}
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
}
