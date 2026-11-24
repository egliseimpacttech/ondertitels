import { initializeApp } from 'firebase/app';
import { getAnalytics, isSupported as analyticsIsSupported } from 'firebase/analytics';
import {
  getAuth,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  sendEmailVerification,
  signOut,
  onAuthStateChanged,
  type User,
} from 'firebase/auth';

const firebaseApiKey = import.meta.env.VITE_FIREBASE_CONFIG_API_KEY;
if (!firebaseApiKey) {
  throw new Error('Set VITE_FIREBASE_CONFIG_API_KEY before building or starting the frontend.');
}

const firebaseConfig = {
  apiKey: firebaseApiKey,
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
  if (!cred.user.emailVerified) {
    try {
      await sendEmailVerification(cred.user);
    } finally {
      await signOut(auth);
    }
    throw new Error('Vérifiez votre adresse e-mail. Un nouveau lien de confirmation vient de vous être envoyé.');
  }
  return cred.user;
}

export async function signUp(email: string, password: string): Promise<User> {
  const cred = await createUserWithEmailAndPassword(auth, email, password);
  try {
    await sendEmailVerification(cred.user);
  } finally {
    await signOut(auth);
  }
  return cred.user;
}

export async function logOut(): Promise<void> {
  await signOut(auth);
}

export { onAuthStateChanged };
export type { User };
