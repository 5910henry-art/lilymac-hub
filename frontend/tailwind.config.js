// tailwind.config.js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,jsx,ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        accent: {
          DEFAULT: "#4f46e5",
          dark: "#6366f1",
        },
        greenFaint: "#0f2a0f",      // page background
        greenCard: "#1f3a1f",       // card background
        greenLight: "#b2f2bb",      // light text accents
        greenMedium: "#4ade80",     // medium accents (probabilities, selection)
        greenDark: "#145214",       // for logos/hover effects
      },
      keyframes: {
        "gradient-x": {
          "0%, 100%": { "background-position": "0% 50%" },
          "50%": { "background-position": "100% 50%" },
        },
        // New: short bounce for mobile betslip
        "bounce-short": {
          "0%, 100%": { transform: "translateY(0%)" },
          "25%": { transform: "translateY(-10%)" },
          "50%": { transform: "translateY(0%)" },
          "75%": { transform: "translateY(-5%)" },
        },
      },
      animation: {
        "gradient-x": "gradient-x 30s ease-in-out infinite",
        // New: short bounce animation
        "bounce-short": "bounce-short 0.5s ease-in-out",
      },
      backgroundSize: {
        "size-200": "200% 200%",
      },
    },
  },
  safelist: [
    'from-blue-500',
    'via-purple-500',
    'to-red-500',
    'text-white',
    'bg-gradient-to-r',
    // optional: add green classes
    'bg-greenFaint',
    'bg-greenCard',
    'text-greenLight',
    'text-greenMedium',
    'bg-greenDark',
  ],
  plugins: [],
};
