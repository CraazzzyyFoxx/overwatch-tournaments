"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Share2, Download, Link2, Check, Copy } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";
import type { PlayerRoleTint } from "@/lib/roster/player-role";
import type { FormResult } from "@/app/(site)/users/components/shared/atoms";
import type { Translate } from "@/app/(site)/users/components/shared/list-utils";

/** Serializable data needed to render the shareable player card. */
export interface ShareCardData {
  name: string;
  tag: string | null;
  role: string | null;
  roleTint: PlayerRoleTint | null;
  division: number | null;
  winrate: number | null;
  avgPlacement: number | null;
  titles: number;
  tournaments: number;
  mapsWon: number;
  mapsTotal: number;
  form: FormResult[];
}

const BTN =
  "inline-flex items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.03)] px-2.5 py-1.5 text-caption font-semibold text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-fg)] disabled:opacity-50";

const CARD_W = 1200;
const CARD_H = 630;

/** Resolve a CSS custom-property font stack (e.g. `var(--aqt-display)`) to the
 * concrete family list — next/font emits a hashed family name, so we can't hard
 * code it; we read it back from a throwaway probe element. */
function resolveFamily(varExpr: string): string {
  const probe = document.createElement("span");
  probe.style.cssText = `position:absolute;visibility:hidden;font-family:${varExpr}`;
  document.body.appendChild(probe);
  const fam = getComputedStyle(probe).fontFamily || "system-ui, sans-serif";
  document.body.removeChild(probe);
  return fam;
}

/** Last-resort colour when a design token cannot be resolved from the document
 *  (e.g. the card renders before stylesheets settle). Canvas 2D cannot take
 *  `var()`, so this has to be a literal — it is `--aqt-fg-faint`
 *  (`hsl(214 10% 52%)`) frozen to hex, not a new colour. */
const TOKEN_FALLBACK = "#788391";

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || TOKEN_FALLBACK;
}

function initialsFrom(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  const single = parts[0] ?? "?";
  return single.slice(0, 2).toUpperCase();
}

function roundRectPath(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

/** Fit `text` into `maxWidth` by shrinking the font from `size` down to `min`. */
function fitFontSize(
  ctx: CanvasRenderingContext2D,
  text: string,
  family: string,
  weight: number,
  size: number,
  min: number,
  maxWidth: number
): number {
  let s = size;
  while (s > min) {
    ctx.font = `${weight} ${s}px ${family}`;
    if (ctx.measureText(text).width <= maxWidth) break;
    s -= 2;
  }
  return s;
}

interface Palette {
  bg: string;
  border: string;
  fg: string;
  fgMuted: string;
  fgFaint: string;
  teal: string;
  tank: string;
  damage: string;
  support: string;
  flex: string;
  emerald: string;
  rose: string;
  amber: string;
}

function drawCard(
  ctx: CanvasRenderingContext2D,
  card: ShareCardData,
  onest: string,
  mono: string,
  C: Palette,
  profileUrl: string,
  t: Translate
) {
  const roleColor = card.roleTint ? C[card.roleTint] : C.teal;
  // The card is rasterised for public sharing, so every glyph on it has to be
  // in the viewer's locale. Canvas has no text transform — uppercase here.
  const roleLabel = (card.role ?? t("users.profile.share.rolePlayer")).toUpperCase();

  // ground
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, CARD_W, CARD_H);

  // faint grid
  ctx.save();
  ctx.strokeStyle = C.border;
  ctx.globalAlpha = 0.5;
  ctx.lineWidth = 1;
  for (let x = 60; x < CARD_W; x += 60) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, CARD_H);
    ctx.stroke();
  }
  for (let y = 60; y < CARD_H; y += 60) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(CARD_W, y);
    ctx.stroke();
  }
  ctx.restore();

  // role-tinted corner wash (only when the player has an assigned role)
  if (card.roleTint) {
    const wash = ctx.createRadialGradient(150, -40, 40, 150, -40, 720);
    wash.addColorStop(0, roleColor);
    wash.addColorStop(1, "transparent");
    ctx.save();
    ctx.globalAlpha = 0.16;
    ctx.fillStyle = wash;
    ctx.fillRect(0, 0, CARD_W, CARD_H);
    ctx.restore();
  }

  // spectrum top bar
  const spectrum = ctx.createLinearGradient(0, 0, CARD_W, 0);
  spectrum.addColorStop(0, C.tank);
  spectrum.addColorStop(0.5, C.damage);
  spectrum.addColorStop(1, C.support);
  ctx.fillStyle = spectrum;
  ctx.fillRect(0, 0, CARD_W, 6);

  const PAD = 64;

  // coordinate labels
  ctx.textBaseline = "alphabetic";
  ctx.font = `600 18px ${mono}`;
  ctx.fillStyle = C.fgFaint;
  ctx.textAlign = "left";
  ctx.fillText(`// ${t("users.profile.share.heading").toUpperCase()}`, PAD, 66);
  ctx.textAlign = "right";
  ctx.fillText(roleLabel, CARD_W - PAD, 66);
  ctx.textAlign = "left";

  // avatar (role gradient + initials)
  const AV = 150;
  const avX = PAD;
  const avY = 150;
  const avGrad = ctx.createLinearGradient(avX, avY, avX + AV, avY + AV);
  avGrad.addColorStop(0, roleColor);
  avGrad.addColorStop(1, C.bg);
  roundRectPath(ctx, avX, avY, AV, AV, 26);
  ctx.fillStyle = avGrad;
  ctx.fill();
  ctx.lineWidth = 1;
  ctx.strokeStyle = C.border;
  ctx.stroke();
  ctx.fillStyle = C.bg;
  ctx.font = `800 64px ${onest}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(initialsFrom(card.name), avX + AV / 2, avY + AV / 2 + 4);

  // name + tag
  const nameX = avX + AV + 34;
  const nameMaxW = CARD_W - nameX - PAD;
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
  const nameSize = fitFontSize(ctx, card.name, onest, 600, 68, 40, nameMaxW);
  ctx.font = `600 ${nameSize}px ${onest}`;
  ctx.fillStyle = C.fg;
  ctx.fillText(card.name, nameX, 218);
  const nameW = ctx.measureText(card.name).width;
  if (card.tag) {
    ctx.font = `500 24px ${mono}`;
    ctx.fillStyle = C.fgFaint;
    ctx.fillText(`#${card.tag}`, Math.min(nameX + nameW + 14, CARD_W - PAD - 90), 218);
  }

  // meta line
  ctx.font = `500 21px ${mono}`;
  ctx.fillStyle = C.fgMuted;
  const meta = [
    roleLabel,
    card.division != null
      ? t("users.profile.share.division", { division: card.division }).toUpperCase()
      : null,
    t("users.profile.share.events", { count: card.tournaments }).toUpperCase()
  ]
    .filter(Boolean)
    .join("   ·   ");
  ctx.fillText(meta, nameX, 258);

  // divider
  ctx.strokeStyle = C.border;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(PAD, 332);
  ctx.lineTo(CARD_W - PAD, 332);
  ctx.stroke();

  // KPI row
  const winrateColor =
    card.winrate == null
      ? C.fgMuted
      : card.winrate >= 60
        ? C.emerald
        : card.winrate >= 50
          ? C.amber
          : C.rose;
  const kpis: { label: string; value: string; sub?: string; color: string }[] = [
    {
      label: t("users.profile.share.winrate"),
      value: card.winrate != null ? `${Math.round(card.winrate)}%` : "—",
      color: winrateColor
    },
    {
      label: t("users.profile.share.avgPlace"),
      value: card.avgPlacement != null && Number.isFinite(card.avgPlacement) ? card.avgPlacement.toFixed(1) : "—",
      color: C.fg
    },
    {
      label: t("users.profile.share.titles"),
      value: `${card.titles}`,
      color: card.titles > 0 ? C.amber : C.fg
    },
    {
      label: t("users.profile.share.mapsWon"),
      value: `${card.mapsWon}`,
      sub: `/${card.mapsTotal}`,
      color: C.fg
    }
  ];
  const colW = (CARD_W - PAD * 2) / kpis.length;
  kpis.forEach((k, i) => {
    const x = PAD + i * colW;
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
    ctx.font = `600 17px ${mono}`;
    ctx.fillStyle = C.fgFaint;
    ctx.fillText(k.label.toUpperCase(), x, 388);
    ctx.font = `700 60px ${onest}`;
    ctx.fillStyle = k.color;
    ctx.fillText(k.value, x, 448);
    if (k.sub) {
      const vw = ctx.measureText(k.value).width;
      ctx.font = `700 30px ${onest}`;
      ctx.fillStyle = C.fgFaint;
      ctx.fillText(k.sub, x + vw + 4, 448);
    }
  });

  // form chips
  ctx.font = `600 16px ${mono}`;
  ctx.fillStyle = C.fgFaint;
  ctx.textAlign = "left";
  ctx.fillText(t("users.profile.share.formLast", { count: card.form.length }).toUpperCase(), PAD, 512);
  const chip = 30;
  const gap = 8;
  const chipY = 526;
  const chipColor = (r: FormResult) => (r === "W" ? C.emerald : r === "L" ? C.rose : C.amber);
  card.form.slice(0, 10).forEach((r, i) => {
    const x = PAD + i * (chip + gap);
    roundRectPath(ctx, x, chipY, chip, chip, 6);
    ctx.fillStyle = chipColor(r);
    ctx.fill();
    ctx.fillStyle = C.bg;
    ctx.font = `700 15px ${mono}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(r, x + chip / 2, chipY + chip / 2 + 1);
  });

  // footer url
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
  ctx.font = `600 18px ${mono}`;
  ctx.fillStyle = C.teal;
  ctx.fillText(profileUrl, PAD, CARD_H - 30);
}

type CopyState = "idle" | "img" | "link" | "download";

interface SharePlayerCardProps {
  card: ShareCardData;
}

const SharePlayerCard = ({ card }: SharePlayerCardProps) => {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const [copyState, setCopyState] = useState<CopyState>("idle");
  // Callback ref in state: Radix portals mount the dialog content one commit
  // after `open` flips, so a plain ref is still null when an `[open]` effect runs.
  const [canvas, setCanvas] = useState<HTMLCanvasElement | null>(null);
  const flashTimer = useRef<number | null>(null);

  const flash = useCallback((s: CopyState) => {
    setCopyState(s);
    if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setCopyState("idle"), 1600);
  }, []);

  useEffect(() => {
    return () => {
      if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    };
  }, []);

  useEffect(() => {
    if (!canvas) return;
    let cancelled = false;
    const render = async () => {
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      try {
        await document.fonts.ready;
      } catch {
        // Font loading API unavailable — fall back to whatever is resolved.
      }
      if (cancelled) return;
      const onest = resolveFamily("var(--aqt-display)");
      const mono = resolveFamily("var(--aqt-data)");
      const palette: Palette = {
        bg: token("--aqt-bg"),
        border: token("--aqt-border"),
        fg: token("--aqt-fg"),
        fgMuted: token("--aqt-fg-muted"),
        fgFaint: token("--aqt-fg-faint"),
        teal: token("--aqt-teal"),
        tank: token("--aqt-tank"),
        damage: token("--aqt-damage"),
        support: token("--aqt-support"),
        flex: token("--aqt-flex"),
        emerald: token("--aqt-emerald"),
        rose: token("--aqt-rose"),
        amber: token("--aqt-amber")
      };
      const origin = window.location.origin.replace(/^https?:\/\//, "");
      const profileUrl = `${origin}${window.location.pathname}`;
      drawCard(ctx, card, onest, mono, palette, profileUrl, t);
    };
    void render();
    return () => {
      cancelled = true;
    };
  }, [canvas, card, t]);

  const download = useCallback((blob: Blob) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${card.name.replace(/[^\w.-]+/g, "_")}-owt-card.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, [card.name]);

  const handleCopyImage = useCallback(() => {
    if (!canvas) return;
    canvas.toBlob(async (blob) => {
      if (!blob) return;
      try {
        if (typeof ClipboardItem === "undefined" || !navigator.clipboard?.write) {
          throw new Error("clipboard-image-unsupported");
        }
        await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
        flash("img");
      } catch {
        // Image clipboard unsupported/denied — degrade to a download.
        try {
          download(blob);
          flash("download");
        } catch {
          // Sandboxed / storage denied — nothing more we can do.
        }
      }
    }, "image/png");
  }, [canvas, download, flash]);

  const handleDownload = useCallback(() => {
    if (!canvas) return;
    canvas.toBlob((blob) => {
      if (blob) {
        download(blob);
        flash("download");
      }
    }, "image/png");
  }, [canvas, download, flash]);

  const handleCopyLink = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      flash("link");
    } catch {
      // Clipboard unavailable (insecure context / denied) — ignore.
    }
  }, [flash]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger className={BTN} title={t("users.profile.toolbar.share")}>
        <Share2 size={13} aria-hidden />
        {t("users.profile.toolbar.share")}
      </DialogTrigger>
      <DialogContent className="max-w-[680px] border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)]">
        <DialogHeader>
          <DialogTitle className="font-onest text-[color:var(--aqt-fg)]">
            {t("users.profile.toolbar.card")}
          </DialogTitle>
          <DialogDescription className="text-[color:var(--aqt-fg-muted)]">
            {t("users.profile.toolbar.cardDescription")}
          </DialogDescription>
        </DialogHeader>

        <canvas
          ref={setCanvas}
          width={CARD_W}
          height={CARD_H}
          className="h-auto w-full rounded-lg border border-[color:var(--aqt-border)]"
          role="img"
          aria-label={t("users.profile.toolbar.card")}
        />

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button type="button" onClick={handleCopyImage} className={BTN}>
            {copyState === "img" ? <Check size={13} aria-hidden /> : <Copy size={13} aria-hidden />}
            {copyState === "img" ? t("users.profile.toolbar.imageCopied") : t("users.profile.toolbar.copyImage")}
          </button>
          <button type="button" onClick={handleDownload} className={BTN}>
            {copyState === "download" ? <Check size={13} aria-hidden /> : <Download size={13} aria-hidden />}
            {copyState === "download" ? t("users.profile.toolbar.downloaded") : t("users.profile.toolbar.download")}
          </button>
          <button type="button" onClick={handleCopyLink} className={BTN} title={t("users.profile.toolbar.copyLink")}>
            {copyState === "link" ? <Check size={13} aria-hidden /> : <Link2 size={13} aria-hidden />}
            {copyState === "link" ? t("users.profile.toolbar.copied") : t("users.profile.toolbar.copyLinkShort")}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default SharePlayerCard;
