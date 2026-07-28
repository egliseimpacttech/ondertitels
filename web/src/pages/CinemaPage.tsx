import { useCallback, useEffect, useMemo, useState } from 'react';
import { ensureIdToken } from '@/lib/firebase';
import { apiBase, apiFetch, apiJson } from '@/lib/api';
import type { CinemaCatalog, CinemaItem } from '@/types';
import { Button } from '@/components/ui/Button';

async function loadCoverUrl(coverPath?: string): Promise<string | null> {
  if (!coverPath) return null;
  try {
    const res = await apiFetch(`${apiBase}${coverPath}`);
    if (!res.ok) return null;
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  } catch {
    return null;
  }
}

function CinemaThumb({ item }: { item: CinemaItem }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    let objectUrl: string | null = null;
    void (async () => {
      objectUrl = await loadCoverUrl(item.cover_url);
      if (alive) setUrl(objectUrl);
    })();
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [item.cover_url]);

  const icon = item.kind === 'ebook' ? '📖' : item.kind === 'audio' ? '🎵' : '▶';
  return (
    <div className="cinema-thumb">
      {url ? <img src={url} alt="" /> : <span style={{ fontSize: '1.4rem', opacity: 0.7 }}>{icon}</span>}
    </div>
  );
}

export function CinemaPage() {
  const [catalog, setCatalog] = useState<CinemaCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [featuredId, setFeaturedId] = useState('');
  const [lang, setLang] = useState('nl');
  const [heroCover, setHeroCover] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await apiJson<CinemaCatalog>(`${apiBase}/api/cinema/catalog`);
      setCatalog(data);
      const all = [
        ...(data.featured ? [data.featured] : []),
        ...(data.videos || []),
        ...(data.ebooks || []),
        ...(data.audios || []),
      ];
      setFeaturedId((prev) => {
        if (prev && all.some((x) => x.id === prev)) return prev;
        return data.featured?.id || all[0]?.id || '';
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const allItems = useMemo(() => {
    if (!catalog) return [] as CinemaItem[];
    const map = new Map<string, CinemaItem>();
    for (const x of [
      ...(catalog.featured ? [catalog.featured] : []),
      ...(catalog.videos || []),
      ...(catalog.ebooks || []),
      ...(catalog.audios || []),
    ]) {
      if (x?.id) map.set(x.id, x);
    }
    return Array.from(map.values());
  }, [catalog]);

  const featured = allItems.find((x) => x.id === featuredId) || allItems[0] || null;

  useEffect(() => {
    let alive = true;
    let objectUrl: string | null = null;
    void (async () => {
      objectUrl = await loadCoverUrl(featured?.cover_url);
      if (alive) setHeroCover(objectUrl);
    })();
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [featured?.cover_url, featured?.id]);

  useEffect(() => {
    const first = featured?.languages?.[0]?.code;
    setLang(first || 'none');
  }, [featured?.id, featured?.languages]);

  async function watch(item: CinemaItem, langCode: string) {
    const tok = await ensureIdToken();
    if (!tok) {
      alert('Connexion requise');
      return;
    }
    const kind = item.kind || 'video';
    if (kind === 'ebook') {
      window.open(`${apiBase}/api/cinema/read/${encodeURIComponent(item.id)}?token=${encodeURIComponent(tok)}`, '_blank');
      return;
    }
    if (kind === 'audio') {
      window.open(
        `${apiBase}/api/cinema/listen/${encodeURIComponent(item.id)}?token=${encodeURIComponent(tok)}`,
        '_blank',
      );
      return;
    }
    const q = new URLSearchParams();
    q.set('lang', langCode === 'none' ? 'none' : langCode || 'nl');
    q.set('token', tok);
    window.location.href = `${apiBase}/api/cinema/watch/${encodeURIComponent(item.id)}?${q.toString()}`;
  }

  const videos = catalog?.videos || [];
  const ebooks = catalog?.ebooks || [];
  const audios = catalog?.audios || [];

  return (
    <div className="page page--cinema">
      {error ? <div className="message error" style={{ margin: 24 }}>{error}</div> : null}
      {!catalog && !error ? <div className="empty-msg">Chargement du Cinéma…</div> : null}

      {featured ? (
        <section className="cinema-hero">
          <div className="cinema-hero-bg">{heroCover ? <img src={heroCover} alt="" /> : null}</div>
          <div className="cinema-hero-content">
            <span className="cinema-kicker">À la une</span>
            <h2>{featured.title || featured.name}</h2>
            <p>{featured.description || 'Contenu publié dans votre bibliothèque cinéma.'}</p>
            <div className="cinema-hero-actions">
              {(featured.kind || 'video') === 'video' ? (
                <label style={{ display: 'grid', gap: 6, fontSize: '0.82rem' }}>
                  Langue des sous-titres
                  <select
                    className="cinema-lang-select"
                    value={lang}
                    onChange={(e) => setLang(e.target.value)}
                  >
                    {(featured.languages || []).length === 0 ? (
                      <option value="none">Aucun sous-titre</option>
                    ) : (
                      (featured.languages || []).map((L) => (
                        <option key={L.code} value={L.code}>
                          {L.name}
                        </option>
                      ))
                    )}
                  </select>
                </label>
              ) : null}
              <Button variant="accent" onClick={() => void watch(featured, lang)}>
                {(featured.kind || 'video') === 'audio'
                  ? 'Lire l’audio'
                  : (featured.kind || 'video') === 'ebook'
                    ? 'Lire le texte'
                    : 'Lire'}
              </Button>
            </div>
          </div>
        </section>
      ) : catalog ? (
        <div className="cinema-empty empty-msg">Aucun contenu publié dans le Cinéma pour le moment.</div>
      ) : null}

      <div className="cinema-rows">
        {[
          { title: 'Vidéos', items: videos },
          { title: 'E-books', items: ebooks },
          { title: 'Audios', items: audios },
        ].map((row) =>
          row.items.length ? (
            <section key={row.title}>
              <h3 className="cinema-row-title">{row.title}</h3>
              <div className="cinema-scroller">
                {row.items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className="cinema-tile"
                    onClick={() => setFeaturedId(item.id)}
                  >
                    <CinemaThumb item={item} />
                    <div className="cinema-tile-title">{item.title || item.name}</div>
                  </button>
                ))}
              </div>
            </section>
          ) : null,
        )}
      </div>
    </div>
  );
}
