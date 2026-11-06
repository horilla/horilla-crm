/**
 * Login page Tailwind theme config.
 *
 * Loaded by inject_html/tailwind_dynamic_config_login.html (head_end slot of the
 * login page). Must run synchronously after tailwind.js and before the page
 * renders, so it is included as a plain (non-async) script tag. The tag carries
 * the server default theme as data attributes (data-theme-id, data-surface,
 * data-primary-50 ... data-secondary-900); they are absent when no theme exists.
 *
 * Colour source order: localStorage "lastActiveTheme" (saved on logout), then the
 * server default theme. Missing/empty values fall back to the built-in palette
 * below, which matches the defaults previously set in the template.
 */
(function () {
  var dataset = (document.currentScript && document.currentScript.dataset) || {};

  // Check localStorage for last active company theme
  const lastActiveTheme = localStorage.getItem('lastActiveTheme');
  let themeData = null;

  if (lastActiveTheme) {
    try {
      themeData = JSON.parse(lastActiveTheme);
    } catch (e) {
      console.error('Error parsing theme from localStorage:', e);
    }
  }

  // If no theme in localStorage, use default theme from server
  if (!themeData && dataset.themeId !== undefined) {
    themeData = {
      id: Number(dataset.themeId),
      surface: dataset.surface,
    };
    const scales = {
      primary: [50, 100, 200, 300, 400, 500, 600, 700, 800, 900],
      dark: [25, 50, 100, 200, 300, 400, 500, 600],
      secondary: [50, 100, 200, 300, 400, 500, 600, 700, 800, 900],
    };
    Object.keys(scales).forEach(function (name) {
      scales[name].forEach(function (shade) {
        themeData[name + '_' + shade] = dataset[name + shade];
      });
    });
  }

  // Apply theme configuration
  if (themeData) {
    window.tailwind.config = {
      theme: {
        colors: {
          white: '#FFFFFF',
          surface: themeData.surface || '#e9edf0ba',
          primary: {
            50:  themeData.primary_50 || '#f6f6f6',
            100: themeData.primary_100 || '#FFF5F1',
            200: themeData.primary_200 || '#FEF6F5',
            300: themeData.primary_300 || '#FCEDEB',
            400: themeData.primary_400 || '#FBE5E1',
            500: themeData.primary_500 || '#F7C8C1',
            600: themeData.primary_600 || '#E54F38',
            700: themeData.primary_700 || '#ce4732',
            800: themeData.primary_800 || '#AC3B2A',
            900: themeData.primary_900 || '#672419',
          },
          dark: {
            25:  themeData.dark_25 || '#F0F0F0',
            50:  themeData.dark_50 || '#E6E6E6',
            100: themeData.dark_100 || '#A8A8A8',
            200: themeData.dark_200 || '#515151',
            300: themeData.dark_300 || '#501C14',
            400: themeData.dark_400 || '#64748B',
            500: themeData.dark_500 || '#190906',
            600: themeData.dark_600 || '#000000',
          },
          secondary: {
            50:  themeData.secondary_50 || '#f8fafc',
            100: themeData.secondary_100 || '#f1f5f9',
            200: themeData.secondary_200 || '#e2e8f0',
            300: themeData.secondary_300 || '#cbd5e1',
            400: themeData.secondary_400 || '#FBE5E1',
            500: themeData.secondary_500 || '#F7C8C1',
            600: themeData.secondary_600 || '#E54F38',
            700: themeData.secondary_700 || '#334155',
            800: themeData.secondary_800 || '#1e293b',
            900: themeData.secondary_900 || '#0f172a',
          },
          success: { light: "#86efac", DEFAULT: "#22c55e", dark: "#15803d" },
          warning: { light: "#fde68a", DEFAULT: "#f59e0b", dark: "#b45309" },
          danger: { light: "#fca5a5", DEFAULT: "#ef4444", dark: "#b91c1c" },
        },
        extend: {
          boxShadow: { card: "0px 0px 10px rgba(0, 0, 0, 0.05)" },
          spacing: { 18: "4.5rem", 72: "18rem", 84: "21rem", 96: "24rem" },
          borderRadius: { "4xl": "2rem", "5xl": "2.5rem" },
          fontSize: { xxs: "0.625rem" },
          height: { "screen-50": "50vh", "screen-75": "75vh" },
        },
      },
    };
  }
  // Otherwise (no stored theme and no server theme) the template loads the
  // default assets/js/tailwind.config.js right after this script.
})();
