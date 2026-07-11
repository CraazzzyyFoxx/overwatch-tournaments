"use client";

import { Toaster as SonnerToaster, type ToasterProps } from "sonner";

/**
 * Global Sonner toaster. Mounted once in the root layout.
 *
 * The app is dark-only (`<body className="dark">`, no next-themes), so the theme
 * is fixed to "dark". `richColors` gives clearly coloured success/error/warning
 * states; neutral toasts fall back to the popover palette via CSS variables.
 */
export function Toaster(props: ToasterProps) {
  return (
    <SonnerToaster
      theme="dark"
      position="bottom-right"
      richColors
      closeButton
      duration={4000}
      className="toaster group"
      style={
        {
          "--normal-bg": "hsl(var(--popover))",
          "--normal-text": "hsl(var(--popover-foreground))",
          "--normal-border": "hsl(var(--border))"
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: "group toast font-sans",
          description: "group-[.toast]:opacity-90",
          actionButton: "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton: "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground"
        }
      }}
      {...props}
    />
  );
}
