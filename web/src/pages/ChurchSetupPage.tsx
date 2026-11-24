import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/Button';
import { useAuth } from '@/context/AuthContext';
import { apiBase, apiJson } from '@/lib/api';

export function ChurchSetupPage() {
  const { refreshAccessFlags } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function createChurch() {
    setError(null);
    if (!name.trim()) {
      setError('Saisissez le nom de votre église.');
      return;
    }

    setBusy(true);
    try {
      const body = new FormData();
      body.append('name', name.trim());
      await apiJson(`${apiBase}/api/church/register`, { method: 'POST', body });
      await refreshAccessFlags();
      navigate('/administration');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Impossible de créer cet espace.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <main className="auth-panel" style={{ width: '100%' }}>
        <section className="auth-card">
          <p className="auth-card-kicker">Nouvel espace d’église</p>
          <h2>Créer votre espace</h2>
          <p className="auth-card-hint">
            L’abonnement coûte 20 € par mois, TVA comprise, pour 100 Go de stockage. Le paiement
            sécurisé se fait via Stripe.
          </p>
          <label className="field">
            <span>Nom de l’église</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={160}
              autoComplete="organization"
              onKeyDown={(event) => event.key === 'Enter' && void createChurch()}
            />
          </label>
          <div className="form-actions">
            <Button variant="accent" disabled={busy} onClick={() => void createChurch()}>
              {busy ? 'Création…' : 'Créer mon espace'}
            </Button>
          </div>
          {error ? <div className="message error">{error}</div> : null}
        </section>
      </main>
    </div>
  );
}
