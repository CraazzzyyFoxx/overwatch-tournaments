/**
 * Everything this module takes from the host application, in one place.
 *
 * Porting the table means satisfying these exports for the new host; nothing
 * else in this folder imports from outside it except the shadcn primitives
 * under `@/components/ui/*` and npm packages (see README).
 */

// Router: the table mirrors its state into the URL of the current route.
export { usePathname } from "next/navigation";
export { default as Link } from "next/link";

// shadcn's class merger.
export { cn } from "@/lib/utils";

// `true` below the `md` breakpoint; rows render as cards there.
export { useIsMobile } from "@/hooks/use-mobile";

// `useState` persisted under a localStorage key; drives density, widths, order.
export { useLocalStorageState } from "@/hooks/useLocalStorageState";

// Eyebrow label style for group-header rows.
export { EYEBROW_CLASS } from "@/components/admin/tone";
