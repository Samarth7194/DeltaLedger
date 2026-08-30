import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#f5f7f6",
          900: "#e7ecea",
          800: "#c8d3cf",
          700: "#96a8a1"
        },
        ledger: {
          900: "#061413",
          800: "#0d2524",
          700: "#1f8a78",
          600: "#35b69f",
          500: "#52d3bd",
          200: "#9de7da",
          100: "#d8f8f1"
        },
        amberline: {
          600: "#a5652a",
          300: "#e1a85f",
          100: "#f7ead9"
        },
        graphite: {
          980: "#050708",
          950: "#090d10",
          900: "#10161a",
          850: "#151c21",
          800: "#1b2429",
          700: "#2b373e"
        }
      },
      boxShadow: {
        panel: "0 18px 60px rgba(0, 0, 0, 0.28)",
        glow: "0 0 0 1px rgba(82, 211, 189, 0.18), 0 20px 70px rgba(5, 7, 8, 0.45)"
      }
    }
  },
  plugins: []
};

export default config;
