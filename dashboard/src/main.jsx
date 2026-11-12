import { StrictMode, lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { AuthProvider } from './contexts/AuthContext'
import { capture as captureAttribution } from './lib/attribution'
import { applyConsent } from './lib/consent'
import CookieBanner from './components/CookieBanner'

const App = lazy(() => import('./App.jsx'))
const Legal = lazy(() => import('./Legal.jsx'))

// No marketing surface in this fork: `/` and `#app` both land in the app, and
// every other hash (an old bookmark, the landing anchors that used to exist)
// resolves there too. Keeping a landing route meant a private install opened
// on a sales page for a product it is not running.
function Root() {
  const view = window.location.hash === '#legal' ? 'legal' : 'app'
  if (view === 'legal') return <Legal />

  return (
    <Suspense fallback={
      <div className="min-h-screen bg-paper flex items-center justify-center text-muted text-sm lowercase">
        loading…
      </div>
    }>
      <App />
    </Suspense>
  )
}

// Before React mounts: captures the referrer and UTM params the app would
// otherwise lose on its first history change.
captureAttribution()

// Start whatever the visitor previously agreed to. Nothing at all on a first
// visit: index.html only publishes the analytics initialiser, it never runs it.
applyConsent()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <Root />
      <CookieBanner />
    </AuthProvider>
  </StrictMode>,
)
