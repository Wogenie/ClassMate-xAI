/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        ink: 'rgb(var(--color-ink) / <alpha-value>)',
        panel: 'rgb(var(--color-panel) / <alpha-value>)',
        edge: 'rgb(var(--color-edge) / <alpha-value>)',
      },
    },
  },
  plugins: [],
  darkMode: 'class',
}
