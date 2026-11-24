import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from '@/context/AuthContext';
import { AppShell } from '@/components/layout/AppShell';
import { AuthPage } from '@/pages/AuthPage';
import { HomePage } from '@/pages/HomePage';
import { LiveTranslatePage } from '@/pages/LiveTranslatePage';
import { CinemaPage } from '@/pages/CinemaPage';
import { WorkspacePage } from '@/pages/WorkspacePage';
import { LibraryPage } from '@/pages/LibraryPage';
import { AdminPage } from '@/pages/AdminPage';
import { ChurchSetupPage } from '@/pages/ChurchSetupPage';
import { StudioUploadPage } from '@/pages/studio/StudioUploadPage';
import { StudioTranscribePage } from '@/pages/studio/StudioTranscribePage';
import { StudioTranslatePage } from '@/pages/studio/StudioTranslatePage';
import { StudioTtsPage } from '@/pages/studio/StudioTtsPage';
import { StudioBurnPage } from '@/pages/studio/StudioBurnPage';
import { Button } from '@/components/ui/Button';
import { useEffect, useState } from 'react';

function StartupSplash({ show }: { show: boolean }) {
  const [mounted, setMounted] = useState(show);
  useEffect(() => {
    if (show) setMounted(true);
    else {
      const t = window.setTimeout(() => setMounted(false), 350);
      return () => window.clearTimeout(t);
    }
  }, [show]);
  if (!mounted) return null;
  return (
    <div className={`startup-splash ${show ? '' : 'hidden'}`}>
      <div className="startup-inner">
        <img className="startup-logo" src="/brand-logo.svg" alt="" />
        <div className="startup-brand">Ondertitels</div>
        <div className="startup-spinner" />
      </div>
    </div>
  );
}

function ProtectedApp() {
  const { user, ready, cinemaOnly, church, accessError, refreshAccessFlags } = useAuth();
  const location = useLocation();

  if (!ready) return <StartupSplash show />;
  if (!user) {
    return (
      <>
        <StartupSplash show={false} />
        <AuthPage />
      </>
    );
  }

  if (accessError) {
    return (
      <div className="auth-page">
        <main className="auth-panel" style={{ width: '100%' }}>
          <section className="auth-card">
            <h2>Accès indisponible</h2>
            <p className="auth-card-hint">{accessError}</p>
            <Button onClick={() => void refreshAccessFlags()}>Réessayer</Button>
          </section>
        </main>
      </div>
    );
  }

  if (!church) return <ChurchSetupPage />;

  if (cinemaOnly && !location.pathname.startsWith('/cinema')) {
    return <Navigate to="/cinema" replace />;
  }

  const cinemaMode = location.pathname.startsWith('/cinema');
  const subscriptionInactive =
    church.plan !== 'free' &&
    church.subscription_status !== 'active' &&
    church.subscription_status !== 'trialing';

  if (subscriptionInactive) {
    return (
      <AppShell cinemaMode={false}>
        <AdminPage />
      </AppShell>
    );
  }

  return (
    <>
      <StartupSplash show={false} />
      <AppShell cinemaMode={cinemaMode}>
        <Routes>
          <Route path="/" element={<Navigate to={cinemaOnly ? '/cinema' : '/accueil'} replace />} />
          <Route path="/accueil" element={<HomePage />} />
          <Route path="/accueil/envoyer" element={<StudioUploadPage />} />
          <Route path="/accueil/transcription" element={<StudioTranscribePage />} />
          <Route path="/accueil/traduire" element={<StudioTranslatePage />} />
          <Route path="/accueil/voix" element={<StudioTtsPage />} />
          <Route path="/accueil/incrustation" element={<StudioBurnPage />} />
          <Route path="/traduction-live" element={<LiveTranslatePage />} />
          <Route path="/cinema" element={<CinemaPage />} />
          <Route path="/workspace" element={<WorkspacePage />} />
          <Route path="/bibliotheque" element={<LibraryPage />} />
          <Route path="/administration" element={<AdminPage />} />
          <Route path="*" element={<Navigate to={cinemaOnly ? '/cinema' : '/accueil'} replace />} />
        </Routes>
      </AppShell>
    </>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <ProtectedApp />
    </AuthProvider>
  );
}
