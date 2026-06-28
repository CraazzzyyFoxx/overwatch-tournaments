import Image from "next/image";
import { Link2 } from "lucide-react";

import { getSocialProviderConfig } from "@/lib/social-providers";

interface SocialIconProps {
  provider: string;
  size?: number;
  className?: string;
}

/** Brand icon for a social provider, falling back to a generic link glyph. */
export function SocialIcon({ provider, size = 12, className }: SocialIconProps) {
  const config = getSocialProviderConfig(provider);
  if (config.icon) {
    return <Image src={config.icon} width={size} height={size} alt={config.label} className={className} />;
  }
  return <Link2 width={size} height={size} className={className} style={{ color: config.color }} aria-label={config.label} />;
}
