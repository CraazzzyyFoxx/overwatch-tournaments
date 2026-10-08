"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Check, CircleAlert, Lock, LogIn } from "lucide-react";

import { EYEBROW_CLASS } from "@/components/site/open-layout";
import { owtButton } from "@/components/site/owt-button";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { usePermissions } from "@/hooks/usePermissions";
import { ApiError, getApiErrorMessage } from "@/lib/api/error";
import { getCurrentPathForAuthRedirect } from "@/lib/auth/redirect";
import { PLATFORM_ZONE } from "@/lib/site/host";
import { cn } from "@/lib/utils";
import workspaceService from "@/services/workspace.service";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import { useWorkspaceStore } from "@/stores/workspace.store";

/**
 * Slugs the platform keeps for itself — the resolved
 * `backend/app-service/src/services/workspace/service.py` `RESERVED_SLUGS`
 * (`RESERVED_SUBDOMAINS` plus the platform's own top-level routes). There is no
 * availability endpoint, so the client can only answer "is this a legal
 * address"; "is it free" arrives as the create call's refusal.
 */
const RESERVED: Record<string, true> = {
  www: true,
  api: true,
  auth: true,
  admin: true,
  app: true,
  assets: true,
  static: true,
  cdn: true,
  mail: true,
  ws: true,
  docs: true,
  status: true,
  support: true
};

const SLUG_RE = /^[a-z0-9_-]+$/;
const EDGE_RE = /^[-_]|[-_]$/;

type HelpKind = "neutral" | "ok" | "err";

const INPUT_SHELL =
  "flex h-11 min-w-0 items-center gap-2.5 rounded-[var(--aqt-radius-sm)] border " +
  "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-3.5 " +
  "transition-[border-color,background-color] duration-150 " +
  "focus-within:border-[color:var(--aqt-teal)] focus-within:bg-[color:var(--aqt-overlay-3)]";

const INPUT_FIELD =
  "h-full min-w-0 flex-1 border-0 bg-transparent text-ui leading-none text-[color:var(--aqt-fg)] " +
  "outline-none placeholder:text-[color:var(--aqt-fg-faint)]";

/**
 * The create form of the organizer page (mock `.create`).
 *
 * It mirrors what `POST /api/v1/workspaces` takes: a name and the PLATFORM
 * address `<zone>/workspace/<slug>`. Subdomain, custom domain and colours are
 * settings after creation, so the form must not promise them.
 */
export function CreateForm() {
  const t = useTranslations("getWorkspace.create");
  const router = useRouter();
  const { user } = useAuthProfile();
  const { isDenied } = usePermissions();
  const openAuthModal = useAuthModalStore((state) => state.open);
  const fetchWorkspaces = useWorkspaceStore((state) => state.fetchWorkspaces);

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [pending, setPending] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  // What the server said about one specific slug — dropped as soon as the
  // field changes, because the verdict was about the old value.
  const [serverSlug, setServerSlug] = useState<{ slug: string; kind: "taken" | "reserved" } | null>(
    null
  );

  // Allow-by-default capability, revoked per account through negative RBAC.
  const revoked = Boolean(user) && isDenied("workspace.self_create");

  const help: { kind: HelpKind; msg: string } =
    serverSlug && serverSlug.slug === slug
      ? { kind: "err", msg: t(`slug.${serverSlug.kind}`, { slug }) }
      : checkSlug(slug);

  function checkSlug(value: string): { kind: HelpKind; msg: string } {
    if (!value) return { kind: "neutral", msg: t("slug.hint") };
    if (!SLUG_RE.test(value)) return { kind: "err", msg: t("slug.format") };
    if (EDGE_RE.test(value)) return { kind: "err", msg: t("slug.edges") };
    if (RESERVED[value]) return { kind: "err", msg: t("slug.reserved", { slug: value }) };
    return { kind: "ok", msg: t("slug.ok") };
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!user) {
      openAuthModal(getCurrentPathForAuthRedirect(window.location));
      return;
    }
    if (pending || !name.trim() || !slug || help.kind === "err") return;

    setPending(true);
    setFormError(null);
    try {
      const workspace = await workspaceService.create({ name: name.trim(), slug });
      // The switcher list and the workspace cookie are stale the moment a
      // workspace exists that was not in them.
      void fetchWorkspaces();
      router.push(`/admin/workspaces/${workspace.id}/general`);
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
      <div className="mt-7 flex max-w-[620px] items-start gap-3 rounded-xl border border-dashed border-[color:var(--aqt-border-2)] p-[18px] text-body text-[color:var(--aqt-fg-muted)]">
        <Lock className="mt-0.5 size-4 shrink-0 text-[color:var(--aqt-rose)]" aria-hidden />
        <div>
          <b className="mb-0.5 block font-semibold text-[color:var(--aqt-fg)]">
            {t("revoked.title")}
          </b>
          {t("revoked.hint")}
        </div>
      </div>
    );
  }

  return (
    <form
      id="create"
      noValidate
      onSubmit={onSubmit}
      className="mt-7 grid max-w-[620px] scroll-mt-[var(--aqt-sticky-top)] gap-4"
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <div>
          <label htmlFor="ws-name" className={cn(EYEBROW_CLASS, "mb-2 block")}>
            {t("name")}
          </label>
          <div className={INPUT_SHELL}>
            <input
              id="ws-name"
              name="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("namePlaceholder")}
              autoComplete="off"
              required
              className={cn(INPUT_FIELD, "font-[family-name:var(--aqt-data)]")}
            />
          </div>
        </div>
        <div>
          <label htmlFor="ws-slug" className={cn(EYEBROW_CLASS, "mb-2 block")}>
            {t("address")}
          </label>
          <div
            className={cn(
              INPUT_SHELL,
              help.kind === "err" &&
                "border-[color:color-mix(in_srgb,var(--aqt-rose)_70%,transparent)]"
            )}
          >
            <span
              aria-hidden
              className="hidden whitespace-nowrap font-mono text-body leading-none text-[color:var(--aqt-fg-dim)] min-[480px]:inline"
            >
              {PLATFORM_ZONE}/workspace/
            </span>
            <input
              id="ws-slug"
              name="slug"
              value={slug}
              // Typing a name with spaces is the common first move; the mock
              // turns it into an address as you type instead of refusing it.
              onChange={(event) => setSlug(event.target.value.toLowerCase().replace(/\s+/g, "-"))}
              placeholder="funny-cup"
              spellCheck={false}
              autoComplete="off"
              required
              aria-describedby="slug-help"
              aria-invalid={help.kind === "err"}
              className={cn(INPUT_FIELD, "font-mono text-body")}
            />
          </div>
          <p
            id="slug-help"
            aria-live="polite"
            className={cn(
              "mt-2 flex min-h-5 items-center gap-[7px] text-caption",
              help.kind === "ok"
                ? "text-[color:var(--aqt-emerald)]"
                : help.kind === "err"
                  ? "text-[color:var(--aqt-rose-text)]"
                  : "text-[color:var(--aqt-fg-dim)]"
            )}
          >
            {help.kind === "ok" ? <Check className="size-3.5 shrink-0" aria-hidden /> : null}
            {help.kind === "err" ? <CircleAlert className="size-3.5 shrink-0" aria-hidden /> : null}
            <span>{help.msg}</span>
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <button type="submit" disabled={pending} className={owtButton({ variant: "primary", size: "lg" })}>
          {user ? (
            t("submit")
          ) : (
            <>
              <LogIn aria-hidden />
              {t("submitSignedOut")}
            </>
          )}
        </button>
        <small className="text-caption text-[color:var(--aqt-fg-dim)]">{t("note")}</small>
      </div>
      {formError ? (
        <p role="alert" className="text-caption text-[color:var(--aqt-rose-text)]">
          {formError}
        </p>
      ) : null}
    </form>
  );
}
