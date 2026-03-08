/**
 * Inventari de discs — JavaScript mínim
 * Toggle tema clar/fosc: guarda preferència a localStorage i aplica classe .dark a <html>
 */
(function () {
  var STORAGE_KEY = 'inventari-theme';
  var DARK = 'dark';

  function getStored() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function setStored(value) {
    try {
      if (value) localStorage.setItem(STORAGE_KEY, value);
      else localStorage.removeItem(STORAGE_KEY);
    } catch (e) {}
  }

  function applyTheme(isDark) {
    document.documentElement.classList.toggle(DARK, !!isDark);
  }

  // Respectar preferència guardada; si no hi ha, opcionalment prefers-color-scheme: dark
  var stored = getStored();
  if (stored === 'dark' || stored === 'light') {
    applyTheme(stored === 'dark');
  } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    applyTheme(true);
  }

  // Exposar per al botó de toggle: window.inventariToggleTheme()
  window.inventariToggleTheme = function () {
    var isDark = document.documentElement.classList.contains(DARK);
    isDark = !isDark;
    applyTheme(isDark);
    setStored(isDark ? 'dark' : 'light');
  };
})();
