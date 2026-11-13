import React, { useEffect, useMemo, useState } from 'react';
import {
    AlertCircle, Check, ChevronDown, ChevronUp, Key, Loader2, RotateCcw,
    Shield, Sparkles, Zap,
} from 'lucide-react';
import { apiFetch } from '../lib/api';
import McpConnectCard from './McpConnectCard';

// Settings is now two real control surfaces for this install:
//
//  1. AI providers — five slots tried in order. A failure (quota, dead
//     endpoint, malformed JSON) falls through to the next slot instead of
//     failing the job.
//  2. Prompts — the instruction blocks that used to be hard-coded constants,
//     seeded with their current text so they can be read and edited.
//
// The chain and the prompt overrides are stored server-side in
// Storage/settings.json: an MCP/agent job has no browser to read localStorage
// from, and the batch queue must use the same providers.

const BLANK_LEVEL = (index) => ({
    level: index + 1,
    enabled: false,
    provider: 'openai',
    model: '',
    base_url: '',
    api_key: '',
    timeout: 600,
});

function LevelStatus({ level }) {
    const configured = level.enabled && (level.provider === 'gemini'
        ? (level.api_key || level.apiKeyFromEnv)
        : !!level.base_url);
    return (
        <span className={`inline-flex items-center gap-1.5 text-[11px] lowercase ${configured ? 'text-ok' : 'text-muted'}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${configured ? 'bg-ok' : 'bg-rule2'}`} />
            {configured ? 'ready' : level.enabled ? 'needs a key / URL' : 'off'}
        </span>
    );
}

function LlmChain({ levels, providers, onChange, onSaved }) {
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [testing, setTesting] = useState(null);
    const [results, setResults] = useState({});

    const patch = (index, field, value) => {
        onChange(levels.map((lv, i) => (i === index ? { ...lv, [field]: value } : lv)));
    };

    const save = async () => {
        setSaving(true);
        setError('');
        try {
            const res = await apiFetch('/api/settings/llm', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ levels }),
            });
            const body = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
            onSaved(body.levels || levels);
        } catch (e) {
            setError(String(e.message || e).slice(0, 300));
        } finally {
            setSaving(false);
        }
    };

    const test = async (index) => {
        setTesting(index);
        setResults((prev) => ({ ...prev, [index]: null }));
        try {
            const res = await apiFetch('/api/settings/llm/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ level: levels[index] }),
            });
            const body = await res.json().catch(() => ({}));
            setResults((prev) => ({ ...prev, [index]: res.ok ? body : { ok: false, error: body.detail || `HTTP ${res.status}` } }));
        } catch (e) {
            setResults((prev) => ({ ...prev, [index]: { ok: false, error: String(e.message || e) } }));
        } finally {
            setTesting(null);
        }
    };

    return (
        <section className="card p-5 sm:p-6 mb-6">
            <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                <div>
                    <p className="eyebrow mb-1">AI providers</p>
                    <h2 className="font-display lowercase text-xl text-ink flex items-center gap-2">
                        <Zap size={17} className="text-brass" /> fallback chain
                    </h2>
                    <p className="text-xs text-muted mt-1.5 max-w-2xl leading-relaxed">
                        Up to five providers, tried in order. If level 1 fails (dead endpoint, quota,
                        malformed JSON) the picker automatically tries level 2, then 3. Only the
                        levels you fill in are used. Any level that can see images also serves the
                        frame-based stages (layout, silent videos, hook grounding).
                    </p>
                </div>
                <button onClick={save} disabled={saving} className="btn-primary px-4 py-2 text-sm">
                    {saving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
                    save chain
                </button>
            </div>

            {error && (
                <p className="text-xs text-danger mb-3 flex items-center gap-1.5" role="alert">
                    <AlertCircle size={13} /> {error}
                </p>
            )}

            <div className="space-y-3">
                {levels.map((level, index) => {
                    const result = results[index];
                    const isGemini = level.provider === 'gemini';
                    return (
                        <div
                            key={index}
                            className={`rounded-card border p-3.5 transition-colors ${level.enabled
                                ? 'border-rule bg-paper2/40'
                                : 'border-rule/60 bg-paper/40 opacity-70'}`}
                        >
                            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                                <div className="flex items-center gap-2.5">
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <input
                                            type="checkbox"
                                            checked={!!level.enabled}
                                            onChange={(e) => patch(index, 'enabled', e.target.checked)}
                                            className="accent-brass"
                                        />
                                        <span className="readout text-ink2">level {index + 1}</span>
                                    </label>
                                    {index === 0 && <span className="badge-ok text-[10px]">primary</span>}
                                    <LevelStatus level={level} />
                                </div>
                                <div className="flex items-center gap-2">
                                    <button
                                        type="button"
                                        onClick={() => test(index)}
                                        disabled={testing === index || !level.enabled}
                                        className="btn-quiet text-xs px-2.5 py-1.5"
                                    >
                                        {testing === index
                                            ? <Loader2 size={12} className="animate-spin" />
                                            : <Zap size={12} />}
                                        test
                                    </button>
                                </div>
                            </div>

                            <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-2.5">
                                <label className="block">
                                    <span className="eyebrow">provider</span>
                                    <select
                                        value={level.provider}
                                        onChange={(e) => patch(index, 'provider', e.target.value)}
                                        className="input-field mt-1 text-sm"
                                    >
                                        {(providers || []).map((p) => (
                                            <option key={p.id} value={p.id}>{p.label}</option>
                                        ))}
                                    </select>
                                </label>
                                <label className="block">
                                    <span className="eyebrow">model</span>
                                    <input
                                        value={level.model || ''}
                                        onChange={(e) => patch(index, 'model', e.target.value)}
                                        placeholder={level.resolvedModel || 'model id'}
                                        className="input-field mt-1 text-sm font-mono"
                                    />
                                </label>
                                {!isGemini && (
                                    <label className="block">
                                        <span className="eyebrow">base url</span>
                                        <input
                                            value={level.base_url || ''}
                                            onChange={(e) => patch(index, 'base_url', e.target.value)}
                                            placeholder="https://api.openai.com/v1"
                                            className="input-field mt-1 text-sm font-mono"
                                        />
                                    </label>
                                )}
                                <label className="block">
                                    <span className="eyebrow">api key {level.apiKeyFromEnv && <span className="text-ok">(env)</span>}</span>
                                    <input
                                        type="password"
                                        value={level.api_key || ''}
                                        onChange={(e) => patch(index, 'api_key', e.target.value)}
                                        placeholder="sk-… / ollama / AIzaSy…"
                                        className="input-field mt-1 text-sm font-mono"
                                    />
                                </label>
                                {!isGemini && (
                                    <label className="block">
                                        <span className="eyebrow">timeout (s)</span>
                                        <input
                                            type="number"
                                            min="5"
                                            max="3600"
                                            value={level.timeout || 600}
                                            onChange={(e) => patch(index, 'timeout', Number(e.target.value))}
                                            className="input-field mt-1 text-sm font-mono"
                                        />
                                    </label>
                                )}
                            </div>

                            {result && (
                                <p className={`text-[11px] mt-2.5 ${result.ok ? 'text-ok' : 'text-danger'}`}>
                                    {result.ok
                                        ? `reachable · ${result.model || level.model} · ${result.latencyMs} ms`
                                        : `${result.error || 'failed'}`}
                                </p>
                            )}
                        </div>
                    );
                })}
            </div>

            <p className="text-[11px] text-muted mt-3 leading-relaxed">
                Keys are stored on this machine in <code className="text-ink2">Storage/settings.json</code>{' '}
                and sent only to the provider you chose. OpenRouter is the easiest way to put
                Anthropic/DeepSeek/Mistral models in the chain: pick OpenAI-compatible and use
                <code className="text-ink2"> https://openrouter.ai/api/v1</code>. Until you save a
                chain, <code className="text-ink2">LLM_BASE_URL</code> /{' '}
                <code className="text-ink2">GEMINI_API_KEY</code> from the environment still apply.
            </p>
        </section>
    );
}

function PromptEditor({ prompts, onReload }) {
    const [drafts, setDrafts] = useState({});
    const [dirty, setDirty] = useState(() => new Set());
    const [open, setOpen] = useState(null);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        const next = {};
        (prompts || []).forEach((p) => { next[p.id] = p.template; });
        setDrafts(next);
        setDirty(new Set());
    }, [prompts]);

    const groups = useMemo(() => {
        const out = {};
        (prompts || []).forEach((p) => { (out[p.group] = out[p.group] || []).push(p); });
        return out;
    }, [prompts]);

    const edit = (id, value) => {
        setDrafts((prev) => ({ ...prev, [id]: value }));
        setDirty((prev) => new Set(prev).add(id));
    };

    const save = async () => {
        if (!dirty.size) return;
        setSaving(true);
        setError('');
        try {
            const updates = {};
            dirty.forEach((id) => { updates[id] = drafts[id]; });
            const res = await apiFetch('/api/settings/prompts', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompts: updates }),
            });
            const body = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
            await onReload();
        } catch (e) {
            setError(String(e.message || e).slice(0, 300));
        } finally {
            setSaving(false);
        }
    };

    const reset = async (id) => {
        setError('');
        try {
            const res = await apiFetch('/api/settings/prompts/reset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: [id] }),
            });
            const body = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
            await onReload();
        } catch (e) {
            setError(String(e.message || e).slice(0, 300));
        }
    };

    return (
        <section className="card p-5 sm:p-6 mb-6">
            <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                <div>
                    <p className="eyebrow mb-1">Prompts</p>
                    <h2 className="font-display lowercase text-xl text-ink flex items-center gap-2">
                        <Sparkles size={17} className="text-brass" /> system prompts
                    </h2>
                    <p className="text-xs text-muted mt-1.5 max-w-2xl leading-relaxed">
                        These are the exact instruction blocks the pipeline sends. The box is
                        seeded with the current text (the shipped default until you edit and save
                        it). Keep the <code className="text-ink2">{'{placeholders}'}</code> in place —
                        they are filled per call and saving fails if one is missing.
                    </p>
                </div>
                <button onClick={save} disabled={saving || !dirty.size} className="btn-primary px-4 py-2 text-sm">
                    {saving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
                    save prompts {dirty.size ? `(${dirty.size})` : ''}
                </button>
            </div>

            {error && (
                <p className="text-xs text-danger mb-3 flex items-center gap-1.5" role="alert">
                    <AlertCircle size={13} /> {error}
                </p>
            )}

            {Object.entries(groups).map(([group, items]) => (
                <div key={group} className="mb-5 last:mb-0">
                    <p className="readout mb-2">{group}</p>
                    <div className="space-y-2">
                        {items.map((p) => {
                            const expanded = open === p.id;
                            return (
                                <div key={p.id} className="rounded-card border border-rule bg-paper2/30">
                                    <button
                                        type="button"
                                        onClick={() => setOpen(expanded ? null : p.id)}
                                        className="w-full flex items-center justify-between gap-3 px-3.5 py-2.5 text-left"
                                    >
                                        <span className="min-w-0">
                                            <span className="text-sm text-ink lowercase">{p.label}</span>
                                            <span className="text-[11px] text-muted ml-2">{p.where}</span>
                                        </span>
                                        <span className="flex items-center gap-2 shrink-0">
                                            {p.overridden && <span className="badge-ok text-[10px]">edited</span>}
                                            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                                        </span>
                                    </button>

                                    {expanded && (
                                        <div className="px-3.5 pb-3.5">
                                            <p className="text-[11px] text-muted mb-2 leading-relaxed">{p.description}</p>
                                            {p.placeholders.length > 0 && (
                                                <div className="flex flex-wrap gap-1 mb-2">
                                                    {p.placeholders.map((v) => (
                                                        <code key={v} className="text-[10px] px-1.5 py-0.5 rounded bg-paper3 text-ink2">{`{${v}}`}</code>
                                                    ))}
                                                </div>
                                            )}
                                            <textarea
                                                value={drafts[p.id] ?? p.template}
                                                onChange={(e) => edit(p.id, e.target.value)}
                                                rows={Math.min(26, Math.max(10, (drafts[p.id] ?? p.template).split('\n').length + 2))}
                                                spellCheck={false}
                                                className="input-field font-mono text-xs leading-relaxed w-full"
                                            />
                                            <div className="flex flex-wrap items-center justify-between gap-2 mt-2">
                                                <span className="text-[11px] text-muted">
                                                    {dirty.has(p.id) ? 'unsaved changes' : p.overridden ? 'custom copy in use' : 'shipped default'}
                                                </span>
                                                <button
                                                    type="button"
                                                    onClick={() => reset(p.id)}
                                                    className="btn-quiet text-xs px-2.5 py-1.5"
                                                    title="Discard the saved copy and use the shipped default"
                                                >
                                                    <RotateCcw size={12} /> reset to default
                                                </button>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>
            ))}
        </section>
    );
}

export default function SettingsPage({ billingEnabled, isManaged, onChoosePlan }) {
    const [levels, setLevels] = useState(null);
    const [providers, setProviders] = useState([]);
    const [prompts, setPrompts] = useState([]);
    const [error, setError] = useState('');

    const loadLevels = async () => {
        const res = await apiFetch('/api/settings/llm');
        if (!res.ok) throw new Error(await res.text());
        const body = await res.json();
        setLevels(body.levels || []);
        setProviders(body.providers || []);
    };

    const loadPrompts = async () => {
        const res = await apiFetch('/api/settings/prompts');
        if (!res.ok) throw new Error(await res.text());
        const body = await res.json();
        setPrompts(body.prompts || []);
    };

    useEffect(() => {
        if (billingEnabled) return;
        Promise.all([loadLevels(), loadPrompts()]).catch((e) => setError(String(e.message || e)));
    }, [billingEnabled]);

    return (
        <div className="h-full w-full overflow-y-auto overscroll-contain custom-scrollbar animate-fade">
            <div className="w-full p-3 sm:p-6">
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-6">
                    <div>
                        <p className="eyebrow mb-1.5">08 · SETTINGS</p>
                        <h1 className="font-display lowercase text-2xl text-ink">Settings</h1>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted mt-1">
                        <Shield size={12} className="text-ok shrink-0" />
                        Keys and prompts stay on this machine (sent only to the provider)
                    </div>
                </div>

                {error && (
                    <div className="card p-4 mb-5 border-danger/40 text-danger text-sm flex items-center gap-2">
                        <AlertCircle size={15} /> {error}
                    </div>
                )}

                {!billingEnabled && (
                    <>
                        {levels ? (
                            <LlmChain
                                levels={levels}
                                providers={providers}
                                onChange={setLevels}
                                onSaved={setLevels}
                            />
                        ) : !error ? (
                            <div className="card p-6 mb-6 flex items-center gap-2 text-muted text-sm">
                                <Loader2 size={16} className="animate-spin" /> loading providers…
                            </div>
                        ) : null}

                        <PromptEditor prompts={prompts} onReload={loadPrompts} />
                        <div className="mb-6"><McpConnectCard cloud={false} /></div>
                    </>
                )}

                {billingEnabled && isManaged && (
                    <div className="card p-6 mb-2">
                        <div className="flex items-center justify-between mb-3">
                            <div className="flex items-center gap-3">
                                <div className="w-9 h-9 rounded-input bg-paper3 flex items-center justify-center shrink-0">
                                    <Shield size={16} className="text-brass" />
                                </div>
                                <h2 className="text-base font-medium text-ink lowercase">Included in your plan</h2>
                            </div>
                            <span className="badge-ok">Managed</span>
                        </div>
                        <p className="text-xs text-muted mb-5 leading-relaxed">
                            Your plan includes the <strong>Clip Generator</strong> and <strong>YouTube Studio</strong>,
                            fully managed — no API keys required.
                        </p>
                    </div>
                )}

                {billingEnabled && !isManaged && (
                    <div className="card p-6 mb-2">
                        <div className="flex items-center justify-between mb-3">
                            <div className="flex items-center gap-3">
                                <div className="w-9 h-9 rounded-input bg-paper3 flex items-center justify-center shrink-0">
                                    <Sparkles size={16} className="text-brass" />
                                </div>
                                <h2 className="text-base font-medium text-ink lowercase">Choose your plan</h2>
                            </div>
                            <span className="badge-ok">Free plan available</span>
                        </div>
                        <p className="text-xs text-muted mb-5 leading-relaxed">
                            Generate shorts with zero setup — no API keys needed.
                        </p>
                        <button onClick={onChoosePlan} className="btn-primary py-2 px-4 text-sm">
                            <Sparkles size={16} /> Choose a plan
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
