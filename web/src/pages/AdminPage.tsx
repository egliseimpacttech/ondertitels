import { useCallback, useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Button } from '@/components/ui/Button';
import { useAuth } from '@/context/AuthContext';
import { apiBase, apiJson } from '@/lib/api';

type Member = { email: string; role: string };

function formatStorage(bytes: number) {
  return `${(bytes / 1_000_000_000).toFixed(2)} Go`;
}

export function AdminPage() {
  const { church, isAdmin, storageUsedBytes, refreshAccessFlags } = useAuth();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [members, setMembers] = useState<Member[]>([]);
  const [busy, setBusy] = useState(false);
  const [billingBusy, setBillingBusy] = useState(false);
  const [link, setLink] = useState<string | null>(null);
  const [verificationLink, setVerificationLink] = useState<string | null>(null);
  const [invited, setInvited] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadMembers = useCallback(async () => {
    if (!church || !isAdmin) return;
    const data = await apiJson<{ members: Member[] }>(`${apiBase}/api/admin/members`);
    setMembers(data.members);
  }, [church, isAdmin]);

  useEffect(() => {
    const checkoutSucceeded = new URLSearchParams(location.search).get('checkout') === 'success';
    const active = church?.plan === 'free' ||
      church?.subscription_status === 'active' ||
      church?.subscription_status === 'trialing';
    if (!checkoutSucceeded || active) return;

    let cancelled = false;
    let timeout: number | undefined;
    let attempts = 0;
    const refresh = async () => {
      await refreshAccessFlags();
      attempts += 1;
      if (!cancelled && attempts < 8) timeout = window.setTimeout(refresh, 2000);
    };
    void refresh();
    return () => {
      cancelled = true;
      if (timeout !== undefined) window.clearTimeout(timeout);
    };
  }, [church?.plan, church?.subscription_status, location.search, refreshAccessFlags]);

  useEffect(() => {
    void loadMembers().catch((e: unknown) => {
      setError(e instanceof Error ? e.message : 'Impossible de charger les membres.');
    });
  }, [loadMembers]);

  async function invite() {
    setError(null);
    setLink(null);
    setVerificationLink(null);
    setInvited(null);
    if (!email.trim()) {
      setError('Saisissez une adresse e-mail.');
      return;
    }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('email', email.trim());
      const data = await apiJson<{
        email?: string;
        password_reset_link?: string;
        email_verification_link?: string | null;
      }>(
        `${apiBase}/api/admin/invite`,
        { method: 'POST', body: fd },
      );
      setInvited(data.email || email.trim());
      setLink(data.password_reset_link || '');
      setVerificationLink(data.email_verification_link || null);
      setEmail('');
      await loadMembers();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Échec de l’invitation.');
    } finally {
      setBusy(false);
    }
  }

  async function removeMember(memberEmail: string) {
    setError(null);
    try {
      await apiJson(`${apiBase}/api/admin/members/${encodeURIComponent(memberEmail)}`, {
        method: 'DELETE',
      });
      await loadMembers();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Impossible de retirer ce membre.');
    }
  }

  async function manageBilling() {
    setError(null);
    setBillingBusy(true);
    try {
      const endpoint = church?.has_billing_subscription ? 'portal' : 'checkout';
      const data = await apiJson<{ url: string }>(`${apiBase}/api/billing/${endpoint}`, {
        method: 'POST',
      });
      window.location.assign(data.url);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Impossible d’ouvrir Stripe.');
    } finally {
      setBillingBusy(false);
    }
  }

  if (!church) return null;

  const unlimited = church.plan === 'free' || church.storage_limit_bytes == null;
  const storageLimit = church.storage_limit_bytes ?? 0;
  const storagePercent = unlimited
    ? 0
    : Math.min(100, (storageUsedBytes / Math.max(storageLimit, 1)) * 100);
  const isActive = unlimited || ['active', 'trialing'].includes(church.subscription_status);
  const paymentConfirming =
    new URLSearchParams(location.search).get('checkout') === 'success' && !isActive;

  return (
    <div className="page">
      <h1 style={{ marginTop: 0 }}>Administration</h1>
      <section className="panel">
        <div className="panel-title">{church.name}</div>
        <p>
          {church.plan === 'free'
            ? 'Accès gratuit réservé à Ministère Apostolique Impact.'
            : `Abonnement : 20 € par mois, TVA comprise — ${church.subscription_status}.`}
        </p>
        <p>
          Stockage : {formatStorage(storageUsedBytes)} /{' '}
          {unlimited ? 'illimité' : formatStorage(storageLimit)}
        </p>
        {!unlimited ? (
          <div
            role="progressbar"
            aria-label="Utilisation du stockage"
            aria-valuenow={Math.round(storagePercent)}
            aria-valuemin={0}
            aria-valuemax={100}
            style={{ height: 8, background: 'rgba(12,22,18,0.12)', borderRadius: 8 }}
          >
            <div
              style={{
                width: `${storagePercent}%`,
                height: '100%',
                background: storagePercent >= 90 ? '#b93838' : '#2f9a72',
                borderRadius: 8,
              }}
            />
          </div>
        ) : null}
        {paymentConfirming ? (
          <div className="message">
            Paiement reçu. Vérification de l’abonnement en cours…
          </div>
        ) : null}
        {church.plan !== 'free' && isAdmin ? (
          paymentConfirming ? null : (
            <div className="form-actions">
              <Button disabled={billingBusy} onClick={() => void manageBilling()}>
                {billingBusy
                  ? 'Ouverture de Stripe…'
                  : church.has_billing_subscription
                    ? 'Gérer le paiement dans Stripe'
                    : 'Payer 20 € / mois avec Stripe'}
              </Button>
            </div>
          )
        ) : null}
        {!isActive && !isAdmin ? (
          <div className="message error">
            L’abonnement de votre église n’est pas actif. Contactez son administrateur.
          </div>
        ) : null}
      </section>

      {isAdmin ? (
        <section className="panel">
          <div className="panel-title">Accès de l’église</div>
          <p>Ajoutez les adresses autorisées à utiliser cet espace.</p>
          <label className="field">
            <span>E-mail</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="utilisateur@exemple.com"
            />
          </label>
          <div className="form-actions">
            <Button disabled={busy || !isActive} onClick={() => void invite()}>
              {busy ? 'Envoi…' : 'Autoriser et inviter'}
            </Button>
          </div>
          {members.length ? (
            <ul>
              {members.map((member) => (
                <li key={member.email}>
                  {member.email} — {member.role}
                  {member.role !== 'admin' ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => void removeMember(member.email)}
                    >
                      Retirer
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
          {invited ? (
            <div className="message">
              <b>Utilisateur :</b> {invited}
              <div style={{ marginTop: 8 }}>
                <b>Lien pour définir son mot de passe :</b>
              </div>
              <textarea rows={3} readOnly value={link || ''} style={{ marginTop: 6, width: '100%' }} />
              {verificationLink ? (
                <>
                  <div style={{ marginTop: 8 }}>
                    <b>Lien pour confirmer son adresse e-mail :</b>
                  </div>
                  <textarea
                    rows={3}
                    readOnly
                    value={verificationLink}
                    style={{ marginTop: 6, width: '100%' }}
                  />
                </>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}
      {error ? <div className="message error">{error}</div> : null}
      <Button
        variant="secondary"
        size="sm"
        onClick={() => void refreshAccessFlags()}
        style={{ marginTop: 12 }}
      >
        Actualiser le statut
      </Button>
    </div>
  );
}
