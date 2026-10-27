"use client";

import { Toaster as SonnerToaster, type ToasterProps } from "sonner";

import { buttonVariants } from "@/components/ui/button";
import { floatingPanelClass } from "@/components/ui/popover";
import { TONE_HUE, type Tone } from "@/components/ui/tone";
import { cn } from "@/lib/utils";

/**
 * A typed toast keeps the panel and spends its tone on the rim and the icon.
 * `[&[data-type]]` lifts the rim over `floatingPanelClass`'s border colour,
 * which sits on the same element with the same specificity.
 */
function toneToast(tone: Tone) {
  return cn(
    TONE_HUE[tone],
    "[&[data-type]]:border-[color:color-mix(in_srgb,var(--tone-hue)_32%,transparent)] [&_[data-icon]]:text-[color:var(--tone-hue)]"
  );
}

/**
 * Global Sonner toaster. Mounted once in the root layout.
 *
 * `unstyled`: Sonner's stylesheet is unlayered, so it outranks every Tailwind
 * utility; unstyled, the toast is the floating panel (`floatingPanelClass`)
 * and its buttons are `Button`s. What stays Sonner's: stacking, motion, and
 * the close button's colours, read from the `--normal-*` variables below.
 * The app is dark-only, so the theme is fixed to "dark".
 */
export function Toaster(props: ToasterProps) {
  return (
    <SonnerToaster
      theme="dark"
      position="bottom-right"
      closeButton
      duration={4000}
      style={
        {
          "--normal-bg": "var(--aqt-card-2)",
          "--normal-bg-hover": "var(--aqt-card-2)",
          "--normal-text": "var(--aqt-fg-muted)",
          "--normal-border": "var(--aqt-border-2)",
          "--normal-border-hover": "var(--aqt-border-3)"
        } as React.CSSProperties
      }
      toastOptions={{
        unstyled: true,
        classNames: {
          // A collapsed stack hides the content of the toasts behind the front one.
          toast: cn(
            floatingPanelClass,
            "flex w-[var(--width)] items-center gap-2 p-4 font-sans text-caption [&[data-expanded=false][data-front=false]>*]:opacity-0"
          ),
          content: "flex min-w-0 flex-1 flex-col gap-0.5",
          title: "font-medium",
          // `!`: Sonner's dark theme colours the description from its own stylesheet.
          description: "text-[color:var(--aqt-fg-muted)]!",
          icon: "relative flex size-4 shrink-0 items-center",
          actionButton: buttonVariants({ size: "sm" }),
          cancelButton: buttonVariants({ variant: "outline", size: "sm" }),
          closeButton:
            "absolute left-[var(--toast-close-button-start)] right-[var(--toast-close-button-end)] top-0 z-1 flex size-5 items-center justify-center rounded-full border [transform:var(--toast-close-button-transform)] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          success: toneToast("success"),
          error: toneToast("danger"),
          warning: toneToast("warning"),
          info: toneToast("info")
        }
      }}
      {...props}
    />
  );
}
