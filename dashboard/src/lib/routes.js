// The app's pages, expressed as real URLs.
//
// The nav used to be tabs: `activeTab` state plus `#app?tab=<id>` deep links,
// which meant every page lived at `/` and a link could only carry the tab in a
// hash. Each destination now has its own path, so
// http://localhost:18481/clip-generator is the Clip Generator, a reload keeps
// the user there, and Back/Forward move between pages.
//
// Paths deliberately avoid the prefixes Vite proxies to the API (`/api`,
// `/videos`, `/thumbnails`, `/collector`, `/gallery`, `/video`, `/render`):
// a page at /collector or /video-collector would otherwise be swallowed by the
// media mount before the SPA fallback could serve it (the proxy matches by
// prefix). nginx proxies the same prefixes.
//
// This module is plain data + functions so App.jsx stays the only place that
// owns React state; tests read it directly (tests/test_nav_routes_ui.py).

export const TAB_PATHS = {
  home: '/',
  dashboard: '/clip-generator',
  gallery: '/clip-gallery',
  archive: '/archive',
  collector: '/shelf',
  downloads: '/download-manager',
  playground: '/playground',
  profiles: '/style-profiles',
  'ai-agent': '/ai-agent',
  thumbnails: '/youtube-studio',
  settings: '/settings',
};

export const DEFAULT_TAB = 'home';

// Paths that used to be pages under another name, or that people type by hand.
// Kept in one place so a shared link never lands on an empty shell.
const PATH_ALIASES = {
  '/home': 'home',
};

const PAGE_TITLES = {
  home: 'Clip Studio',
  dashboard: 'Clip Generator · Clip Studio',
  gallery: 'Clip Gallery · Clip Studio',
  archive: 'Archive · Clip Studio',
  collector: 'Collector · Clip Studio',
  downloads: 'Download Manager · Clip Studio',
  playground: 'Playground · Clip Studio',
  profiles: 'Style Profiles · Clip Studio',
  'ai-agent': 'AI Agent · Clip Studio',
  thumbnails: 'YouTube Studio · Clip Studio',
  settings: 'Settings · Clip Studio',
};

// tab id -> path. Unknown ids (an old saved session, a link from a removed
// feature) fall back to Home instead of leaving the shell blank.
export function pathForTab(tab) {
  return TAB_PATHS[tab] || TAB_PATHS[DEFAULT_TAB];
}

// pathname -> tab id. Trailing slashes are ignored so /settings/ works.
export function tabFromPath(pathname) {
  const clean = `/${String(pathname || '/').split('?')[0].split('#')[0]
    .replace(/^\/+|\/+$/g, '')}`.toLowerCase();
  if (clean === '/') return DEFAULT_TAB;
  const alias = PATH_ALIASES[clean];
  if (alias) return alias;
  for (const [tab, path] of Object.entries(TAB_PATHS)) {
    if (path.toLowerCase() === clean) return tab;
  }
  return DEFAULT_TAB;
}

// Renamed tabs that may still sit in localStorage or in an old deep link.
export function normalizeTab(tab) {
  if (tab === 'history') return 'gallery';  // the pre-redesign name of the Clip Gallery
  return TAB_PATHS[tab] ? tab : DEFAULT_TAB;
}

export function pageTitle(tab) {
  return PAGE_TITLES[normalizeTab(tab)] || PAGE_TITLES[DEFAULT_TAB];
}
