import React from "react";
import TankIcon from "@/components/icons/TankIcon";
import DamageIcon from "@/components/icons/DamageIcon";
import SupportIcon from "@/components/icons/SupportIcon";

const PlayerRoleIcon = ({
  role,
  size = 24,
  color,
}: {
  role: string | null;
  size?: number;
  color?: string;
}) => {
  return (
    <div>
      {role === "Tank" && <TankIcon height={size} width={size} color={color} />}
      {role === "Damage" && <DamageIcon height={size} width={size} color={color} />}
      {role === "Support" && <SupportIcon height={size} width={size} color={color} />}
    </div>
  );
};

export default PlayerRoleIcon;
