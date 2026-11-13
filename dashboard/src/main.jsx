import { StrictMode, lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { AuthProvider } from './contexts/AuthContext'
import { capture as captureAttribution } from './lib/attribution'

const App = lazy(() => import('./App.jsx'))

// A private local build has exactly one surface: the app. Old bookmarks
// (#legal, #landing, #/pricing) all resolve here instead of a marketing or
// legal page that belongs to the hosted product.
function Root() {
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

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <Root />
    </AuthProvider>
  </StrictMode>,
)
