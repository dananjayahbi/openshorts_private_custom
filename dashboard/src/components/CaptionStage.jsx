import React, { useEffect, useRef, useState } from 'react';
import { luminance } from '../lib/captionStyles';

// A live CSS preview of the caption style the pipeline will burn. It mirrors
// the subtitle burn: ASS sizes text against PlayResY 288, so the font size is
// `font_size * 0.85 * (stageHeight / 288)`; the active word gets the
// preset's effect, inactive words are dimmed by RGB (not alpha) like
// `generate_ass`. Not a Remotion render — instant feedback while you drag a
// control, with a real clip (or a neutral stage) behind it.

const SAMPLE_WORDS = ['this', 'is', 'how', 'your', 'captions', 'will', 'look', 'on', 'the', 'clip'];

function mixToBlack(hex, amount) {
    const m = /^#?([0-9a-fA-F]{6})$/.exec(hex || '');
    if (!m) return hex;
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16));
    const k = Math.max(0, Math.min(1, amount));
    const to = (v) => Math.round(v * k).toString(16).padStart(2, '0');
    return `#${to(r)}${to(g)}${to(b)}`;
}

export default function CaptionStage({
    style,
    videoUrl = null,
    posterUrl = null,
    playing = true,
    words = SAMPLE_WORDS,
    aspect = '9 / 16',
    className = '',
}) {
    const boxRef = useRef(null);
    const [height, setHeight] = useState(540);
    const [active, setActive] = useState(0);

    useEffect(() => {
        const node = boxRef.current;
        if (!node || typeof ResizeObserver === 'undefined') return undefined;
        const observer = new ResizeObserver((entries) => {
            const h = entries[0]?.contentRect?.height;
            if (h) setHeight(h);
        });
        observer.observe(node);
        return () => observer.disconnect();
    }, []);

    useEffect(() => {
        if (!playing) return undefined;
        const id = setInterval(() => {
            setActive((i) => (i + 1) % Math.max(1, words.length));
        }, 430);
        return () => clearInterval(id);
    }, [playing, words.length]);

    const maxChars = Math.max(1, Number(style?.max_chars) || 3);
    // A window of words that fits the line budget, sliding with the active word.
    const start = Math.max(0, Math.min(active, Math.max(0, words.length - maxChars)));
    const visible = words.slice(start, start + maxChars);
    const activeIndex = Math.min(active - start, visible.length - 1);

    const fontPx = Math.max(10, (Number(style?.font_size) || 44) * 0.85 * (height / 288));
    const borderPx = Math.max(0, (Number(style?.border_width) || 0) * (height / 288));
    const shadowPx = Math.max(0, Number(style?.shadow) || 0);

    const outline = borderPx > 0
        ? [
            `-${borderPx}px -${borderPx}px 0 ${style.border_color}`,
            `${borderPx}px -${borderPx}px 0 ${style.border_color}`,
            `-${borderPx}px ${borderPx}px 0 ${style.border_color}`,
            `${borderPx}px ${borderPx}px 0 ${style.border_color}`,
            `0 -${borderPx}px 0 ${style.border_color}`,
            `0 ${borderPx}px 0 ${style.border_color}`,
            `-${borderPx}px 0 0 ${style.border_color}`,
            `${borderPx}px 0 0 ${style.border_color}`,
        ].join(', ')
        : 'none';

    const inactive = style?.style === 'karaoke' && style?.base_opacity < 1
        ? mixToBlack(style.font_color, style.base_opacity)
        : style?.font_color;

    const positionClass = style?.position === 'top'
        ? 'top-[12%]'
        : style?.position === 'middle'
            ? 'top-1/2 -translate-y-1/2'
            : 'bottom-[12%]';

    const boxBackground = Number(style?.bg_opacity) > 0
        ? `${style.bg_color}${Math.round(Number(style.bg_opacity) * 255).toString(16).padStart(2, '0')}`
        : 'transparent';

    const activeBg = (style?.effect === 'highlight' || style?.effect === 'box')
        ? style.highlight_color
        : 'transparent';
    const activeFg = activeBg !== 'transparent'
        ? (luminance(style.highlight_color) > 0.6 ? '#000000' : style.font_color)
        : style.highlight_color;

    return (
        <div
            ref={boxRef}
            className={`relative w-full bg-black overflow-hidden ${className}`}
            style={{ aspectRatio: aspect }}
        >
            {videoUrl ? (
                <video
                    src={videoUrl}
                    poster={posterUrl || undefined}
                    muted
                    loop
                    autoPlay
                    playsInline
                    preload="metadata"
                    className="absolute inset-0 w-full h-full object-cover"
                />
            ) : posterUrl ? (
                <img src={posterUrl} alt="" className="absolute inset-0 w-full h-full object-cover opacity-80" />
            ) : (
                <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,#3a2a1c,transparent_55%),radial-gradient(circle_at_75%_70%,#1f2a33,transparent_60%),#0d0f14]" />
            )}

            <div className={`absolute inset-x-0 px-[6%] flex justify-center ${positionClass}`}>
                <div
                    className="flex flex-wrap items-baseline justify-center gap-x-[0.28em] gap-y-[0.12em] text-center max-w-full"
                    style={{
                        background: boxBackground,
                        padding: boxBackground === 'transparent' ? 0 : '0.18em 0.35em',
                        borderRadius: 4,
                    }}
                >
                    {visible.map((word, index) => {
                        const isActive = index === activeIndex;
                        const hidden = style?.reveal && index > activeIndex;
                        return (
                            <span
                                key={`${word}-${index}`}
                                style={{
                                    fontFamily: style?.font_name,
                                    fontSize: `${fontPx}px`,
                                    fontWeight: 800,
                                    lineHeight: 1.15,
                                    color: isActive ? activeFg : inactive,
                                    background: isActive ? activeBg : 'transparent',
                                    padding: isActive && activeBg !== 'transparent' ? '0 0.14em' : 0,
                                    borderRadius: 3,
                                    textShadow: isActive && style?.effect === 'glow'
                                        ? `0 0 ${Math.max(8, fontPx * 0.22)}px ${style.highlight_color}, ${outline}`
                                        : (borderPx > 0 ? outline : (shadowPx > 0 ? `0 ${shadowPx}px ${shadowPx * 2}px rgba(0,0,0,.85)` : 'none')),
                                    transform: isActive && style?.effect === 'pop' ? 'scale(1.08)' : 'scale(1)',
                                    transition: 'transform 90ms ease-out, color 90ms linear',
                                    opacity: hidden ? 0 : 1,
                                    textTransform: style?.uppercase ? 'uppercase' : 'none',
                                    whiteSpace: 'pre',
                                }}
                            >
                                {style?.uppercase ? word.toUpperCase() : word}
                            </span>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
