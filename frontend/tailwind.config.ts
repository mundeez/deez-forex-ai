import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        forex: {
          dark: "#0f172a",
          card: "#1e293b",
          accent: "#3b82f6",
          bullish: "#10b981",
          bearish: "#ef4444",
        },
      },
    },
  },
  plugins: [],
};
export default config;
