import React, { useMemo } from "react";
import Image from "next/image";
import Link from "next/link";
import { ChevronDown, ChevronUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import { TableCell, TableRow } from "@/components/ui/table";
import { UserOverviewRow } from "@/types/user.types";

import DivisionBadges from "./DivisionBadges";
import ExpandedUserRow from "./ExpandedUserRow";
import { formatOptional, toUserSlug } from "./utils";

type UsersOverviewTableRowProps = {
  user: UserOverviewRow;
  isExpanded: boolean;
  onToggleRow: (id: number) => void;
};

const UsersOverviewTableRow = ({ user, isExpanded, onToggleRow }: UsersOverviewTableRowProps) => {
  const topHeroesPreview = useMemo(() => user.top_heroes.slice(0, 3), [user.top_heroes]);

  return (
    <>
      <TableRow className="hover:bg-transparent">
        <TableCell className="text-left">
          <Link href={`/users/${toUserSlug(user.name)}`} className="font-medium hover:underline">
            {user.name}
          </Link>
        </TableCell>

        <TableCell className="text-center">
          <DivisionBadges user={user} />
        </TableCell>

        <TableCell className="text-center font-medium">{user.tournaments_count}</TableCell>
        <TableCell className="text-center font-medium">{user.achievements_count}</TableCell>
        <TableCell className="text-center">{formatOptional(user.averages.avg_placement)}</TableCell>

        <TableCell className="text-center">
          {topHeroesPreview.length > 0 ? (
            <div className="flex justify-center gap-1">
              {topHeroesPreview.map((heroRow) => (
                <Image
                  key={`${user.id}-preview-${heroRow.hero.id}`}
                  src={heroRow.hero.image_path}
                  alt={heroRow.hero.name}
                  width={38}
                  height={38}
                  title={heroRow.hero.name}
                  className="h-9 w-9 rounded-full border border-border/70 object-cover shadow-sm"
                />
              ))}
            </div>
          ) : (
            <span className="text-sm text-muted-foreground">-</span>
          )}
        </TableCell>

        <TableCell className="text-center">
          <Button
            variant="ghost"
            size="icon"
            aria-label={isExpanded ? "Collapse user details" : "Expand user details"}
            onClick={() => onToggleRow(user.id)}
            className="mx-auto rounded-full border border-border/60 bg-background/50 hover:bg-muted/40"
          >
            {isExpanded ? <ChevronUp className="h-4 w-4 text-emerald-400" /> : <ChevronDown className="h-4 w-4 text-emerald-400" />}
          </Button>
        </TableCell>
      </TableRow>

      {isExpanded ? (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={7} className="p-3">
            <ExpandedUserRow user={user} />
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
};

export default React.memo(UsersOverviewTableRow);
