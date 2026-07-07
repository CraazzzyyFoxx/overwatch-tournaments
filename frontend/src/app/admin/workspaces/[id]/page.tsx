"use client";

import { use, useEffect, useState, type CSSProperties } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle, XCircle, Copy, Loader2 } from "lucide-react";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import { notify } from "@/lib/notify";
import { usePermissions } from "@/hooks/usePermissions";
import { deriveWorkspacePalette } from "@/lib/workspace-theme";
import { PLATFORM_ZONE } from "@/lib/host";
import workspaceService from "@/services/workspace.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { Workspace } from "@/types/workspace.types";

const ACCEPTED_IMAGE_TYPES = "image/webp,image/png,image/jpeg,image/gif";
const MAX_FILE_SIZE = 2 * 1024 * 1024; // 2 MB
const VERIFY_POLL_MS = 15000;

interface EditFormData {
  name: string;
  description: string;
  branding_enabled: boolean;
  brand_primary: string | null;
  brand_secondary: string | null;
  brand_background: string | null;
  brand_surface: string | null;
  brand_accent: string | null;
  brand_foreground: string | null;
  brand_muted: string | null;
  brand_border: string | null;
  brand_ring: string | null;
  brand_destructive: string | null;
  subdomain: string | null;
  seo_title: string | null;
  seo_description: string | null;
}

function formFromWorkspace(ws: Workspace): EditFormData {
  return {
    name: ws.name,
    description: ws.description ?? "",
    branding_enabled: ws.branding_enabled,
    brand_primary: ws.brand_primary,
    brand_secondary: ws.brand_secondary,
    brand_background: ws.brand_background,
    brand_surface: ws.brand_surface,
    brand_accent: ws.brand_accent ?? null,
    brand_foreground: ws.brand_foreground ?? null,
    brand_muted: ws.brand_muted ?? null,
    brand_border: ws.brand_border ?? null,
    brand_ring: ws.brand_ring ?? null,
    brand_destructive: ws.brand_destructive ?? null,
    subdomain: ws.subdomain,
    seo_title: ws.seo_title,
    seo_description: ws.seo_description,
  };
}

function BrandColorField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string | null | undefined;
  onChange: (value: string) => void;
}) {
  const hex = value ?? "";
  const valid = /^#[0-9a-fA-F]{6}$/.test(hex);
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <div className="mt-1 flex items-center gap-2">
        <input
          type="color"
          aria-label={`${label} color`}
          value={valid ? hex : "#000000"}
          onChange={(e) => onChange(e.target.value)}
          className="h-9 w-10 shrink-0 cursor-pointer rounded border border-input bg-transparent p-0.5"
        />
        <Input
          id={id}
          value={hex}
          onChange={(e) => onChange(e.target.value)}
          placeholder="#000000"
          className="font-mono"
        />
      </div>
    </div>
  );
}

const errorMessage = (error: unknown, fallback: string): string =>
  error instanceof Error ? error.message : fallback;

export default function WorkspaceEditPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: idParam } = use(params);
  const id = Number(idParam);
  const router = useRouter();
  const queryClient = useQueryClient();
  const { isSuperuser, isWorkspaceAdmin, isLoaded } = usePermissions();
  const fetchWorkspaces = useWorkspaceStore((s) => s.fetchWorkspaces);

  const wsQuery = useQuery({
    queryKey: ["admin-workspace", id],
    queryFn: () => workspaceService.getById(id),
    enabled: Number.isFinite(id),
  });
  const ws = wsQuery.data;

  const [form, setForm] = useState<EditFormData | null>(null);
  const [iconFile, setIconFile] = useState<File | null>(null);
  const [iconPreview, setIconPreview] = useState<string | null>(null);
  const [customDomainInput, setCustomDomainInput] = useState("");
  const [domain, setDomain] = useState<{
    domain: string | null;
    verifiedAt: string | null;
    token: string | null;
  }>({ domain: null, verifiedAt: null, token: null });

  // Seed local state once the workspace loads (guarded so a background refetch
  // never clobbers in-progress edits).
  const [seeded, setSeeded] = useState(false);
  useEffect(() => {
    if (!ws || seeded) return;
    setForm(formFromWorkspace(ws));
    setIconPreview(ws.icon_url ?? null);
    setCustomDomainInput(ws.custom_domain ?? "");
    setDomain({
      domain: ws.custom_domain,
      verifiedAt: ws.custom_domain_verified_at,
      token: ws.custom_domain_verification_token,
    });
    setSeeded(true);
  }, [ws, seeded]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["admin-workspaces"] });
    queryClient.invalidateQueries({ queryKey: ["admin-workspace", id] });
    fetchWorkspaces();
  };

  const applyDomainResult = (updated: Workspace) => {
    setDomain({
      domain: updated.custom_domain,
      verifiedAt: updated.custom_domain_verified_at,
      token: updated.custom_domain_verification_token,
    });
    setCustomDomainInput(updated.custom_domain ?? "");
  };

  const updateMutation = useMutation({
    mutationFn: async (data: Partial<EditFormData>) => {
      await workspaceService.update(id, data);
      if (iconFile) await workspaceService.uploadIcon(id, iconFile);
    },
    onSuccess: () => {
      invalidate();
      notify.success("Workspace updated");
      router.push("/admin/workspaces");
    },
    onError: (error) => notify.error(errorMessage(error, "Failed to save workspace")),
  });

  const deleteIconMutation = useMutation({
    mutationFn: () => workspaceService.deleteIcon(id),
    onSuccess: () => {
      invalidate();
      setIconPreview(null);
      notify.success("Icon removed");
    },
  });

  const setDomainMutation = useMutation({
    mutationFn: (value: string) => workspaceService.setCustomDomain(id, value),
    onSuccess: (updated) => {
      applyDomainResult(updated);
      invalidate();
      notify.success("Custom domain saved — add the DNS records below, then verify");
    },
    onError: (error) => notify.error(errorMessage(error, "Failed to save custom domain")),
  });

  const verifyMutation = useMutation({
    mutationFn: () => workspaceService.verifyCustomDomain(id),
    onSuccess: (updated) => {
      applyDomainResult(updated);
      invalidate();
      notify.success("Custom domain verified");
    },
    onError: (error) =>
      notify.error(
        errorMessage(error, "Verification record not found yet — DNS changes can take time to propagate")
      ),
  });

  const clearDomainMutation = useMutation({
    mutationFn: () => workspaceService.clearCustomDomain(id),
    onSuccess: (updated) => {
      applyDomainResult(updated);
      invalidate();
      notify.success("Custom domain removed");
    },
    onError: (error) => notify.error(errorMessage(error, "Failed to remove custom domain")),
  });

  // Auto-poll verification while a domain is pending: the domain only goes live
  // once verified, so we quietly re-check DNS on an interval (no toast spam) and
  // stop as soon as it verifies. The manual "Verify" button stays for an
  // immediate check.
  const domainPending = !!domain.domain && !domain.verifiedAt;
  const verifyPoll = useQuery({
    queryKey: ["admin-workspace-domain-verify", id, domain.domain],
    queryFn: () => workspaceService.verifyCustomDomain(id),
    enabled: domainPending,
    refetchInterval: domainPending ? VERIFY_POLL_MS : false,
    refetchOnWindowFocus: false,
    retry: false,
    gcTime: 0,
  });
  useEffect(() => {
    if (verifyPoll.data?.custom_domain_verified_at) {
      applyDomainResult(verifyPoll.data);
      invalidate();
      notify.success("Custom domain verified");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [verifyPoll.data?.custom_domain_verified_at]);

  const handleIconSelect = (file: File) => {
    setIconFile(file);
    setIconPreview(URL.createObjectURL(file));
  };

  const canManage = isLoaded && (isSuperuser || isWorkspaceAdmin(id));

  const brandingPreview = form
    ? deriveWorkspacePalette({ ...form, branding_enabled: true })
    : null;

  if (wsQuery.isLoading || !isLoaded) {
    return (
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading workspace…
      </div>
    );
  }

  if (!ws || !form) {
    return (
      <div className="flex flex-col items-center gap-3 py-24 text-center">
        <p className="text-sm text-muted-foreground">Workspace not found.</p>
        <Button asChild variant="outline">
          <Link href="/admin/workspaces">Back to workspaces</Link>
        </Button>
      </div>
    );
  }

  if (!canManage) {
    return (
      <div className="flex flex-col items-center gap-3 py-24 text-center">
        <p className="text-sm text-muted-foreground">
          You don&apos;t have permission to manage this workspace.
        </p>
        <Button asChild variant="outline">
          <Link href="/admin/workspaces">Back to workspaces</Link>
        </Button>
      </div>
    );
  }

  const handleCopy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      notify.success("Copied to clipboard");
    } catch {
      notify.error("Could not copy to clipboard");
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // Blank colour → null (backend rejects "" via the #RRGGBB pattern; a missing
    // token falls back to the derived default). Custom domain is its own flow.
    const hexOrNull = (v: string | null) => v?.trim() || null;
    updateMutation.mutate({
      name: form.name,
      description: form.description,
      branding_enabled: form.branding_enabled,
      brand_primary: hexOrNull(form.brand_primary),
      brand_secondary: hexOrNull(form.brand_secondary),
      brand_background: hexOrNull(form.brand_background),
      brand_surface: hexOrNull(form.brand_surface),
      brand_accent: hexOrNull(form.brand_accent),
      brand_foreground: hexOrNull(form.brand_foreground),
      brand_muted: hexOrNull(form.brand_muted),
      brand_border: hexOrNull(form.brand_border),
      brand_ring: hexOrNull(form.brand_ring),
      brand_destructive: hexOrNull(form.brand_destructive),
      subdomain: form.subdomain?.trim() || null,
      seo_title: form.seo_title?.trim() || null,
      seo_description: form.seo_description?.trim() || null,
    });
  };

  const patch = (changes: Partial<EditFormData>) => setForm((f) => (f ? { ...f, ...changes } : f));

  return (
    <form onSubmit={handleSubmit} className="mx-auto flex max-w-3xl flex-col gap-6 pb-16">
      <AdminPageHeader
        title={`Edit ${ws.name}`}
        description={`Workspace “${ws.slug}” — branding, domains and metadata`}
        actions={
          <Button asChild variant="ghost" size="sm">
            <Link href="/admin/workspaces">
              <ArrowLeft className="mr-2 h-4 w-4" /> Back
            </Link>
          </Button>
        }
      />

      {/* Basics */}
      <section className="space-y-4 rounded-lg border p-4">
        <div>
          <Label htmlFor="edit-name">Name</Label>
          <Input id="edit-name" value={form.name} onChange={(e) => patch({ name: e.target.value })} />
        </div>
        <div>
          <Label htmlFor="edit-description">Description</Label>
          <Textarea
            id="edit-description"
            value={form.description}
            onChange={(e) => patch({ description: e.target.value })}
          />
        </div>
        <div>
          <Label>Icon</Label>
          <div className="mt-1.5">
            <EditableAvatar
              src={iconPreview}
              name={form.name}
              size={64}
              shape="rounded"
              busy={deleteIconMutation.isPending}
              onSelectFile={handleIconSelect}
              onDelete={
                iconPreview
                  ? () => {
                      if (ws.icon_url && !iconFile) {
                        deleteIconMutation.mutate();
                      } else {
                        setIconFile(null);
                        setIconPreview(ws.icon_url || null);
                      }
                    }
                  : undefined
              }
              accept={ACCEPTED_IMAGE_TYPES}
              maxSizeBytes={MAX_FILE_SIZE}
              onError={(message) => notify.error(message)}
            />
          </div>
          <p className="mt-1 text-xs text-muted-foreground">PNG, JPEG, WebP or GIF, max 2 MB</p>
        </div>
      </section>

      {/* Branding */}
      <section className="space-y-3 rounded-lg border p-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <Label htmlFor="branding-enabled">Site branding</Label>
            <p className="text-xs text-muted-foreground">
              Custom palette for this workspace on the main public site
            </p>
          </div>
          <Switch
            id="branding-enabled"
            checked={form.branding_enabled}
            onCheckedChange={(checked) => patch({ branding_enabled: checked })}
          />
        </div>

        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Seed colours
        </p>
        <div className="grid grid-cols-2 gap-3">
          <BrandColorField id="brand-primary" label="Primary accent" value={form.brand_primary} onChange={(v) => patch({ brand_primary: v })} />
          <BrandColorField id="brand-secondary" label="Secondary accent" value={form.brand_secondary} onChange={(v) => patch({ brand_secondary: v })} />
          <BrandColorField id="brand-background" label="Background" value={form.brand_background} onChange={(v) => patch({ brand_background: v })} />
          <BrandColorField id="brand-surface" label="Surface" value={form.brand_surface} onChange={(v) => patch({ brand_surface: v })} />
        </div>

        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Core palette · optional overrides
        </p>
        <p className="-mt-2 text-[11px] text-muted-foreground">
          Leave blank to derive from the seed colours above.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <BrandColorField id="brand-accent" label="Accent" value={form.brand_accent} onChange={(v) => patch({ brand_accent: v })} />
          <BrandColorField id="brand-foreground" label="Foreground (text)" value={form.brand_foreground} onChange={(v) => patch({ brand_foreground: v })} />
          <BrandColorField id="brand-muted" label="Muted surface" value={form.brand_muted} onChange={(v) => patch({ brand_muted: v })} />
          <BrandColorField id="brand-border" label="Border" value={form.brand_border} onChange={(v) => patch({ brand_border: v })} />
          <BrandColorField id="brand-ring" label="Focus ring" value={form.brand_ring} onChange={(v) => patch({ brand_ring: v })} />
          <BrandColorField id="brand-destructive" label="Destructive" value={form.brand_destructive} onChange={(v) => patch({ brand_destructive: v })} />
        </div>

        {brandingPreview ? (
          <div
            className="rounded-md border p-3"
            style={{ ...brandingPreview, background: "var(--aqt-bg)" } as CSSProperties}
          >
            <div className="text-xs font-medium" style={{ color: "var(--aqt-fg)" }}>
              Preview
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              <span className="rounded px-2 py-1 text-xs font-medium" style={{ background: "var(--aqt-teal)", color: "hsl(var(--primary-foreground))" }}>
                Primary
              </span>
              <span className="rounded px-2 py-1 text-xs font-medium" style={{ background: "var(--aqt-violet)", color: "hsl(var(--secondary-foreground))" }}>
                Secondary
              </span>
              <span className="rounded px-2 py-1 text-xs" style={{ background: "var(--aqt-card)", color: "var(--aqt-fg-muted)", border: "1px solid var(--aqt-border)" }}>
                Surface
              </span>
              <span className="rounded px-2 py-1 text-xs font-medium" style={{ background: "hsl(var(--destructive))", color: "hsl(var(--destructive-foreground))" }}>
                Destructive
              </span>
            </div>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            Set at least a primary accent and a background to preview. Backgrounds are clamped to a
            dark shade to keep text readable.
          </p>
        )}
      </section>

      {/* Domains & SEO */}
      <section className="space-y-4 rounded-lg border p-4">
        <div>
          <Label htmlFor="edit-subdomain">Subdomain</Label>
          <Input
            id="edit-subdomain"
            value={form.subdomain ?? ""}
            onChange={(e) => patch({ subdomain: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "") })}
            placeholder="my-team"
          />
          <p className="mt-1 text-xs text-muted-foreground">
            {form.subdomain ? `${form.subdomain}.${PLATFORM_ZONE}` : "Leave blank to use the platform URL only"}
          </p>
        </div>

        <div className="space-y-2 border-t pt-4">
          <div className="flex items-center justify-between gap-2">
            <Label htmlFor="edit-custom-domain">Custom domain</Label>
            {domain.verifiedAt ? (
              <Badge variant="secondary" className="gap-1">
                <CheckCircle className="h-3 w-3 text-emerald-500" /> Verified · live
              </Badge>
            ) : domain.domain ? (
              <Badge variant="outline" className="gap-1">
                <Loader2 className="h-3 w-3 animate-spin text-amber-500" /> Pending — checking DNS…
              </Badge>
            ) : null}
          </div>
          <div className="flex gap-2">
            <Input
              id="edit-custom-domain"
              value={customDomainInput}
              onChange={(e) => setCustomDomainInput(e.target.value.toLowerCase().trim())}
              placeholder="tourney.example.com"
              disabled={!!domain.verifiedAt}
            />
            {domain.verifiedAt ? (
              <Button
                type="button"
                variant="outline"
                className="text-destructive"
                disabled={clearDomainMutation.isPending}
                onClick={() => clearDomainMutation.mutate()}
              >
                Remove
              </Button>
            ) : (
              <Button
                type="button"
                variant="outline"
                disabled={!customDomainInput || setDomainMutation.isPending}
                onClick={() => setDomainMutation.mutate(customDomainInput)}
              >
                {setDomainMutation.isPending ? "Saving…" : "Save domain"}
              </Button>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            Your workspace goes live on this domain <strong>only after verification</strong>. Leave
            blank to use the platform URL / subdomain only.
          </p>

          {domain.domain && !domain.verifiedAt ? (
            <div className="space-y-3 rounded-md border bg-muted/30 p-3">
              <div>
                <p className="text-xs font-semibold">How to connect your domain</p>
                <ol className="mt-1 list-decimal space-y-1 pl-4 text-xs text-muted-foreground">
                  <li>Open your DNS provider (Cloudflare, Namecheap, GoDaddy…).</li>
                  <li>Add the two records below exactly as shown.</li>
                  <li>
                    DNS can take a few minutes to propagate — we re-check automatically every 15s,
                    or press <strong>Verify now</strong>.
                  </li>
                </ol>
              </div>
              <div className="space-y-1.5 text-xs">
                <div className="grid grid-cols-[auto_1fr_auto] items-center gap-2 font-mono">
                  <span className="text-muted-foreground">TXT</span>
                  <span className="break-all">{`_owt-verify.${domain.domain}`}</span>
                  <span className="break-all text-muted-foreground">(ownership)</span>
                  <span className="text-muted-foreground">↳ value</span>
                  <span className="break-all">{domain.token}</span>
                  {domain.token ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-5 w-5"
                      aria-label="Copy TXT value"
                      onClick={() => domain.token && handleCopy(domain.token)}
                    >
                      <Copy className="h-3 w-3" />
                    </Button>
                  ) : (
                    <span />
                  )}
                </div>
                <div className="grid grid-cols-[auto_1fr_auto] items-center gap-2 font-mono">
                  <span className="text-muted-foreground">CNAME</span>
                  <span className="break-all">{domain.domain}</span>
                  <span className="break-all text-muted-foreground">→ {PLATFORM_ZONE}</span>
                </div>
              </div>
              <Button
                type="button"
                size="sm"
                disabled={verifyMutation.isPending}
                onClick={() => verifyMutation.mutate()}
              >
                {verifyMutation.isPending ? "Checking…" : "Verify now"}
              </Button>
            </div>
          ) : null}
        </div>

        <div>
          <Label htmlFor="edit-seo-title">SEO title</Label>
          <Input
            id="edit-seo-title"
            value={form.seo_title ?? ""}
            onChange={(e) => patch({ seo_title: e.target.value })}
            placeholder="Displayed in browser tabs and search results"
          />
        </div>
        <div>
          <Label htmlFor="edit-seo-description">SEO description</Label>
          <Textarea
            id="edit-seo-description"
            value={form.seo_description ?? ""}
            onChange={(e) => patch({ seo_description: e.target.value })}
            placeholder="Optional meta description shown in search results"
          />
        </div>
      </section>

      <div className="flex items-center justify-end gap-2">
        <Button asChild variant="ghost">
          <Link href="/admin/workspaces">Cancel</Link>
        </Button>
        <Button type="submit" disabled={updateMutation.isPending}>
          {updateMutation.isPending ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}
