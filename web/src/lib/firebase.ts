import { initializeApp } from 'firebase/app';
import { getAnalytics, isSupported as analyticsIsSupported } from 'firebase/analytics';
import {
  getAuth,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  signOut,
  onAuthStateChanged,
  type User,
} from 'firebase/auth';

const firebaseConfig = {
  apiKey: 'AIzaSyCfDgHVodELAgjc48FRDgSDuq7WIzs4iq0',
  authDomain: 'ondertitels-1.firebaseapp.com',
  projectId: 'ondertitels-1',
  storageBucket: 'ondertitels-1.firebasestorage.app',
  messagingSenderId: '807675502591',
  appId: '1:807675502591:web:ad229e10c84135a4dc11ca',
  measurementId: 'G-77EP76LQCE',
};

const firebaseApp = initializeApp(firebaseConfig);
void analyticsIsSupported().then((supported) => {
  if (supported) getAnalytics(firebaseApp);
}).catch(() => {});
export const auth = getAuth(firebaseApp);

export const firebaseAuthReady = new Promise<void>((resolve) => {
  const unsub = onAuthStateChanged(auth, () => {
    unsub();
    resolve();
  });
});

export async function ensureIdToken(forceRefresh = false): Promise<string | null> {
  await firebaseAuthReady;
  const user = auth.currentUser;
  if (!user) return null;
  return user.getIdToken(forceRefresh);
}

export async function signIn(email: string, password: string): Promise<User> {
  const cred = await signInWithEmailAndPassword(auth, email, password);
  return cred.user;
}

export async function signUp(email: string, password: string): Promise<User> {
  const cred = await createUserWithEmailAndPassword(auth, email, password);
  return cred.user;
}

export async function logOut(): Promise<void> {
  await signOut(auth);
}

export { onAuthStateChanged };
export type { User };
