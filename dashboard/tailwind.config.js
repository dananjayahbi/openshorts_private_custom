/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Lumen · Night Foundry — values mirror tokens.css (kept literal so
        // Tailwind alpha modifiers like bg-brass/10 compile)
        paper: "oklch(14.5% 0.004 264 / <alpha-value>)",
        paper2: "oklch(17.5% 0.005 264 / <alpha-value>)",
        paper3: "oklch(21% 0.007 264 / <alpha-value>)",
        ink: "oklch(94% 0.004 264 / <alpha-value>)",
        ink2: "oklch(85% 0.006 264 / <alpha-value>)",
        muted: "oklch(67% 0.012 264 / <alpha-value>)",
        brass: "oklch(72% 0.19 47 / <alpha-value>)",
        brassink: "oklch(18% 0.03 47 / <alpha-value>)",
        coral: "oklch(66% 0.17 32 / <alpha-value>)",
        ok: "oklch(75% 0.14 155 / <alpha-value>)",
        warn: "oklch(80% 0.14 78 / <alpha-value>)",
        danger: "oklch(65% 0.19 25 / <alpha-value>)",
        // legacy aliases so untouched files degrade gracefully
        background: "oklch(14.5% 0.004 264 / <alpha-value>)",
        surface: "oklch(17.5% 0.005 264 / <alpha-value>)",
        primary: "oklch(72% 0.19 47 / <alpha-value>)",
        accent: "oklch(66% 0.17 32 / <alpha-value>)",
      },
      fontFamily: {
        display: "var(--font-display)",
        body: "var(--font-body)",
        sans: "var(--font-body)",
        serif: "var(--font-display)",
        mono: "var(--font-mono)",
      },
      borderColor: {
        rule: "var(--color-rule)",
        rule2: "var(--color-rule-2)",
      },
      borderRadius: {
        card: "var(--radius-card)",
        input: "var(--radius-input)",
      },
      fontSize: {
        micro: ["10.5px", { letterSpacing: "0.10em" }],
      },
      transitionTimingFunction: {
        out: "var(--ease-out)",
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade': 'fadeIn 0.4s var(--ease-out)',
        // mobile shell: the nav drawer flies in from the edge, sheets rise
        'slide-in-left': 'slideInLeft 0.24s var(--ease-out)',
        'sheet-up': 'sheetUp 0.26s var(--ease-out)',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        slideInLeft: {
          from: { transform: 'translateX(-100%)' },
          to: { transform: 'translateX(0)' },
        },
        sheetUp: {
          from: { transform: 'translateY(12px)', opacity: '0' },
          to: { transform: 'translateY(0)', opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
