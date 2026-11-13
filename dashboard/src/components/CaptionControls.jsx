import React from 'react';
import {
    ANIMATION_OPTIONS, ANIMATION_TO_EFFECT, CAPTION_PRESETS, COLOR_PRESETS,
    DEFAULT_CAPTION_STYLE, EFFECT_TO_ANIMATION, FONT_OPTIONS, HIGHLIGHT_PRESETS,
    POSITION_OPTIONS, SIZE_OPTIONS, lineBudget, matchPreset, presetToStyle,
} from '../lib/captionStyles';

// The caption look editor used by the Playground and by the Clip Generator's
// pre-generation panel. It edits the same snake_case object /api/process takes
// (and the profile store saves), so what you see here is what gets burned.

const Swatch = ({ color, selected, onClick, title }) => (
    <button
        type="button"
        title={title}
        onClick={onClick}
        aria-label={title || color}
        className={`w-6 h-6 rounded-full transition-all ${selected
            ? 'ring-2 ring-[color:var(--color-accent)] ring-offset-2 ring-offset-[color:var(--color-paper-2)]'
            : 'ring-1 ring-[color:var(--color-rule-2)] hover:ring-[color:var(--color-accent)]'}`}
        style={{ backgroundColor: color }}
    />
);

export default function CaptionControls({ value, onChange }) {
    const style = { ...DEFAULT_CAPTION_STYLE, ...(value || {}) };
    const patch = (fields) => onChange({ ...style, ...fields });
    const activePreset = matchPreset(style);
    const animation = EFFECT_TO_ANIMATION[style.effect] || 'none';

    return (
        <div className="space-y-4">
            <div>
                <p className="eyebrow mb-2">preset</p>
                <div className="flex flex-wrap gap-1.5">
                    {CAPTION_PRESETS.map((preset) => (
                        <button
                            key={preset.id}
                            type="button"
                            onClick={() => onChange(presetToStyle(preset))}
                            className={`px-2.5 py-1 rounded-input text-[11px] border transition-colors ${activePreset === preset.id
                                ? 'border-brass text-ink bg-brass/10'
                                : 'border-rule text-muted hover:text-ink2 hover:border-rule2'}`}
                        >
                            {preset.label}
                        </button>
                    ))}
                </div>
            </div>

            <div className="grid sm:grid-cols-2 gap-3">
                <label className="block">
                    <span className="eyebrow">font</span>
                    <select
                        value={style.font_name}
                        onChange={(e) => {
                            const name = e.target.value;
                            patch({
                                font_name: name,
                                max_chars: lineBudget(name, style.font_size, style.max_chars === 1),
                            });
                        }}
                        className="input-field mt-1 text-sm"
                    >
                        {FONT_OPTIONS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
                    </select>
                </label>

                <label className="block">
                    <span className="eyebrow">position</span>
                    <select
                        value={style.position}
                        onChange={(e) => patch({ position: e.target.value })}
                        className="input-field mt-1 text-sm"
                    >
                        {POSITION_OPTIONS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                    </select>
                </label>

                <div>
                    <span className="eyebrow">size</span>
                    <div className="flex gap-1.5 mt-1">
                        {SIZE_OPTIONS.map((s) => (
                            <button
                                key={s.value}
                                type="button"
                                onClick={() => patch({
                                    font_size: s.value,
                                    max_chars: lineBudget(style.font_name, s.value, style.max_chars === 1),
                                })}
                                className={`flex-1 py-1.5 rounded-input text-xs border transition-colors ${Number(style.font_size) === s.value
                                    ? 'border-brass text-ink bg-brass/10' : 'border-rule text-muted hover:text-ink2'}`}
                            >
                                {s.label}
                            </button>
                        ))}
                    </div>
                </div>

                <label className="block">
                    <span className="eyebrow">animation</span>
                    <select
                        value={animation}
                        onChange={(e) => patch({ effect: ANIMATION_TO_EFFECT[e.target.value] || 'none' })}
                        className="input-field mt-1 text-sm"
                    >
                        {ANIMATION_OPTIONS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
                    </select>
                </label>
            </div>

            <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
                <label className="flex items-center gap-2 text-xs text-ink2 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={!!style.uppercase}
                        onChange={(e) => patch({ uppercase: e.target.checked })}
                        className="accent-brass"
                    />
                    UPPERCASE
                </label>
                <label className="flex items-center gap-2 text-xs text-ink2 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={!!style.reveal}
                        onChange={(e) => patch({ reveal: e.target.checked })}
                        className="accent-brass"
                    />
                    reveal word by word
                </label>
                <label className="flex items-center gap-2 text-xs text-ink2 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={Number(style.max_chars) === 1}
                        onChange={(e) => patch({
                            max_chars: e.target.checked
                                ? 1
                                : lineBudget(style.font_name, style.font_size, false),
                        })}
                        className="accent-brass"
                    />
                    one word at a time
                </label>
            </div>

            <div className="grid sm:grid-cols-2 gap-3">
                <label className="block">
                    <span className="eyebrow">dim inactive words · {Math.round((1 - Number(style.base_opacity)) * 100)}%</span>
                    <input
                        type="range"
                        min="0"
                        max="0.85"
                        step="0.05"
                        value={1 - Number(style.base_opacity)}
                        onChange={(e) => patch({ base_opacity: 1 - Number(e.target.value) })}
                        className="w-full mt-2 accent-brass"
                    />
                </label>
                <label className="block">
                    <span className="eyebrow">shadow · {style.shadow}</span>
                    <input
                        type="range"
                        min="0"
                        max="8"
                        step="1"
                        value={Number(style.shadow)}
                        onChange={(e) => patch({ shadow: Number(e.target.value) })}
                        className="w-full mt-2 accent-brass"
                    />
                </label>
            </div>

            <div className="grid sm:grid-cols-2 gap-3">
                <div>
                    <p className="eyebrow mb-1.5">text color</p>
                    <div className="flex flex-wrap items-center gap-1.5">
                        {COLOR_PRESETS.map((c) => (
                            <Swatch
                                key={c.color}
                                color={c.color}
                                title={c.label}
                                selected={style.font_color.toLowerCase() === c.color.toLowerCase()}
                                onClick={() => patch({ font_color: c.color })}
                            />
                        ))}
                        <input
                            type="color"
                            value={style.font_color}
                            onChange={(e) => patch({ font_color: e.target.value })}
                            className="w-6 h-6 rounded-full bg-transparent border border-rule cursor-pointer"
                            title="custom text color"
                        />
                    </div>
                </div>

                <div>
                    <p className="eyebrow mb-1.5">active word / box</p>
                    <div className="flex flex-wrap items-center gap-1.5">
                        {HIGHLIGHT_PRESETS.map((c) => (
                            <Swatch
                                key={c.color}
                                color={c.color}
                                title={c.label}
                                selected={style.highlight_color.toLowerCase() === c.color.toLowerCase()}
                                onClick={() => patch({ highlight_color: c.color })}
                            />
                        ))}
                        <input
                            type="color"
                            value={style.highlight_color}
                            onChange={(e) => patch({ highlight_color: e.target.value })}
                            className="w-6 h-6 rounded-full bg-transparent border border-rule cursor-pointer"
                            title="custom highlight color"
                        />
                    </div>
                </div>

                <div>
                    <p className="eyebrow mb-1.5">border</p>
                    <div className="flex items-center gap-2">
                        <input
                            type="color"
                            value={style.border_color}
                            onChange={(e) => patch({ border_color: e.target.value })}
                            className="w-7 h-7 rounded-input bg-transparent border border-rule cursor-pointer"
                            title="border color"
                        />
                        <input
                            type="range"
                            min="0"
                            max="8"
                            step="1"
                            value={Number(style.border_width)}
                            onChange={(e) => patch({ border_width: Number(e.target.value) })}
                            className="flex-1 accent-brass"
                        />
                        <span className="readout w-6 text-right">{style.border_width}</span>
                    </div>
                </div>

                <div>
                    <p className="eyebrow mb-1.5">background box</p>
                    <div className="flex items-center gap-2">
                        <label className="flex items-center gap-1.5 text-xs text-ink2">
                            <input
                                type="checkbox"
                                checked={Number(style.bg_opacity) > 0}
                                onChange={(e) => patch({ bg_opacity: e.target.checked ? 0.55 : 0 })}
                                className="accent-brass"
                            />
                            on
                        </label>
                        <input
                            type="color"
                            value={style.bg_color}
                            onChange={(e) => patch({ bg_color: e.target.value })}
                            className="w-7 h-7 rounded-input bg-transparent border border-rule cursor-pointer"
                            title="box color"
                        />
                        <input
                            type="range"
                            min="0"
                            max="1"
                            step="0.05"
                            value={Number(style.bg_opacity)}
                            onChange={(e) => patch({ bg_opacity: Number(e.target.value) })}
                            className="flex-1 accent-brass"
                        />
                    </div>
                </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 text-xs text-muted">
                    max characters / line
                    <input
                        type="number"
                        min="1"
                        max="40"
                        value={style.max_chars}
                        onChange={(e) => patch({ max_chars: Math.min(40, Math.max(1, Number(e.target.value) || 1)) })}
                        className="input-field w-16 py-1 text-sm font-mono"
                    />
                </label>
                <label className="flex items-center gap-2 text-xs text-muted">
                    caption block
                    <input
                        type="number"
                        min="0.4"
                        max="5"
                        step="0.1"
                        value={style.max_duration}
                        onChange={(e) => patch({ max_duration: Math.min(5, Math.max(0.4, Number(e.target.value) || 1.4)) })}
                        className="input-field w-16 py-1 text-sm font-mono"
                    />
                    s
                </label>
            </div>
        </div>
    );
}
