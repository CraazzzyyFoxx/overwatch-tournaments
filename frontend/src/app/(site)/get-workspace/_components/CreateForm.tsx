"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Check, CircleAlert, Lock, LogIn } from "lucide-react";

import { EmptyNote } from "@/components/kit/EmptyNote";
import { owtButton } from "@/components/site/owt-button";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { usePermissions } from "@/hooks/usePermissions";
import { ApiError, getApiErrorMessage } from "@/lib/api/error";
import { getCurrentPathForAuthRedirect } from "@/lib/auth/redirect";
import { PLATFORM_ZONE } from "@/lib/site/host";
import { cn } from "@/lib/utils";
import { SLUG_MAX_LENGTH, suggestSlug, validateSlug } from "@/lib/workspace/slug";
import workspaceService from "@/services/workspace.service";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import { useWorkspaceStore } from "@/stores/workspace.store";

type HelpKind = "neutral" | "ok" | "err";

/**
 * What the form held when "sign in and create" sent the visitor away. Sign-in
 * is a full-page OAuth round trip, so React state does not survive it; this
 * tab's storage does. Kept until the community is created.
 */
const DRAFT_KEY = "owt-get-workspace-draft";

interface Draft {
  name: string;
  slug: string;
  slugTouched: boolean;
}

function readStoredDraft(): string | null {
  try {
    return window.sessionStorage.getItem(DRAFT_KEY);
  } catch {
    return null;
  }
}

function writeStoredDraft(draft: Draft | null) {
  try {
    if (draft) window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    else window.sessionStorage.removeItem(DRAFT_KEY);
  } catch {
    // Storage refused (private mode, quota): the visitor types it again.
  }
}

function parseDraft(raw: string | null): Draft | null {
  if (!raw) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null || !("name" in value) || !("slug" in value)) {
      return null;
    }
    const { name, slug } = value;
    return typeof name === "string" && typeof slug === "string"
      ? { name, slug, slugTouched: "slugTouched" in value && value.slugTouched === true }
      : null;
  } catch {
    return null;
  }
}

const noSubscription = () => () => {};

/**
 * The create form of the organizer page (mock `.create`), and step 1 of the
 * admin's workspace wizard: on success it continues at step 2 of
 * `/admin/workspaces/new`.
 *
 * The server and the hydrating render know no draft; the first client render
 * after them reads it, and the new key remounts the form already filled. No
 * effect copies it into state, and the server HTML never disagrees with the
 * client's.
 */
export function CreateForm() {
  const stored = useSyncExternalStore(noSubscription, readStoredDraft, () => null);
  return <CreateFormBody key={stored ?? ""} draft={parseDraft(stored)} />;
}

/**
 * It mirrors what `POST /api/v1/workspaces` takes: a name and the PLATFORM
 * address `<zone>/workspace/<slug>`. There is no availability endpoint, so the
 * client can only answer "is this a legal address" (`validateSlug`); "is it
 * free" arrives as the create call's refusal.
 */
function CreateFormBody({ draft }: Readonly<{ draft: Draft | null }>) {
  const t = useTranslations("getWorkspace.create");
  const router = useRouter();
  const { user } = useAuthProfile();
  const { isDenied } = usePermissions();
  const openAuthModal = useAuthModalStore((state) => state.open);
  const fetchWorkspaces = useWorkspaceStore((state) => state.fetchWorkspaces);

  const [name, setName] = useState(draft?.name ?? "");
  const [slug, setSlug] = useState(draft?.slug ?? "");
  // Set once the slug is typed by hand; until then it follows the name.
  const [slugTouched, setSlugTouched] = useState(draft?.slugTouched ?? false);
  const [pending, setPending] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  // Back from sign-in with the form filled: the next step is the button.
  const [restored] = useState(draft !== null);
  const submitRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (restored) submitRef.current?.focus();
  }, [restored]);
  // What the server said about one specific slug — dropped as soon as the
  // field changes, because the verdict was about the old value.
  const [serverSlug, setServerSlug] = useState<{ slug: string; kind: "taken" | "reserved" } | null>(
    null
  );

  // Allow-by-default capability, revoked per account through negative RBAC.
  const revoked = Boolean(user) && isDenied("workspace.self_create");

  const slugProblem = validateSlug(slug);
  const help: { kind: HelpKind; msg: string } =
    serverSlug && serverSlug.slug === slug
      ? { kind: "err", msg: t(`slug.${serverSlug.kind}`, { slug }) }
      : slugProblem === "empty"
        ? { kind: "neutral", msg: t("slug.hint") }
        : slugProblem
          ? { kind: "err", msg: t(`slug.${slugProblem}`, { slug, max: SLUG_MAX_LENGTH }) }
          : { kind: "ok", msg: t("slug.ok") };

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!user) {
      writeStoredDraft({ name, slug, slugTouched });
      openAuthModal(getCurrentPathForAuthRedirect(window.location));
      return;
    }
    if (pending || !name.trim() || !slug || help.kind === "err") return;

    setPending(true);
    setFormError(null);
    try {
      const workspace = await workspaceService.create({ name: name.trim(), slug });
      writeStoredDraft(null);
      // The switcher list and the workspace cookie are stale the moment a
      // workspace exists that was not in them.
      void fetchWorkspaces();
      // Step 1 of the wizard is done; the rest of the setup continues there.
      router.push(`/admin/workspaces/new?id=${workspace.id}&step=profile`);
    } catch (error) {
      setPending(false);
      // The backend answers with machine codes for the two policy refusals and
      // with prose for a duplicate slug; match on both as it sends them.
      const details = error instanceof ApiError ? error.details : [];
      const codes = details.map((detail) => `${detail.code} ${detail.msg}`).join(" ");
      if (codes.includes("workspace_create_limit_reached")) {
        setFormError(t("error.limit"));
      } else if (codes.includes("slug_reserved")) {
        setServerSlug({ slug, kind: "reserved" });
      } else if (/slug already exists/i.test(codes)) {
        setServerSlug({ slug, kind: "taken" });
      } else {
        setFormError(getApiErrorMessage(error, t("error.generic")));
      }
    }
  }

  if (revoked) {
    return (
      <EmptyNote icon={Lock} title={t("revoked.title")} tone="danger" className="mt-7 max-w-[620px]">
        {t("revoked.hint")}
      </EmptyNote>
    );
  }

  return (
    <form
      id="create"
      noValidate
      onSubmit={onSubmit}
      className="mt-6 grid max-w-[640px] scroll-mt-[var(--aqt-sticky-top)] gap-5"
    >
      <div className="grid grid-cols-1 gap-x-4 gap-y-5 sm:grid-cols-2">
        <div className="min-w-0">
          <label
            htmlFor="ws-name"
            className="mb-2 block text-body font-medium text-[color:var(--aqt-fg)]"
          >
            {t("name")}
          </label>
          <Input
            id="ws-name"
            name="name"
            variant="surface"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              if (!slugTouched) setSlug(suggestSlug(event.target.value));
            }}
            placeholder={t("namePlaceholder")}
            autoComplete="off"
            required
          />
        </div>
        <div className="min-w-0">
          <label
            htmlFor="ws-slug"
            className="mb-2 block text-body font-medium text-[color:var(--aqt-fg)]"
          >
            {t("address")}
          </label>
          <Input
            id="ws-slug"
            name="slug"
            variant="surface"
            value={slug}
            // Typing a name with spaces is the common first move; the mock
            // turns it into an address as you type instead of refusing it.
            // Clearing the field hands it back to the name.
            onChange={(event) => {
              const next = event.target.value.toLowerCase().replace(/\s+/g, "-");
              setSlug(next);
              setSlugTouched(next !== "");
            }}
            placeholder="night-owls"
            spellCheck={false}
            autoComplete="off"
            required
            aria-describedby="slug-preview slug-help"
            aria-invalid={help.kind === "err"}
          />
          <p
            id="slug-preview"
            className="mt-2 font-mono text-caption leading-relaxed text-[color:var(--aqt-fg-dim)] [overflow-wrap:anywhere]"
          >
            {PLATFORM_ZONE}/workspace/
            <span className="text-[color:var(--aqt-fg-muted)]">{slug}</span>
          </p>
          <p
            id="slug-help"
            aria-live="polite"
            className={cn(
              "mt-1.5 flex min-h-5 items-start gap-1.5 text-caption leading-relaxed",
              help.kind === "ok"
                ? "text-[color:var(--aqt-emerald)]"
                : help.kind === "err"
                  ? "text-[color:var(--aqt-rose-text)]"
                  : "text-[color:var(--aqt-fg-dim)]"
            )}
          >
            {help.kind === "ok" ? <Check className="mt-0.5 size-3.5 shrink-0" aria-hidden /> : null}
            {help.kind === "err" ? (
              <CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            ) : null}
            <span>{help.msg}</span>
          </p>
        </div>
      </div>
      <div className="flex flex-col items-start gap-3">
        {/* owtButton carries the whole marketing look; Button only supplies the element. */}
        <Button
          ref={submitRef}
          type="submit"
          variant={null}
          size={null}
          disabled={pending}
          aria-busy={pending}
          className={owtButton({ variant: "primary", size: "lg" })}
        >
          {user ? (
            t("submit")
          ) : (
            <>
              <LogIn aria-hidden />
              {t("submitSignedOut")}
            </>
          )}
        </Button>
        <small className="max-w-[38rem] text-pretty text-caption leading-relaxed text-[color:var(--aqt-fg-dim)]">
          {t("note")}
        </small>
      </div>
      {formError ? (
        <p role="alert" className="text-body leading-relaxed text-[color:var(--aqt-rose-text)]">
          {formError}
        </p>
      ) : null}
    </form>
  );
}
