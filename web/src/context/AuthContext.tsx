import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import {
  auth,
  firebaseAuthReady,
  logOut,
  onAuthStateChanged,
  signIn,
  signUp,
  type User,
} from '@/lib/firebase';
import { apiFetch, apiBase } from '@/lib/api';

export type Church = {
  id: string;
  name: string;
  plan: 'free' | 'paid';
  subscription_status: string;
  storage_limit_bytes: number | null;
  has_billing_subscription?: boolean;
};

export type StorageBackend = 'gcs' | 'local' | 'local_fallback';

type AuthContextValue = {
  user: User | null;
  ready: boolean;
  isAdmin: boolean;
  cinemaOnly: boolean;
  church: Church | null;
  storageUsedBytes: number;
  storageBackend: StorageBackend;
  storageWarning: string;
  accessError: string | null;
  signInEmail: (email: string, password: string) => Promise<void>;
  signUpEmail: (email: string, password: string) => Promise<void>;
  signOutUser: () => Promise<void>;
  refreshAccessFlags: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [cinemaOnly, setCinemaOnly] = useState(false);
  const [church, setChurch] = useState<Church | null>(null);
  const [storageUsedBytes, setStorageUsedBytes] = useState(0);
  const [storageBackend, setStorageBackend] = useState<StorageBackend>('local');
  const [storageWarning, setStorageWarning] = useState('');
  const [accessError, setAccessError] = useState<string | null>(null);

  const refreshAccessFlags = useCallback(async () => {
    setAccessError(null);
    try {
      const res = await apiFetch(`${apiBase}/api/tenant/status`);
      if (res.status === 403) {
        setCinemaOnly(true);
        setIsAdmin(false);
        setChurch(null);
        const data = (await res.json().catch(() => ({}))) as { detail?: string };
        setAccessError(data.detail || 'Impossible de vérifier l’accès à votre espace.');
        return;
      }
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(data.detail || `Impossible de charger l’espace (${res.status}).`);
      }
      const data = (await res.json()) as {
        church: Church | null;
        is_admin: boolean;
        storage_used_bytes: number;
        storage_backend?: StorageBackend;
        storage_warning?: string;
      };
      setCinemaOnly(false);
      setChurch(data.church);
      setStorageUsedBytes(data.storage_used_bytes || 0);
      setStorageBackend(data.storage_backend || 'local');
      setStorageWarning(data.storage_warning || '');
      setIsAdmin(!!data.is_admin);
    } catch (e) {
      setAccessError(
        e instanceof Error ? e.message : 'Impossible de vérifier l’accès à votre espace.',
      );
    }
  }, []);

  useEffect(() => {
    let unsub = () => {};
    let authChangeId = 0;
    let disposed = false;
    void (async () => {
      await firebaseAuthReady;
      if (disposed) return;
      unsub = onAuthStateChanged(auth, async (u) => {
        const changeId = ++authChangeId;
        setReady(false);
        setUser(u);
        if (u) {
          try {
            await u.getIdToken(true);
            if (changeId !== authChangeId || auth.currentUser?.uid !== u.uid) return;
            await refreshAccessFlags();
          } catch (e) {
            if (changeId === authChangeId) {
              setAccessError(
                e instanceof Error ? e.message : 'Impossible de vérifier l’accès à votre espace.',
              );
            }
          }
        } else {
          setIsAdmin(false);
          setCinemaOnly(false);
          setChurch(null);
          setStorageUsedBytes(0);
          setStorageBackend('local');
          setStorageWarning('');
          setAccessError(null);
        }
        if (changeId === authChangeId) setReady(true);
      });
    })();
    return () => {
      disposed = true;
      authChangeId += 1;
      unsub();
    };
  }, [refreshAccessFlags]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      ready,
      isAdmin,
      cinemaOnly,
      church,
      storageUsedBytes,
      storageBackend,
      storageWarning,
      accessError,
      signInEmail: async (email, password) => {
        await signIn(email, password);
      },
      signUpEmail: async (email, password) => {
        await signUp(email, password);
      },
      signOutUser: async () => {
        await logOut();
      },
      refreshAccessFlags,
    }),
    [
      user,
      ready,
      isAdmin,
      cinemaOnly,
      church,
      storageUsedBytes,
      storageBackend,
      storageWarning,
      accessError,
      refreshAccessFlags,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
