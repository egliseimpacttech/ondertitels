import { useState } from 'react';
import { motion } from 'framer-motion';
import { useAuth } from '@/context/AuthContext';
import { Button } from '@/components/ui/Button';

export function AuthPage() {
  const { signInEmail, signUpEmail } = useAuth();
  const [tab, setTab] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  async function submit() {
    setError(null);
    setInfo(null);
    if (!email.trim() || !password) {
      setError('Saisissez l’e-mail et le mot de passe.');
      return;
    }
    setBusy(true);
    try {
      if (tab === 'login') await signInEmail(email.trim(), password);
      else {
        await signUpEmail(email.trim(), password);
        setInfo('Compte créé. Vérifiez le lien envoyé par e-mail, puis connectez-vous.');
      }
    } catch (e) {
      const err = e as { code?: string; message?: string };
      setError(
        `${tab === 'login' ? 'Échec de la connexion' : 'Échec de l’inscription'}${
          err.code ? ` (${err.code})` : ''
        }${err.message ? ` — ${err.message}` : ''}`,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <aside className="auth-visual" aria-hidden={false}>
        <div className="auth-orb auth-orb--a" aria-hidden />
        <div className="auth-orb auth-orb--b" aria-hidden />
        <div className="auth-ripple" aria-hidden>
          <span />
          <span />
          <span />
        </div>

        <motion.div
          className="auth-visual-inner"
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
        >
          <div className="auth-brand-block">
            <img className="auth-logo" src="/brand-logo.svg" alt="" />
            <p className="auth-brand-mark">Ondertitels</p>
            <h1>Du sermon à l’écran</h1>
            <p className="auth-lead">
              Sous-titres multilingues, édition et diffusion — un seul espace de travail.
            </p>
          </div>
        </motion.div>
      </aside>

      <main className="auth-panel">
        <motion.div
          className="auth-card"
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, delay: 0.08, ease: [0.22, 1, 0.36, 1] }}
        >
          <p className="auth-card-kicker">Espace sécurisé</p>
          <h2>{tab === 'login' ? 'Connexion' : 'Créer un compte'}</h2>
          <p className="auth-card-hint">
            {tab === 'login'
              ? 'Entrez vos identifiants pour continuer.'
              : 'Choisissez un e-mail et un mot de passe (min. 6 caractères).'}
          </p>

          <div className="auth-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'login'}
              className={`auth-tab ${tab === 'login' ? 'active' : ''}`}
              onClick={() => setTab('login')}
            >
              Connexion
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'register'}
              className={`auth-tab ${tab === 'register' ? 'active' : ''}`}
              onClick={() => setTab('register')}
            >
              Créer un compte
            </button>
          </div>

          <label className="field">
            <span>E-mail</span>
            <input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="nom@exemple.com"
            />
          </label>
          <label className="field">
            <span>Mot de passe</span>
            <input
              type="password"
              autoComplete={tab === 'login' ? 'current-password' : 'new-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              onKeyDown={(e) => e.key === 'Enter' && void submit()}
            />
          </label>

          <div className="form-actions">
            <Button
              variant="accent"
              disabled={busy}
              onClick={() => void submit()}
              style={{ width: '100%' }}
            >
              {busy ? 'Patientez…' : tab === 'login' ? 'Se connecter' : 'Créer mon compte'}
            </Button>
          </div>

          {error ? <div className="message error">{error}</div> : null}
          {info ? <div className="message">{info}</div> : null}
        </motion.div>
      </main>
    </div>
  );
}
