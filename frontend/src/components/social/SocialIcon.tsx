import Image from "next/image";
import { Link2 } from "lucide-react";

import { getSocialProviderConfig } from "@/lib/social/providers";

interface SocialIconProps {
  provider: string;
  size?: number;
  className?: string;
  /** The provider's name is already spelled out beside the icon: hide it from
   *  assistive tech so the name is not announced twice. */
  decorative?: boolean;
}

/** Brand icon for a social provider, falling back to a generic link glyph. */
export function SocialIcon({ provider, size = 12, className, decorative = false }: Readonly<SocialIconProps>) {
  const config = getSocialProviderConfig(provider);
  const label = decorative ? "" : config.label;
  if (config.icon) {
    return <Image src={config.icon} width={size} height={size} alt={label} className={className} />;
  }
  return (
    <Link2
      width={size}
      height={size}
      className={className}
      style={{ color: config.color }}
      aria-label={label || undefined}
      aria-hidden={decorative || undefined}
    />
  );
}
