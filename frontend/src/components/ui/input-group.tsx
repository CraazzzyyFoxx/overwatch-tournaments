"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import { controlSurfaceClass, Input } from "@/components/ui/input";

type InputGroupSize = "sm" | "default";

const InputGroupSizeContext = React.createContext<InputGroupSize>("default");

/**
 * An `Input` with a fixed text beside it (a domain, a path prefix). The frame
 * wears the control surface and draws the input's focus ring and error border,
 * so the addon and the input read as one field. `size` sets the row for both.
 */
function InputGroup({
  className,
  size = "default",
  ...props
}: React.ComponentProps<"div"> & { size?: InputGroupSize }) {
  return (
    <InputGroupSizeContext.Provider value={size}>
      <div
        data-slot="input-group"
        role="group"
        className={cn(
          controlSurfaceClass,
          "group/input-group relative flex items-center px-0",
          size === "sm" ? "h-8 text-caption" : "h-9 text-sm",
          "has-[>[data-align=inline-start]]:[&>input]:pl-2 has-[>[data-align=inline-end]]:[&>input]:pr-2",
          "has-[[data-slot=input-group-control]:focus-visible]:ring-2 has-[[data-slot=input-group-control]:focus-visible]:ring-ring",
          "has-[[data-slot=input-group-control]:focus-visible]:ring-offset-2 has-[[data-slot=input-group-control]:focus-visible]:ring-offset-background",
          "has-[[data-slot=input-group-control][aria-invalid=true]]:border-destructive",
          "has-[[data-slot=input-group-control]:disabled]:cursor-not-allowed has-[[data-slot=input-group-control]:disabled]:opacity-50",
          className
        )}
        {...props}
      />
    </InputGroupSizeContext.Provider>
  );
}

function InputGroupAddon({
  className,
  align = "inline-start",
  ...props
}: React.ComponentProps<"div"> & { align?: "inline-start" | "inline-end" }) {
  return (
    <div
      role="group"
      data-slot="input-group-addon"
      data-align={align}
      className={cn(
        "flex h-auto cursor-text select-none items-center justify-center gap-2 py-1.5 font-medium text-[color:var(--aqt-fg-muted)] [&>svg:not([class*='size-'])]:size-4",
        align === "inline-end" ? "order-last pr-3" : "order-first pl-3",
        className
      )}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("button")) {
          return;
        }
        e.currentTarget.parentElement?.querySelector("input")?.focus();
      }}
      {...props}
    />
  );
}

function InputGroupText({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "flex items-center gap-2 [&_svg:not([class*='size-'])]:size-4 [&_svg]:pointer-events-none",
        className
      )}
      {...props}
    />
  );
}

function InputGroupInput({
  className,
  ...props
}: Omit<React.ComponentProps<typeof Input>, "size">) {
  const size = React.useContext(InputGroupSizeContext);
  return (
    <Input
      data-slot="input-group-control"
      size={size}
      className={cn(
        "h-full flex-1 rounded-none border-0 bg-transparent focus-visible:ring-0 focus-visible:ring-offset-0 disabled:opacity-100",
        className
      )}
      {...props}
    />
  );
}

export { InputGroup, InputGroupAddon, InputGroupText, InputGroupInput };
