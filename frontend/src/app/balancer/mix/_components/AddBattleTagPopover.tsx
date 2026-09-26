"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";

import { EYEBROW_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Spinner } from "@/components/ui/spinner";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { workspacePlayerKeys, workspacePlayerService } from "@/services/workspace-player.service";

/**
 * Adding somebody the workspace roster has never seen, from inside the picker.
 *
 * The new member drops straight into this mix on success: a host types a tag
 * *because* that person is in the lobby right now, so making them find the new
 * row afterwards was busywork.
 */
export function AddBattleTagPopover({
  workspaceId,
  canWrite,
  onTogglePlayer
}: Readonly<{
  workspaceId: number;
  /** Mix right: a closed mix still accepts a roster addition, it just cannot seat them. */
  canWrite: boolean;
  onTogglePlayer: (memberId: number) => void;
}>) {
  const queryClient = useQueryClient();
  const [battleTag, setBattleTag] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [isAddOpen, setIsAddOpen] = useState(false);

  const addByTag = useMutation({
    mutationFn: (tag: string) => workspacePlayerService.upsert(workspaceId, tag),
    onSuccess: async (member, tag) => {
      setBattleTag("");
      setIsAddOpen(false);
      notify.success(`${tag} joined the workspace roster`);
      await queryClient.invalidateQueries({ queryKey: workspacePlayerKeys.all(workspaceId) });
      if (canWrite) onTogglePlayer(member.member_id);
    },
    onError: (error) => notify.apiError(error)
  });

  const submitBattleTag = () => {
    const tag = battleTag.trim();
    if (!tag) {
      setAddError("Enter a BattleTag, for example Name#1234.");
      return;
    }
    setAddError(null);
    addByTag.mutate(tag);
  };

  return (
    <Popover
      open={isAddOpen}
      onOpenChange={(next) => {
        setIsAddOpen(next);
        if (!next) setAddError(null);
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "ml-auto inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border border-dashed px-3",
            "border-[color:var(--aqt-border-2)] text-label text-[color:var(--aqt-fg-dim)]",
            "transition-colors hover:border-[color:var(--aqt-border-3)] hover:text-[color:var(--aqt-fg)]"
          )}
        >
          <UserPlus className="size-3.5" aria-hidden="true" />
          New BattleTag
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-3">
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            submitBattleTag();
          }}
        >
          <p className={EYEBROW_CLASS}>Add someone new</p>
          <div className="flex gap-1.5">
            <Input
              value={battleTag}
              onChange={(event) => {
                setBattleTag(event.target.value);
                if (addError) setAddError(null);
              }}
              placeholder="Name#1234"
              aria-label="New BattleTag"
              autoComplete="off"
              aria-invalid={addError ? true : undefined}
              // `min-w-0`: an `<input>` carries an intrinsic ~170px
              // width that `min-width: auto` turns into a floor.
              className="h-9 min-w-0 rounded-lg border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] text-sm"
            />
            {/* Enabled while empty on purpose: submit validates and says why. */}
            <Button type="submit" size="sm" className="h-9 shrink-0 px-3" disabled={addByTag.isPending}>
              {addByTag.isPending ? <Spinner className="size-3.5" /> : null}
              Add
            </Button>
          </div>
          <p
            className={cn(
              "text-label",
              addError ? "text-rose-200" : "text-[color:var(--aqt-fg-dim)]"
            )}
          >
            {addError ?? "Joins the workspace roster and drops straight into this mix."}
          </p>
        </form>
      </PopoverContent>
    </Popover>
  );
}
