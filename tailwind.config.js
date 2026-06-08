/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./apps/**/templates/**/*.html",
    "./static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        // Brand palette (from the supplied colour board).
        navy: {
          DEFAULT: "#2F4156",
          50: "#f3f5f7",
          100: "#e1e7ed",
          200: "#c3cedb",
          300: "#9aabc0",
          400: "#6b819e",
          500: "#4d6483",
          600: "#3c4f6a",
          700: "#2F4156",
          800: "#283747",
          900: "#1f2a37",
          950: "#141b24",
        },
        teal: {
          DEFAULT: "#567C8D",
          50: "#f3f6f8",
          100: "#e3eaee",
          200: "#cbd9df",
          300: "#a6bdc8",
          400: "#7c9aab",
          500: "#567C8D",
          600: "#4a6b7a",
          700: "#3f5764",
          800: "#384a54",
          900: "#323f48",
        },
        sky: {
          DEFAULT: "#C8D9E6",
          50: "#f6f9fb",
          100: "#eef4f8",
          200: "#dfeaf2",
          300: "#C8D9E6",
          400: "#a6c0d4",
          500: "#84a4c0",
        },
        beige: {
          DEFAULT: "#F5EFEB",
          50: "#fdfcfb",
          100: "#F5EFEB",
          200: "#ece2da",
          300: "#ddcdbf",
        },
      },
      fontFamily: {
        // Serif display for headlines (premium, editorial); sans for body.
        display: ["'Fraunces'", "Georgia", "'Times New Roman'", "serif"],
        sans: ["'Plus Jakarta Sans'", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica", "Arial", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(47,65,86,0.04), 0 8px 24px rgba(47,65,86,0.06)",
        cardhover: "0 2px 4px rgba(47,65,86,0.06), 0 16px 40px rgba(47,65,86,0.12)",
        soft: "0 2px 10px rgba(47,65,86,0.05)",
      },
      borderRadius: {
        xl: "1rem",
        "2xl": "1.25rem",
        "3xl": "1.75rem",
      },
      maxWidth: {
        content: "1200px",
      },
    },
  },
  plugins: [],
};
