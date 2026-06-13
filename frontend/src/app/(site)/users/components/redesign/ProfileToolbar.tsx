"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Share2, GitCompare, Check } from "lucide-react";

interface ProfileToolbarProps {
  /** Destination for the Compare action. Defaults to the players compare page. */
  comparePath?: string;
}

const BTN =
  "inline-flex items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.03)] px-2.5 py-1.5 text-[11.5px] font-semibold text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-fg)]";

/**
 * Header toolbar for the player profile. Share copies the current URL; Compare
 * links to the existing players-compare page. (Export CSV and Follow are planned
 * for a later phase — Export needs a per-tab data export, Follow needs backend.)
 */
const ProfileToolbar = ({ comparePath = "/users/compare" }: ProfileToolbarProps) => {
  const [copied, setCopied] = useState(false);

  const handleShare = async () => {
    if (typeof window === "undefined") return;
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard unavailable (insecure context / denied) — silently ignore.
    }
  };

  return (
    <div className="flex items-center gap-2">
      <button type="button" onClick={handleShare} className={BTN} title="Copy link to this profile">
        {copied ? <Check size={13} /> : <Share2 size={13} />}
        {copied ? "Copied" : "Share"}
      </button>
      <Link href={comparePath} className={BTN} title="Compare players">
        <GitCompare size={13} />
        Compare
      </Link>
    </div>
  );
};

export default ProfileToolbar;
