const isLocalhost =
  location.hostname === '127.0.0.1' || location.hostname === 'localhost';

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    if (import.meta.env.PROD && !isLocalhost) {
      void navigator.serviceWorker.register('/sw.js');
      return;
    }
    void navigator.serviceWorker.getRegistrations().then((regs) =>
      Promise.all(regs.map((reg) => reg.unregister())),
    );
  });
}
