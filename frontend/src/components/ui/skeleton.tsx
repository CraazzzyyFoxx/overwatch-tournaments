import { cn } from "@/lib/utils";

/**
 * Loading stand-in. `block` (default) is a `<div>` sized by the caller.
 * `text` stands in for one line of text: an inline `<span>` in the parent's
 * line box, 0.8em tall, so the value that replaces it takes the same height
 * and nothing shifts when the data lands. Never make a `text` skeleton a grid
 * or flex item itself: that blockifies it to its own 0.8em height.
 */
function Skeleton({
  className,
  variant = "block",
  ...props
}: React.HTMLAttributes<HTMLElement> & { variant?: "block" | "text" }) {
  const Comp = variant === "text" ? "span" : "div";
  return (
    <Comp
      className={cn(
        "animate-pulse rounded-md bg-[color:var(--aqt-overlay-3)] motion-reduce:animate-none",
        variant === "text" && "inline-block h-[0.8em] align-middle",
        className
      )}
      {...props}
    />
  );
}

export { Skeleton };
