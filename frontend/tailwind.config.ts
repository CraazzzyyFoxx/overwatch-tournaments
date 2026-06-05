// eslint-disable-next-line no-mixed-spaces-and-tabs

import type { Config } from "tailwindcss";
import colors from "tailwindcss/colors";

const config = {
  darkMode: "class",
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}"
  ],
  prefix: "",
  theme: {
    container: {
      center: true,
      padding: "2rem"
    },
    screens: {
      xs: "320px",
      xs1: "540px",
      sm: "640px",
      md: "768px",
      lg: "1024px",
      xl: "1280px",
      "2xl": "1400px",
      "3xl": "1720px"
    },
    extend: {
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains-mono)", "ui-monospace", "monospace"],
        display: ["var(--font-barlow-condensed)", "system-ui", "sans-serif"],
      },
      colors: {
        // Redesign (OWT) accent palette — references global --aqt-* tokens.
        aqt: {
          teal: "var(--aqt-teal)",
          emerald: "var(--aqt-emerald)",
          amber: "var(--aqt-amber)",
          rose: "var(--aqt-rose)",
          violet: "var(--aqt-violet)",
          blue: "var(--aqt-blue)",
          gold: "var(--aqt-gold)",
          tank: "var(--aqt-tank)",
          damage: "var(--aqt-damage)",
          support: "var(--aqt-support)",
        },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        "group-a": "#86efac", // green-300 in HEX
        "group-b": "#fef08a", // yellow-200 in HEX
        "group-c": "#93c5fd", // blue-300 in HEX
        "group-d": "#c084fc", // purple-400 in HEX
        firstPlaceBg: "#cbb765",
        TopPlaceText: "#121009",
        secondPlaceBg: "#99b0cc",
        thirdPlaceBg: "#a86243",
        placeBg: "#2c3f52",
        placeText: "#ffffff",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))"
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))"
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))"
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))"
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))"
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))"
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))"
        },
        amber: {
          "50": "#fffbeb",
          "100": "#fef3c7",
          "200": "#fde68a",
          "300": "#fcd34d",
          "400": "#fbbf24",
          "500": "#f59e0b",
          "600": "#d97706",
          "700": "#b45309",
          "800": "#92400e",
          "900": "#78350f",
          "950": "#451a03"
        },
        sidebar: {
          DEFAULT: "hsl(var(--sidebar-background))",
          foreground: "hsl(var(--sidebar-foreground))",
          primary: "hsl(var(--sidebar-primary))",
          "primary-foreground": "hsl(var(--sidebar-primary-foreground))",
          accent: "hsl(var(--sidebar-accent))",
          "accent-foreground": "hsl(var(--sidebar-accent-foreground))",
          border: "hsl(var(--sidebar-border))",
          ring: "hsl(var(--sidebar-ring))"
        }
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)"
      },
      keyframes: {
        "accordion-down": {
          from: {
            height: "0"
          },
          to: {
            height: "var(--radix-accordion-content-height)"
          }
        },
        "accordion-up": {
          from: {
            height: "var(--radix-accordion-content-height)"
          },
          to: {
            height: "0"
          }
        }
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out"
      },
      maxWidth: {
        "screen-3xl": "1620px"
      }
    }
  },
  plugins: [require("tailwindcss-animate")]
} satisfies Config;

export default config;
