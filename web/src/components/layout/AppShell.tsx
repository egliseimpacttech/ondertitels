import { useEffect, useId, useState, type ReactNode } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  Clapperboard,
  FileAudio,
  FolderOpen,
  Languages,
  LogOut,
  Menu,
  Mic2,
  PenLine,
  Radio,
  Shield,
  Upload,
  Video,
  X,
} from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { STUDIO_TOOLS } from '@/lib/studio';
import { VIEW_PATHS, type AppView } from '@/types';
import { Button } from '@/components/ui/Button';

const NAV: { view: AppView; label: string; hint: string; icon: typeof Mic2 }[] = [
  { view: 'home', label: 'Accueil', hint: 'Studio & outils', icon: Mic2 },
  { view: 'live', label: 'Traduction live', hint: 'Micro → traduction', icon: Radio },
  { view: 'cinema', label: 'Cinéma', hint: 'Lecture & catalogue', icon: Clapperboard },
  { view: 'workspace', label: 'Espace de travail', hint: 'Édition VTT / vidéo', icon: PenLine },
  { view: 'library', label: 'Bibliothèque', hint: 'Fichiers & dossiers', icon: FolderOpen },
  { view: 'admin', label: 'Administration', hint: 'Invitations', icon: Shield },
];

const STUDIO_ICONS = {
  upload: Upload,
  transcribe: Mic2,
  translate: Languages,
  tts: FileAudio,
  burn: Video,
} as const;

function userInitials(email?: string | null) {
  if (!email) return '?';
  const local = email.split('@')[0] || email;
  const parts = local.split(/[._-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return local.slice(0, 2).toUpperCase();
}

export function AppShell({ children, cinemaMode }: { children: ReactNode; cinemaMode?: boolean }) {
  const { cinemaOnly, isAdmin, signOutUser, user } = useAuth();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const drawerTitleId = useId();

  useEffect(() => {
    document.body.classList.toggle('cinema-mode', !!cinemaMode);
    return () => document.body.classList.remove('cinema-mode');
  }, [cinemaMode]);

  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname, cinemaMode]);

  useEffect(() => {
    if (!drawerOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDrawerOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener('keydown', onKey);
    };
  }, [drawerOpen]);

  const items = NAV.filter((item) => {
    if (cinemaOnly && item.view !== 'cinema') return false;
    if (item.view === 'admin' && !isAdmin) return false;
    return true;
  });

  const onAccueilBranch = location.pathname === '/accueil' || location.pathname.startsWith('/accueil/');

  async function handleSignOut() {
    await signOutUser();
    setDrawerOpen(false);
    navigate('/');
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-inner">
          <div className="header-start">
            <button
              type="button"
              className="menu-toggle"
              aria-expanded={drawerOpen}
              aria-controls="app-drawer"
              aria-label={drawerOpen ? 'Fermer le menu' : 'Ouvrir le menu'}
              onClick={() => setDrawerOpen((v) => !v)}
            >
              {drawerOpen ? <X size={18} /> : <Menu size={18} />}
            </button>

            <NavLink
              to={cinemaOnly ? VIEW_PATHS.cinema : VIEW_PATHS.home}
              className="brand"
              onClick={() => setDrawerOpen(false)}
            >
              <span className="brand-mark">
                <img src="/brand-logo.svg" alt="" />
              </span>
              <span className="brand-text">
                <span className="brand-name">Ondertitels</span>
                <span className="brand-tag">Sous-titres automatiques</span>
              </span>
            </NavLink>
          </div>

          <nav className="nav-rail nav-desktop" aria-label="Navigation principale">
            {items.map((item) => {
              const Icon = item.icon;
              const homeActive = item.view === 'home' && onAccueilBranch;
              return (
                <NavLink
                  key={item.view}
                  to={VIEW_PATHS[item.view]}
                  end={item.view === 'home'}
                  className={({ isActive }) =>
                    `nav-link ${isActive || homeActive ? 'active' : ''}`
                  }
                >
                  <Icon size={15} strokeWidth={2.25} aria-hidden />
                  <span>{item.label}</span>
                </NavLink>
              );
            })}
          </nav>

          <div className="header-end">
            {user?.email ? (
              <div className="nav-account nav-desktop" title={user.email}>
                <span className="nav-avatar" aria-hidden>
                  {userInitials(user.email)}
                </span>
                <span className="nav-user-meta">
                  <span className="nav-user-label">Connecté</span>
                  <span className="nav-user">{user.email}</span>
                </span>
              </div>
            ) : null}

            <Button
              variant="secondary"
              size="sm"
              className="nav-desktop header-signout"
              onClick={() => void handleSignOut()}
            >
              <LogOut size={14} />
              <span>Déconnexion</span>
            </Button>
          </div>
        </div>
      </header>

      <div className={`drawer-root ${drawerOpen ? 'open' : ''}`} aria-hidden={!drawerOpen}>
        <button
          type="button"
          className="drawer-backdrop"
          aria-label="Fermer le menu"
          tabIndex={drawerOpen ? 0 : -1}
          onClick={() => setDrawerOpen(false)}
        />
        <aside
          id="app-drawer"
          className="drawer-panel"
          role="dialog"
          aria-modal="true"
          aria-labelledby={drawerTitleId}
        >
          <div className="drawer-head">
            <div className="drawer-brand">
              <span className="brand-mark">
                <img src="/brand-logo.svg" alt="" />
              </span>
              <div>
                <p id={drawerTitleId} className="drawer-title">
                  Menu
                </p>
                <p className="drawer-subtitle">Navigation Ondertitels</p>
              </div>
            </div>
            <button
              type="button"
              className="drawer-close"
              aria-label="Fermer"
              onClick={() => setDrawerOpen(false)}
            >
              <X size={18} />
            </button>
          </div>

          {user?.email ? (
            <div className="drawer-user">
              <span className="nav-avatar">{userInitials(user.email)}</span>
              <div className="drawer-user-meta">
                <span className="nav-user-label">Connecté</span>
                <span className="drawer-user-email">{user.email}</span>
              </div>
            </div>
          ) : null}

          <nav className="drawer-nav" aria-label="Menu mobile">
            {items.map((item) => {
              const Icon = item.icon;
              const isHome = item.view === 'home';
              return (
                <div key={item.view} className={isHome ? 'drawer-group' : undefined}>
                  <NavLink
                    to={VIEW_PATHS[item.view]}
                    end={isHome}
                    className={({ isActive }) =>
                      `drawer-link ${isActive || (isHome && location.pathname === '/accueil') ? 'active' : ''}`
                    }
                    onClick={() => setDrawerOpen(false)}
                    tabIndex={drawerOpen ? 0 : -1}
                  >
                    <span className="drawer-link-icon">
                      <Icon size={18} strokeWidth={2.2} />
                    </span>
                    <span className="drawer-link-text">
                      <span className="drawer-link-label">{item.label}</span>
                      <span className="drawer-link-hint">{item.hint}</span>
                    </span>
                  </NavLink>

                  {isHome && !cinemaOnly ? (
                    <div className="drawer-subnav" role="group" aria-label="Outils Accueil">
                      {STUDIO_TOOLS.map((tool) => {
                        const SubIcon = STUDIO_ICONS[tool.id];
                        return (
                          <NavLink
                            key={tool.id}
                            to={tool.path}
                            className={({ isActive }) =>
                              `drawer-sublink ${isActive ? 'active' : ''}`
                            }
                            onClick={() => setDrawerOpen(false)}
                            tabIndex={drawerOpen ? 0 : -1}
                          >
                            <SubIcon size={15} strokeWidth={2.2} aria-hidden />
                            <span>{tool.title}</span>
                          </NavLink>
                        );
                      })}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </nav>

          <div className="drawer-foot">
            <button
              type="button"
              className="drawer-signout"
              tabIndex={drawerOpen ? 0 : -1}
              onClick={() => void handleSignOut()}
            >
              <LogOut size={17} />
              Déconnexion
            </button>
          </div>
        </aside>
      </div>

      {children}
    </div>
  );
}
