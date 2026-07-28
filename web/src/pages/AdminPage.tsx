import { useState } from 'react';
import { apiBase, apiJson } from '@/lib/api';
import { Button } from '@/components/ui/Button';

export function AdminPage() {
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState<string | null>(null);
  const [invited, setInvited] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function invite() {
    setError(null);
    setLink(null);
    setInvited(null);
    if (!email.trim()) {
      setError('Saisissez une adresse e-mail.');
      return;
    }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('email', email.trim());
      const data = await apiJson<{ email?: string; password_reset_link?: string }>(
        `${apiBase}/api/admin/invite`,
        { method: 'POST', body: fd },
      );
      setInvited(data.email || email.trim());
      setLink(data.password_reset_link || '');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Invitation échouée');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h1 style={{ marginTop: 0 }}>Administration</h1>
      <p style={{ color: 'rgba(12,22,18,0.65)' }}>
        Créez des comptes et partagez un lien de réinitialisation du mot de passe.
      </p>
      <section className="panel">
        <div className="panel-title">Inviter un utilisateur</div>
        <label className="field">
          <span>E-mail</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="utilisateur@exemple.com"
          />
        </label>
        <div className="form-actions">
          <Button disabled={busy} onClick={() => void invite()}>
            {busy ? 'Génération…' : 'Générer le lien de réinitialisation'}
          </Button>
        </div>
        {error ? <div className="message error">{error}</div> : null}
        {link != null ? (
          <div className="message">
            <div>
              <b>Utilisateur :</b> {invited}
            </div>
            <div style={{ marginTop: 8 }}>
              <b>Lien de réinitialisation :</b>
            </div>
            <textarea rows={3} readOnly value={link} style={{ marginTop: 6, width: '100%' }} />
            <div className="file-info">
              Copiez ce lien et envoyez-le à l’utilisateur. Il définit son mot de passe puis se
              connecte.
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
