"use client";

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

function FieldSet({ className, ...props }: React.ComponentProps<"fieldset">) {
  return (
    <fieldset
      data-slot="field-set"
      className={cn(
        "flex flex-col gap-6",
        "has-[>[data-slot=checkbox-group]]:gap-3 has-[>[data-slot=radio-group]]:gap-3",
        className
      )}
      {...props}
    />
  );
}

function FieldGroup({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="field-group"
      className={cn(
        "group/field-group @container/field-group flex w-full flex-col gap-7 data-[slot=checkbox-group]:gap-3 [&>[data-slot=field-group]]:gap-4",
        className
      )}
      {...props}
    />
  );
}

const fieldVariants = cva("group/field flex w-full gap-3 data-[invalid=true]:text-destructive", {
  variants: {
    orientation: {
      // The `.sr-only` escape hatch is matched by class name, so a responsive
      // variant like `lg:sr-only` misses it and keeps `w-full`: absolutely
      // positioned at 100% of the viewport, one hidden label then stretches
      // the document twice its width. `[class*=":sr-only"]` catches the
      // variants without also catching `not-sr-only`.
      vertical: ['flex-col [&>*]:w-full [&>.sr-only]:w-auto [&>[class*=":sr-only"]]:w-auto'],
      horizontal: [
        "flex-row items-center",
        "[&>[data-slot=field-label]]:flex-auto",
        "has-[>[data-slot=field-content]]:[&>[role=checkbox],[role=radio]]:mt-px has-[>[data-slot=field-content]]:items-start"
      ],
      responsive: [
        '@md/field-group:flex-row @md/field-group:items-center @md/field-group:[&>*]:w-auto flex-col [&>*]:w-full [&>.sr-only]:w-auto [&>[class*=":sr-only"]]:w-auto',
        "@md/field-group:[&>[data-slot=field-label]]:flex-auto",
        "@md/field-group:has-[>[data-slot=field-content]]:items-start @md/field-group:has-[>[data-slot=field-content]]:[&>[role=checkbox],[role=radio]]:mt-px"
      ]
    }
  },
  defaultVariants: {
    orientation: "vertical"
  }
});

function Field({
  className,
  orientation = "vertical",
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof fieldVariants>) {
  return (
    <div
      role="group"
      data-slot="field"
      data-orientation={orientation}
      className={cn(fieldVariants({ orientation }), className)}
      {...props}
    />
  );
}

function FieldContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="field-content"
      className={cn("group/field-content flex flex-1 flex-col gap-1.5 leading-snug", className)}
      {...props}
    />
  );
}

function FieldLabel({ className, ...props }: React.ComponentProps<typeof Label>) {
  return (
    <Label
      data-slot="field-label"
      className={cn(
        "group/field-label peer/field-label flex w-fit gap-2 leading-snug group-data-[disabled=true]/field:opacity-50",
        "has-[>[data-slot=field]]:w-full has-[>[data-slot=field]]:flex-col has-[>[data-slot=field]]:rounded-lg has-[>[data-slot=field]]:border has-[>[data-slot=field]]:border-[color:var(--aqt-border-2)] [&>[data-slot=field]]:p-4",
        // A `Field` inside the label is a whole-option radio card: the option card's chosen look.
        "has-data-[state=checked]:border-[color:var(--aqt-teal)] has-data-[state=checked]:bg-[color:color-mix(in_srgb,var(--aqt-teal)_10%,transparent)]",
        className
      )}
      {...props}
    />
  );
}

function FieldTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="field-label"
      className={cn(
        "flex w-fit items-center gap-2 text-sm font-medium leading-snug group-data-[disabled=true]/field:opacity-50",
        className
      )}
      {...props}
    />
  );
}

/** `size="sm"` is the 12px message line the public registration skin uses. */
type FieldTextSize = { size?: "sm" | "default" };

function FieldDescription({
  className,
  size = "default",
  ...props
}: React.ComponentProps<"p"> & FieldTextSize) {
  return (
    <p
      data-slot="field-description"
      className={cn(
        "font-normal leading-normal text-[color:var(--aqt-fg-dim)] group-has-[[data-orientation=horizontal]]/field:text-balance",
        size === "sm" ? "text-label" : "text-sm",
        "nth-last-2:-mt-1 last:mt-0 [[data-variant=legend]+&]:-mt-1.5",
        "[&>a:hover]:text-[color:var(--aqt-teal)] [&>a]:underline [&>a]:underline-offset-4",
        className
      )}
      {...props}
    />
  );
}

/**
 * A field's validation message; renders nothing without one. Point the
 * control's `aria-describedby` at its `id`. `role="alert"`: an error that
 * appears on submit is announced without moving focus back to the field.
 */
function FieldError({
  className,
  size = "default",
  children,
  ...props
}: React.ComponentProps<"p"> & FieldTextSize) {
  if (!children) return null;
  return (
    <p
      data-slot="field-error"
      role="alert"
      className={cn(
        "font-normal text-destructive",
        size === "sm" ? "text-label" : "text-sm",
        className
      )}
      {...props}
    >
      {children}
    </p>
  );
}

export {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldSet,
  FieldTitle
};
