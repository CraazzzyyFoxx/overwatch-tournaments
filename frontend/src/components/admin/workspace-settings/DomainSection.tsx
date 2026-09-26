"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle, Copy } from "lucide-react";

import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { PhaseStrip, type PhaseState } from "@/components/kit/PhaseStrip";
import { SaveBar } from "@/components/kit/SaveBar";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { PLATFORM_ZONE } from "@/lib/site/host";
import { notify } from "@/lib/notify";
import workspaceService from "@/services/workspace.service";
import type { Workspace } from "@/types/workspace.types";
import { Spinner } from "@/components/ui/spinner";
import { WorkspaceSettingsFrame } from "./WorkspaceSettingsFrame";
import { useWorkspaceSettingsForm } from "./useWorkspaceSettingsForm";
import { adminQueryKeys } from "@/lib/admin/query-keys";

/** DNS propagation is minutes, not seconds; re-checking faster only burns
 * requests on a resolver that has not refreshed yet. */
const VERIFY_POLL_MS = 15000;

type DomainState = { domain: string | null; verifiedAt: string | null; token: string | null };

const domainStateOf = (ws: Workspace): DomainState => ({
  domain: ws.custom_domain,
  verifiedAt: ws.custom_domain_verified_at,
  token: ws.custom_domain_verification_token
});

/**
 * Subdomain, custom domain and the text search engines show.
 *
 * The custom domain is a three-step stepper rather than a field with a Save
 * button, because it is not a value the form owns: adding it mints a DNS token
 * server-side, and the domain only starts serving once a resolver can see that
 * token. A `SaveBar` cannot express "now go edit your DNS", so the stepper
 * says which of the three states the domain is in and what closes it.
 */
export function DomainSection({ workspaceId }: Readonly<{ workspaceId: number | null }>) {
  const settings = useWorkspaceSettingsForm(workspaceId, "domain");
  const { patch, invalidate, workspace } = settings;

  const [draftDomain, setDraftDomain] = useState("");
  const [removeOpen, setRemoveOpen] = useState(false);
  const [domain, setDomain] = useState<DomainState>({
    domain: null,
    verifiedAt: null,
    token: null
  });

  // The domain lives outside the form diff, so it re-seeds from the workspace
  // on every read rather than being guarded against refetches: there is no
  // in-progress edit to lose except the input, which is separate.
  useEffect(() => {
    if (!workspace) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDomain(domainStateOf(workspace));
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraftDomain(workspace.custom_domain ?? "");
  }, [workspace]);

  const applyDomain = (updated: Workspace) => {
    setDomain(domainStateOf(updated));
    setDraftDomain(updated.custom_domain ?? "");
    invalidate();
  };

  const setDomainMutation = useMutation({
    mutationFn: (value: string) => workspaceService.setCustomDomain(workspaceId as number, value),
    onSuccess: (updated) => {
      applyDomain(updated);
      notify.success("Custom domain saved — add the DNS records below, then verify");
    },
    onError: (error) => notify.apiError(error, { title: "Could not save the custom domain" })
  });

  const verifyMutation = useMutation({
    mutationFn: () => workspaceService.verifyCustomDomain(workspaceId as number),
    onSuccess: (updated) => {
      applyDomain(updated);
      if (updated.custom_domain_verified_at) {
        notify.success("Custom domain verified");
      } else {
        notify.warning("Verification record not found yet — DNS changes take time to propagate");
      }
    },
    onError: (error) =>
      notify.apiError(error, {
        title: "Verification record not found yet — DNS changes take time to propagate"
      })
  });

  const clearMutation = useMutation({
    mutationFn: () => workspaceService.clearCustomDomain(workspaceId as number),
    onSuccess: (updated) => {
      applyDomain(updated);
      setRemoveOpen(false);
      notify.success("Custom domain removed");
    },
    onError: (error) => notify.apiError(error, { title: "Could not remove the custom domain" })
  });

  // While a domain is pending we re-check DNS quietly on an interval (no toast
  // spam) and stop the moment it verifies; "Verify now" stays for an immediate
  // check.
  const pending = !!domain.domain && !domain.verifiedAt;
  const poll = useQuery({
    queryKey: adminQueryKeys.workspaceDomainVerify(workspaceId, domain.domain),
    queryFn: () => workspaceService.verifyCustomDomain(workspaceId as number),
    enabled: pending,
    refetchInterval: pending ? VERIFY_POLL_MS : false,
    refetchOnWindowFocus: false,
    retry: false,
    gcTime: 0
  });

  const polledVerifiedAt = poll.data?.custom_domain_verified_at;
  useEffect(() => {
    if (!polledVerifiedAt || !poll.data) return;
    // Reacting to a poll result is the "subscribe to an external system" case:
    // the toast and the cache invalidation must fire once per verification, so
    // this cannot move into render.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    applyDomain(poll.data);
    notify.success("Custom domain verified");
  }, [polledVerifiedAt]);

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      notify.success("Copied to clipboard");
    } catch {
      notify.error("Could not copy to clipboard");
    }
  };

  const step = domain.verifiedAt ? 2 : domain.domain ? 1 : 0;
  const phaseState = (index: number): PhaseState =>
    index < step ? "done" : index === step ? "current" : "todo";

  return (
    <WorkspaceSettingsFrame workspaceId={workspaceId} settings={settings}>
      {({ form: values, workspace: ws }) => (
        <>
          <Card>
            <CardContent className="flex flex-col gap-4 pt-6">
              <div>
                <Label htmlFor="workspace-subdomain">Subdomain</Label>
                <Input
                  id="workspace-subdomain"
                  className="mt-1.5"
                  value={values.subdomain ?? ""}
                  placeholder="my-team"
                  onChange={(event) =>
                    patch({
                      subdomain: event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "")
                    })
                  }
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  {values.subdomain
                    ? `${values.subdomain}.${PLATFORM_ZONE}`
                    : "Leave blank to use the platform URL only"}
                </p>
              </div>

              <div>
                <Label htmlFor="workspace-seo-title">SEO title</Label>
                <Input
                  id="workspace-seo-title"
                  className="mt-1.5"
                  value={values.seo_title ?? ""}
                  placeholder="Displayed in browser tabs and search results"
                  onChange={(event) => patch({ seo_title: event.target.value })}
                />
              </div>
              <div>
                <Label htmlFor="workspace-seo-description">SEO description</Label>
                <Textarea
                  id="workspace-seo-description"
                  className="mt-1.5"
                  value={values.seo_description ?? ""}
                  placeholder="Optional meta description shown in search results"
                  onChange={(event) => patch({ seo_description: event.target.value })}
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="flex flex-col gap-3 pt-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className={EYEBROW_CLASS}>Custom domain</h2>
                {domain.verifiedAt ? (
                  <StatusPill tone="success">
                    <CheckCircle aria-hidden className="size-3" /> Verified · live
                  </StatusPill>
                ) : domain.domain ? (
                  <StatusPill tone="warning">
                    <Spinner className="size-3" />{" "}
                    Pending — checking DNS…
                  </StatusPill>
                ) : null}
              </div>

              <PhaseStrip
                phases={[
                  { key: "add", label: "Add domain", state: phaseState(0) },
                  { key: "dns", label: "Add DNS records", state: phaseState(1) },
                  { key: "verified", label: "Verified", state: phaseState(2) }
                ]}
              />

              <div className="flex flex-wrap gap-2">
                <Input
                  id="workspace-custom-domain"
                  aria-label="Custom domain"
                  className="min-w-[16rem] flex-1"
                  value={draftDomain}
                  placeholder="tourney.example.com"
                  disabled={!!domain.verifiedAt}
                  onChange={(event) => setDraftDomain(event.target.value.toLowerCase().trim())}
                />
                {domain.verifiedAt ? (
                  <Button
                    type="button"
                    variant="outline"
                    className="text-danger"
                    disabled={clearMutation.isPending}
                    onClick={() => setRemoveOpen(true)}
                  >
                    Remove domain
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={setDomainMutation.isPending}
                    onClick={() => {
                      if (!draftDomain) {
                        notify.error("Enter a domain such as tourney.example.com first.");
                        return;
                      }
                      setDomainMutation.mutate(draftDomain);
                    }}
                  >
                    {setDomainMutation.isPending ? "Saving…" : "Save domain"}
                  </Button>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Your workspace goes live on this domain <strong>only after verification</strong>.
                Leave blank to use the platform URL / subdomain only.
              </p>

              {pending ? (
                <div className="flex flex-col gap-3 rounded-md border border-border bg-muted/30 p-3">
                  <div>
                    <h3 className="text-xs font-semibold text-foreground">
                      How to connect your domain
                    </h3>
                    <ol className="mt-1 list-decimal space-y-1 pl-4 text-xs text-muted-foreground">
                      <li>Open your DNS provider (Cloudflare, Namecheap, GoDaddy…).</li>
                      <li>Add the two records below exactly as shown.</li>
                      <li>
                        DNS can take a few minutes to propagate — we re-check automatically every{" "}
                        <span className="tabular-nums">{VERIFY_POLL_MS / 1000}s</span>, or press{" "}
                        <strong>Verify now</strong>.
                      </li>
                    </ol>
                  </div>
                  <div className="flex flex-col gap-1.5 text-xs">
                    <div className="grid grid-cols-[auto_1fr_auto] items-center gap-2 font-mono">
                      <span className="text-muted-foreground">TXT</span>
                      <span className="break-all">{`_owt-verify.${domain.domain}`}</span>
                      <span className="break-all text-muted-foreground">(ownership)</span>
                      <span className="text-muted-foreground">value</span>
                      <span className="break-all">{domain.token}</span>
                      {domain.token ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="size-5"
                          aria-label="Copy TXT value"
                          onClick={() => domain.token && copy(domain.token)}
                        >
                          <Copy aria-hidden className="size-3" />
                        </Button>
                      ) : (
                        <span />
                      )}
                    </div>
                    <div className="grid grid-cols-[auto_1fr_auto] items-center gap-2 font-mono">
                      <span className="text-muted-foreground">CNAME</span>
                      <span className="break-all">{domain.domain}</span>
                      <span className="break-all text-muted-foreground">
                        points to {PLATFORM_ZONE}
                      </span>
                    </div>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    className="self-start"
                    disabled={verifyMutation.isPending}
                    onClick={() => verifyMutation.mutate()}
                  >
                    {verifyMutation.isPending ? "Checking…" : "Verify now"}
                  </Button>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <SaveBar
            dirty={settings.dirty}
            summary={settings.summary}
            saving={settings.saving}
            onDiscard={settings.discard}
            onSave={settings.save}
          />

          <ConfirmDialog
            open={removeOpen}
            onOpenChange={setRemoveOpen}
            pending={clearMutation.isPending}
            intent={{
              title: "Remove custom domain",
              description: `${domain.domain ?? "This domain"} stops serving ${ws.name} the moment you confirm — visitors land on the platform URL instead. You can add it back later, but the DNS records have to be verified again.`,
              confirmLabel: "Remove domain",
              tone: "danger"
            }}
            onConfirm={() => clearMutation.mutate()}
          />
        </>
      )}
    </WorkspaceSettingsFrame>
  );
}
