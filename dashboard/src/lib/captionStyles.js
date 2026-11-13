// One vocabulary for caption looks, shared by the Playground, the Clip
// Generator's pre-generation panel, the Style Profiles page and the subtitle
// modal's presets. Field names are the server's (snake_case) so a style object
// can be POSTed to /api/process or saved on a profile without a translation
// layer; the preview reads the same object.

export const FONT_OPTIONS = [
    { value: 'Anton', label: 'Anton' },
    { value: 'Montserrat ExtraBold', label: 'Montserrat' },
    { value: 'Verdana', label: 'Verdana' },
    { value: 'Arial', label: 'Arial' },
    { value: 'Impact', label: 'Impact' },
    { value: 'Helvetica', label: 'Helvetica' },
    { value: 'Georgia', label: 'Georgia' },
    { value: 'Courier New', label: 'Courier New' },
];

export const COLOR_PRESETS = [
    { color: '#FFFFFF', label: 'White' },
    { color: '#FFFF00', label: 'Yellow' },
    { color: '#00FFFF', label: 'Cyan' },
    { color: '#00FF00', label: 'Green' },
    { color: '#FF0000', label: 'Red' },
    { color: '#FF69B4', label: 'Pink' },
];

export const HIGHLIGHT_PRESETS = [
    { color: '#FFE500', label: 'Yellow' },
    { color: '#FFDD00', label: 'Gold' },
    { color: '#A3FF12', label: 'Lime' },
    { color: '#7C3AED', label: 'Purple' },
    { color: '#FF4444', label: 'Red' },
    { color: '#00FF88', label: 'Green' },
    { color: '#00BBFF', label: 'Blue' },
    { color: '#FF69B4', label: 'Pink' },
];

export const ANIMATION_OPTIONS = [
    { value: 'pop', label: 'Pop' },
    { value: 'word-highlight', label: 'Glow' },
    { value: 'karaoke', label: 'Box' },
    { value: 'none', label: 'None' },
];

export const ANIMATION_TO_EFFECT = {
    pop: 'pop', 'word-highlight': 'glow', karaoke: 'highlight', none: 'none',
};
export const EFFECT_TO_ANIMATION = {
    pop: 'pop', glow: 'word-highlight', highlight: 'karaoke', box: 'karaoke', none: 'none',
};

export const SIZE_OPTIONS = [
    { value: 34, label: 'S' },
    { value: 44, label: 'M' },
    { value: 56, label: 'L' },
    { value: 70, label: 'XL' },
];

export const POSITION_OPTIONS = [
    { value: 'top', label: 'top' },
    { value: 'middle', label: 'middle' },
    { value: 'bottom', label: 'bottom' },
];

export const LINE_CHARS = { Anton: 16, 'Montserrat ExtraBold': 9, Impact: 16 };

export const lineBudget = (fontName, fontSize, oneWord) =>
    oneWord ? 1 : Math.max(6, Math.round((LINE_CHARS[fontName] || 14) * 44 / fontSize));

// The shipped look (subtitles.AUTO_CAPTION_STYLE), expressed with the fields
// /api/process and the profile store share.
export const DEFAULT_CAPTION_STYLE = {
    style: 'karaoke',
    position: 'bottom',
    font_name: 'Anton',
    font_size: 44,
    font_color: '#FFFFFF',
    highlight_color: '#FFE500',
    border_color: '#000000',
    border_width: 4,
    bg_color: '#000000',
    bg_opacity: 0,
    effect: 'pop',
    base_opacity: 1,
    uppercase: true,
    reveal: false,
    shadow: 0,
    max_chars: 16,
    max_duration: 1.4,
};

// Presets are editable looks: every field they set, the rest falls back to the
// shipped default. `oneWord` is encoded as max_chars=1, which is what the burn
// understands.
export const CAPTION_PRESETS = [
    { id: 'default', label: 'Default', style: 'karaoke', effect: 'pop', highlight_color: '#FFE500', base_opacity: 1.0, uppercase: true, font_name: 'Anton', border_width: 4, font_size: 44 },
    { id: 'hormozi', label: 'Hormozi', style: 'karaoke', effect: 'pop', highlight_color: '#FFE500', base_opacity: 1.0, uppercase: true, font_name: 'Montserrat ExtraBold', border_width: 4, shadow: 2, reveal: true, font_size: 44 },
    { id: 'pill', label: 'Pill', style: 'karaoke', effect: 'highlight', highlight_color: '#7C3AED', base_opacity: 1.0, uppercase: true, font_name: 'Montserrat ExtraBold', border_width: 3, font_size: 44 },
    { id: 'oneword', label: 'One word', style: 'karaoke', effect: 'pop', highlight_color: '#FFFFFF', base_opacity: 1.0, uppercase: true, font_name: 'Anton', border_width: 5, oneWord: true, font_size: 70 },
    { id: 'clean', label: 'Clean', style: 'karaoke', effect: 'none', highlight_color: '#FFFFFF', base_opacity: 0.7, uppercase: false, font_name: 'Montserrat ExtraBold', border_width: 0, shadow: 2, font_size: 34 },
    { id: 'lime', label: 'Lime box', style: 'karaoke', effect: 'highlight', highlight_color: '#A3FF12', base_opacity: 1.0, uppercase: true, font_name: 'Montserrat ExtraBold', border_width: 3, font_size: 44 },
    { id: 'tiktok', label: 'TikTok', style: 'karaoke', effect: 'none', highlight_color: '#FE2C55', base_opacity: 0.75, uppercase: false, font_name: 'Verdana', border_width: 2 },
    { id: 'reels', label: 'Reels', style: 'karaoke', effect: 'none', highlight_color: '#E1306C', base_opacity: 0.7, uppercase: false, font_name: 'Verdana', border_width: 2 },
    { id: 'shorts', label: 'Shorts Pop', style: 'karaoke', effect: 'pop', highlight_color: '#FF0000', base_opacity: 0.7, uppercase: false, font_name: 'Verdana', border_width: 2 },
    { id: 'gold', label: 'Gold Glow', style: 'karaoke', effect: 'glow', highlight_color: '#FFD700', base_opacity: 0.6, uppercase: false, font_name: 'Verdana', border_width: 2 },
    { id: 'neon', label: 'Neon', style: 'karaoke', effect: 'glow', highlight_color: '#00FF88', base_opacity: 0.55, uppercase: false, font_name: 'Verdana', border_width: 2 },
    { id: 'cyber', label: 'Cyber', style: 'karaoke', effect: 'glow', highlight_color: '#00FFFF', base_opacity: 0.5, uppercase: false, font_name: 'Verdana', border_width: 2 },
    { id: 'karaoke', label: 'Karaoke', style: 'karaoke', effect: 'none', highlight_color: '#FF6B6B', base_opacity: 0.6, uppercase: false, font_name: 'Verdana', border_width: 2 },
    { id: 'minimal', label: 'Minimal', style: 'karaoke', effect: 'none', highlight_color: '#FFFFFF', base_opacity: 0.65, uppercase: false, font_name: 'Verdana', border_width: 1 },
    { id: 'beast', label: 'Beast', style: 'karaoke', effect: 'pop', highlight_color: '#FFD700', base_opacity: 1.0, uppercase: true, font_name: 'Impact', border_width: 3 },
    { id: 'boxed', label: 'Boxed', style: 'karaoke', effect: 'box', highlight_color: '#7C3AED', base_opacity: 0.85, uppercase: false, font_name: 'Verdana', border_width: 2 },
    { id: 'classic', label: 'Classic', style: 'classic', effect: 'none', highlight_color: '#FFD700', base_opacity: 1.0, uppercase: false, font_name: 'Verdana', border_width: 2 },
];

export function presetToStyle(preset) {
    if (!preset) return { ...DEFAULT_CAPTION_STYLE };
    const fontSize = preset.font_size || DEFAULT_CAPTION_STYLE.font_size;
    return {
        ...DEFAULT_CAPTION_STYLE,
        style: preset.style || 'karaoke',
        effect: preset.effect || 'none',
        font_name: preset.font_name || DEFAULT_CAPTION_STYLE.font_name,
        font_size: fontSize,
        highlight_color: preset.highlight_color || DEFAULT_CAPTION_STYLE.highlight_color,
        base_opacity: preset.base_opacity ?? DEFAULT_CAPTION_STYLE.base_opacity,
        uppercase: preset.uppercase ?? DEFAULT_CAPTION_STYLE.uppercase,
        border_width: preset.border_width ?? DEFAULT_CAPTION_STYLE.border_width,
        reveal: !!preset.reveal,
        shadow: preset.shadow || 0,
        bg_opacity: 0,
        font_color: '#FFFFFF',
        max_chars: lineBudget(preset.font_name || DEFAULT_CAPTION_STYLE.font_name, fontSize, !!preset.oneWord),
    };
}

// The preset whose fields match a style, for highlighting the selected chip.
export function matchPreset(style) {
    if (!style) return null;
    const hit = CAPTION_PRESETS.find((p) => {
        const s = presetToStyle(p);
        return s.style === style.style
            && s.effect === style.effect
            && s.font_name === style.font_name
            && Number(s.font_size) === Number(style.font_size)
            && s.uppercase === !!style.uppercase
            && Number(s.base_opacity) === Number(style.base_opacity)
            && s.highlight_color === style.highlight_color
            && Number(s.border_width) === Number(style.border_width)
            && Number(s.max_chars) === Number(style.max_chars);
    });
    return hit ? hit.id : null;
}

// Mirrors subtitles._luminance (Rec. 601).
export const luminance = (hex) => {
    const m = /^#?([0-9a-fA-F]{6})$/.exec(hex || '');
    if (!m) return 1;
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16));
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255;
};

export const OUTPUT_FORMATS = [
    { id: 'vertical', label: '9:16', hint: 'Shorts · Reels · TikTok' },
    { id: 'square', label: '1:1', hint: 'Feed posts' },
    { id: 'horizontal', label: '16:9', hint: 'Keep landscape' },
];

export const HOOK_STYLES = [
    { id: 'pill', label: 'Pill' },
    { id: 'classic', label: 'Classic' },
    { id: 'dark', label: 'Dark' },
    { id: 'yellow', label: 'Yellow' },
    { id: 'red', label: 'Red' },
    { id: 'outline', label: 'Outline' },
    { id: 'outline_yellow', label: 'Outline yellow' },
];
