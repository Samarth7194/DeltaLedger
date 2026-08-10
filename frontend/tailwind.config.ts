import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#17201b",
          800: "#26332d",
          700: "#33443b"
        },
        ledger: {
          700: "#2f6b5f",
          600: "#3d7f70",
          100: "#e7f2ef"
        },
        amberline: {
          600: "#a5652a",
          100: "#f7ead9"
        }
      },
      boxShadow: {
        panel: "0 1px 2px rgba(23, 32, 27, 0.08)"
      }
    }
  },
  plugins: []
};

export default config;
