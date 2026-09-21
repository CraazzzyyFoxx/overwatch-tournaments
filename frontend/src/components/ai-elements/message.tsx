"use client";

import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

/**
 * Message primitives, adapted from the shadcn `@ai-elements/message` registry
 * item for a HUMAN chat.
 *
 * The upstream component models an assistant transcript: it types `from` as
 * `UIMessage["role"]`, renders bodies through `Streamdown`, and ships branch
 * navigation and file attachments. That pulls in the `ai` SDK and `streamdown`
 * for a room where two captains send plain text at each other — so the parts we
 * use are copied and the rest is not. `Conversation` (the stick-to-bottom
 * scroller) is vendored unmodified next to this file, because that behaviour is
 * the fiddly half and it has no such baggage.
 */
export type MessageAuthorKind = "self" | "peer" | "system";

export type MessageProps = ComponentProps<"div"> & {
  /** Who wrote it, from the reader's point of view. Drives side + colour. */
  from: MessageAuthorKind;
};

export const Message = ({ className, from, ...props }: MessageProps) => (
  <div
    className={cn(
      "group flex w-full max-w-[85%] flex-col gap-1",
      from === "self" && "is-self ml-auto items-end",
      from === "peer" && "is-peer items-start",
      from === "system" && "is-system mx-auto max-w-full items-center",
      className
    )}
    {...props}
  />
);

export type MessageHeaderProps = ComponentProps<"div">;

/** Author line: name, optional side badge, timestamp. */
export const MessageHeader = ({ className, ...props }: MessageHeaderProps) => (
  <div
    className={cn(
      "flex items-center gap-1.5 text-label uppercase tracking-label text-muted-foreground",
      className
    )}
    {...props}
  />
);

export type MessageContentProps = ComponentProps<"div">;

export const MessageContent = ({ className, ...props }: MessageContentProps) => (
  <div
    className={cn(
      "w-fit max-w-full min-w-0 overflow-hidden rounded-lg px-3 py-2 text-sm",
      // `break-words` is not optional here: a chat body is arbitrary user text,
      // and one unbroken 200-character token would otherwise widen the whole
      // scroller instead of wrapping.
      "whitespace-pre-wrap break-words",
      "group-[.is-self]:bg-primary/15 group-[.is-self]:text-foreground",
      "group-[.is-peer]:bg-muted group-[.is-peer]:text-foreground",
      "group-[.is-system]:bg-transparent group-[.is-system]:px-0 group-[.is-system]:py-0 group-[.is-system]:text-xs group-[.is-system]:text-muted-foreground",
      className
    )}
    {...props}
  />
);
