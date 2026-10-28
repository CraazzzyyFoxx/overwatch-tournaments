"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Copy } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText
} from "@/components/ui/input-group";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { PhaseStrip, type PhaseState } from "@/components/kit/PhaseStrip";
import { SaveBar } from "@/components/kit/SaveBar";
import { useInSettingsPreview } from "@/components/kit/SettingsContinuation";
import { SettingGroup, SettingRow, invalidProps } from "@/components/kit/SettingRow";
import { getApiErrorMessage } from "@/lib/api/error";
import { PLATFORM_ZONE } from "@/lib/site/host";
import { notify } from "@/lib/notify";
import workspaceService from "@/services/workspace.service";
import type { Workspace } from "@/types/workspace.types";
import { customDomainIssue } from "./fields";
import { WorkspaceSettingsFrame } from "./WorkspaceSettingsFrame";
import { useFieldIssueText, useWorkspaceSettingsForm } from "./useWorkspaceSettingsForm";
import { adminQueryKeys } from "@/lib/admin/query-keys";

/** DNS propagation is minutes, not seconds; re-checking faster only burns
 * requests on a resolver that has not refreshed yet. */
const VERIFY_POLL_MS = 15000;

/**
 * Lengths search engines show before they cut a snippet. Advice, not limits:
 * the server stores longer text, so the counters warn and never block.
 */
const SEO_TITLE_SHOWN = 60;
const SEO_DESCRIPTION_SHOWN = 160;

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
 * token. A `SaveBar` cannot express "now go edit your DNS", so the `PhaseStrip`
 * says which of the three states the domain is in, and nothing else repeats it.
 */
export function DomainSection({ workspaceId }: Readonly<{ workspaceId: number | null }>) {
  const t = useTranslations("adminWorkspace.workspaceSettings.domain");
  const settings = useWorkspaceSettingsForm(workspaceId, "domain");
  const { patch, invalidate, workspace, errors, reveal } = settings;
  const issueText = useFieldIssueText();
  // As the next page's ghost this section only shows; it must not poll DNS
  // and toast a verification on a page that is about something else.
  const inPreview = useInSettingsPreview();

  const [draftDomain, setDraftDomain] = useState("");
  // The draft is judged once the reader leaves it or tries to save it, and a
  // refusal from the server replaces that judgement until the draft changes.
  const [draftJudged, setDraftJudged] = useState(false);
  const [domainRefusal, setDomainRefusal] = useState<string | null>(null);
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
    setDraftJudged(false);
    setDomainRefusal(null);
    invalidate();
  };

  const setDomainMutation = useMutation({
    mutationFn: (value: string) => workspaceService.setCustomDomain(workspaceId as number, value),
    onSuccess: (updated) => {
      applyDomain(updated);
      notify.success(t("saved"));
    },
    onError: (error) => setDomainRefusal(getApiErrorMessage(error, t("saveError")))
  });

  const draftIssue = customDomainIssue(draftDomain);
  const draftError =
    domainRefusal ?? (draftJudged && draftIssue ? issueText(draftIssue) : undefined);
  const saveDraft = () => {
    setDraftJudged(true);
    if (!draftIssue) setDomainMutation.mutate(draftDomain);
  };

  const verifyMutation = useMutation({
    mutationFn: () => workspaceService.verifyCustomDomain(workspaceId as number),
    onSuccess: (updated) => {
      applyDomain(updated);
      if (updated.custom_domain_verified_at) {
        notify.success(t("verified"));
      } else {
        notify.warning(t("pendingWarning"));
      }
    },
    onError: (error) =>
      notify.apiError(error, {
        title: t("pendingWarning")
      })
  });

  const clearMutation = useMutation({
    mutationFn: () => workspaceService.clearCustomDomain(workspaceId as number),
    onSuccess: (updated) => {
      applyDomain(updated);
      setRemoveOpen(false);
      notify.success(t("removed"));
    },
    onError: (error) => notify.apiError(error, { title: t("removeError") })
  });

  // While a domain is pending we re-check DNS quietly on an interval (no toast
  // spam) and stop the moment it verifies; "Verify now" stays for an immediate
  // check.
  const pending = !!domain.domain && !domain.verifiedAt;
  const poll = useQuery({
    queryKey: adminQueryKeys.workspaceDomainVerify(workspaceId, domain.domain),
    queryFn: () => workspaceService.verifyCustomDomain(workspaceId as number),
    enabled: pending && !inPreview,
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
    notify.success(t("verified"));
  }, [polledVerifiedAt]);

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      notify.success(t("copied"));
    } catch {
      notify.error(t("copyError"));
    }
  };

  const step = domain.verifiedAt ? 2 : domain.domain ? 1 : 0;
  const phaseState = (index: number): PhaseState =>
    index < step ? "done" : index === step ? "current" : "todo";

  return (
    <WorkspaceSettingsFrame workspaceId={workspaceId} settings={settings}>
      {({ form: values, workspace: ws }) => (
        <>
          <SettingGroup
            id="address"
            title={t("groups.address.title")}
            description={t("groups.address.description")}
          >
            <SettingRow
              htmlFor="workspace-subdomain"
              label={t("subdomain")}
              hint={
                values.subdomain
                  ? `https://${values.subdomain}.${PLATFORM_ZONE}`
                  : t("platformUrlOnly")
              }
              error={errors.subdomain}
              stacked
            >
              <InputGroup>
                <InputGroupInput
                  id="workspace-subdomain"
                  value={values.subdomain ?? ""}
                  spellCheck={false}
                  onChange={(event) =>
                    patch({
                      subdomain: event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "")
                    })
                  }
                  onBlur={() => reveal("subdomain")}
                  {...invalidProps("workspace-subdomain", errors.subdomain)}
                />
                <InputGroupAddon align="inline-end">
                  <InputGroupText>.{PLATFORM_ZONE}</InputGroupText>
                </InputGroupAddon>
              </InputGroup>
            </SettingRow>
          </SettingGroup>

          <SettingGroup
            id="custom-domain"
            title={t("customDomain")}
            description={t("groups.customDomain.description")}
            immediate
          >
            <div className="pb-4">
              <PhaseStrip
                phases={[
                  { key: "add", label: t("addDomain"), state: phaseState(0) },
                  { key: "dns", label: t("addDns"), state: phaseState(1) },
                  { key: "verified", label: t("verifyLabel"), state: phaseState(2) }
                ]}
              />
            </div>

            <SettingRow
              htmlFor="workspace-custom-domain"
              label={t("domainLabel")}
              error={draftError}
              stacked
            >
              <div className="flex w-full flex-wrap gap-2">
                <Input
                  id="workspace-custom-domain"
                  className="min-w-[16rem] flex-1"
                  value={draftDomain}
                  placeholder={t("domainPlaceholder")}
                  inputMode="url"
                  spellCheck={false}
                  disabled={!!domain.verifiedAt}
                  onChange={(event) => {
                    setDraftDomain(event.target.value.toLowerCase().trim());
                    setDomainRefusal(null);
                  }}
                  onBlur={() => {
                    if (draftDomain) setDraftJudged(true);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !domain.verifiedAt) saveDraft();
                  }}
                  {...invalidProps("workspace-custom-domain", draftError)}
                />
                {domain.verifiedAt ? (
                  <Button
                    type="button"
                    variant="outline"
                    className="text-danger"
                    disabled={clearMutation.isPending}
                    onClick={() => setRemoveOpen(true)}
                  >
                    {t("removeDomain")}
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={setDomainMutation.isPending}
                    onClick={saveDraft}
                  >
                    {setDomainMutation.isPending ? t("saving") : t("saveDomain")}
                  </Button>
                )}
                {pending ? (
                  <Button
                    type="button"
                    disabled={verifyMutation.isPending}
                    onClick={() => verifyMutation.mutate()}
                  >
                    {verifyMutation.isPending ? t("saving") : t("verifyNow")}
                  </Button>
                ) : null}
              </div>
            </SettingRow>

            {pending ? (
              <SettingRow
                label={t("dnsRecords")}
                hint={t("addRecords", { seconds: VERIFY_POLL_MS / 1000 })}
                stacked
              >
                <DnsRecords
                  records={[
                    { type: "TXT", host: `_owt-verify.${domain.domain}`, value: domain.token ?? "" },
                    { type: "CNAME", host: domain.domain ?? "", value: PLATFORM_ZONE }
                  ]}
                  onCopy={copy}
                />
              </SettingRow>
            ) : null}
          </SettingGroup>

          {/* Each placeholder is what a blank field falls back to, so the
              reader sees what search engines get without filling anything. */}
          <SettingGroup
            id="search"
            title={t("groups.search.title")}
            description={t("groups.search.description")}
          >
            <SettingRow
              htmlFor="workspace-seo-title"
              label={t("seoTitle")}
              count={{ value: (values.seo_title ?? "").length, max: SEO_TITLE_SHOWN, soft: true }}
              stacked
            >
              <Input
                id="workspace-seo-title"
                value={values.seo_title ?? ""}
                placeholder={ws.name}
                onChange={(event) => patch({ seo_title: event.target.value })}
              />
            </SettingRow>
            <SettingRow
              htmlFor="workspace-seo-description"
              label={t("seoDescription")}
              count={{
                value: (values.seo_description ?? "").length,
                max: SEO_DESCRIPTION_SHOWN,
                soft: true
              }}
              stacked
            >
              <Textarea
                id="workspace-seo-description"
                value={values.seo_description ?? ""}
                placeholder={ws.description ?? undefined}
                onChange={(event) => patch({ seo_description: event.target.value })}
              />
            </SettingRow>
          </SettingGroup>

          <SaveBar
            dirty={settings.dirty}
            summary={settings.summary}
            error={settings.error}
            saving={settings.saving}
            onDiscard={settings.discard}
            onSave={settings.save}
          />

          <ConfirmDialog
            open={removeOpen}
            onOpenChange={setRemoveOpen}
            pending={clearMutation.isPending}
            intent={{
              title: t("removeTitle"),
              description: t("removeDescription", {
                domain: domain.domain ?? t("thisDomain"),
                workspace: ws.name
              }),
              confirmLabel: t("removeDomain"),
              tone: "danger"
            }}
            onConfirm={() => clearMutation.mutate()}
          />
        </>
      )}
    </WorkspaceSettingsFrame>
  );
}

interface DnsRecord {
  type: "TXT" | "CNAME";
  host: string;
  value: string;
}

/**
 * The records to add at the DNS provider, each part copyable on its own: a
 * provider's form asks for the host and the value in separate fields, so a
 * copy of only the token left the reader retyping the rest.
 */
function DnsRecords({
  records,
  onCopy
}: Readonly<{ records: readonly DnsRecord[]; onCopy: (value: string) => void }>) {
  const t = useTranslations("adminWorkspace.workspaceSettings.domain");
  return (
    <Table className="table-fixed" wrapperClassName="overflow-visible">
      <TableHeader>
        <TableRow className="border-border/60">
          <TableHead scope="col" className="h-auto w-16 px-0 pb-1.5">
            {t("dnsType")}
          </TableHead>
          <TableHead scope="col" className="h-auto pb-1.5 pl-0 pr-3">
            {t("dnsHost")}
          </TableHead>
          <TableHead scope="col" className="h-auto px-0 pb-1.5">
            {t("dnsValue")}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody className="font-mono">
        {records.map((record) => (
          <TableRow key={record.type} className="border-border/60 hover:bg-transparent">
            <TableCell className="px-0 py-2 align-top text-muted-foreground">{record.type}</TableCell>
            <TableCell className="py-2 pl-0 pr-3 align-top">
              <CopyableValue
                value={record.host}
                label={t("copyHost", { type: record.type })}
                onCopy={onCopy}
              />
            </TableCell>
            <TableCell className="px-0 py-2 align-top">
              <CopyableValue
                value={record.value}
                label={t("copyValue", { type: record.type })}
                onCopy={onCopy}
              />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function CopyableValue({
  value,
  label,
  onCopy
}: Readonly<{ value: string; label: string; onCopy: (value: string) => void }>) {
  return (
    <div className="flex items-start gap-1">
      <span className="min-w-0 flex-1 break-all py-0.5">{value}</span>
      {value ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-6 shrink-0"
          aria-label={label}
          title={label}
          onClick={() => onCopy(value)}
        >
          <Copy aria-hidden className="size-3.5" />
        </Button>
      ) : null}
    </div>
  );
}
