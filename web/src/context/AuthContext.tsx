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

type AuthContextValue = {
  user: User | null;
  ready: boolean;
  isAdmin: boolean;
  cinemaOnly: boolean;
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

  const refreshAccessFlags = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase}/api/library?path=`);
      if (res.status === 403) {
        setCinemaOnly(true);
        setIsAdmin(false);
        return;
      }
      setCinemaOnly(false);
      try {
        const adminRes = await apiFetch(`${apiBase}/api/admin/status`);
        const adminData = await adminRes.json().catch(() => ({}));
        setIsAdmin(!!adminData.is_admin);
      } catch {
        setIsAdmin(false);
      }
    } catch {
      /* keep current flags on transient errors */
    }
  }, []);

  useEffect(() => {
    let unsub = () => {};
    void (async () => {
      await firebaseAuthReady;
      unsub = onAuthStateChanged(auth, async (u) => {
        setUser(u);
        if (u) await refreshAccessFlags();
        else {
          setIsAdmin(false);
          setCinemaOnly(false);
        }
        setReady(true);
      });
    })();
    return () => unsub();
  }, [refreshAccessFlags]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      ready,
      isAdmin,
      cinemaOnly,
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
    [user, ready, isAdmin, cinemaOnly, refreshAccessFlags],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
