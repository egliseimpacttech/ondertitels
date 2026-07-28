import { initializeApp } from 'firebase/app';
import {
  getAuth,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  signOut,
  onAuthStateChanged,
  type User,
} from 'firebase/auth';

const firebaseConfig = {
  apiKey: 'AIzaSyCqd17ac8mHZkRUDi0G85P6zjuzSG3ktd8',
  authDomain: 'itech-workspace-8da4f.firebaseapp.com',
  projectId: 'itech-workspace-8da4f',
  storageBucket: 'itech-workspace-8da4f.firebasestorage.app',
  messagingSenderId: '512996235945',
  appId: '1:512996235945:web:792379ec240fbed8e427b8',
  measurementId: 'G-N3B77WJGMH',
};

const firebaseApp = initializeApp(firebaseConfig);
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
