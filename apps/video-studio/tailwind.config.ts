import type { Config } from "tailwindcss";

export default {
  darkMode: ["class"],
  content: ["./pages/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./app/**/*.{ts,tsx}", "./src/**/*.{ts,tsx}"],
  prefix: "",
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
          gray: "hsl(var(--accent-gray))",
          "gray-dark": "hsl(var(--accent-gray-dark))",
          blue: "hsl(var(--accent-blue))",
          green: "hsl(var(--accent-green))",
          orange: "hsl(var(--accent-orange))",
          red: "hsl(var(--accent-red))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      fontFamily: {
        'inter': ['Inter', 'PingFang SC', 'Noto Sans SC', 'sans-serif'],
        'inter-tight': ['"Inter Tight"', 'Inter', 'PingFang SC', 'Noto Sans SC', 'sans-serif'],
        'space-grotesk': ['"Space Grotesk"', 'sans-serif'],
        'righteous': ['Righteous', 'sans-serif'],
        'playfair': ['Playfair Display', 'serif'],
        'cormorant': ['Cormorant Garamond', 'serif'],
        'system': ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      backgroundImage: {
        'gradient-primary': 'var(--gradient-primary)',
        'gradient-surface': 'var(--gradient-surface)',
        'gradient-glass': 'var(--gradient-glass)',
      },
      boxShadow: {
        'apple-sm': 'var(--shadow-sm)',
        'apple': 'var(--shadow)',
        'apple-lg': 'var(--shadow-lg)',
        'apple-xl': 'var(--shadow-xl)',
      },
      backdropBlur: {
        'apple': '20px',
        'apple-strong': '30px',
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": {
          from: {
            height: "0",
          },
          to: {
            height: "var(--radix-accordion-content-height)",
          },
        },
        "accordion-up": {
          from: {
            height: "var(--radix-accordion-content-height)",
          },
          to: {
            height: "0",
          },
        },
        "spin-slow": {
          from: {
            transform: "rotate(0deg)",
          },
          to: {
            transform: "rotate(360deg)",
          },
        },
        "scroll-up": {
          "0%": {
            transform: "translateY(0)",
          },
          "100%": {
            transform: "translateY(-50%)",
          },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "spin-slow": "spin-slow 3s linear infinite",
        "scroll-up": "scroll-up 60s linear infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config;
