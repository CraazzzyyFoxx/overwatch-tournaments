interface RankBadgeProps {
  rank: number;
}

const RankBadge = ({ rank }: RankBadgeProps) => {
  if (rank === 1)
    return (
      <span className="w-6 shrink-0 text-center text-xs font-bold tabular-nums text-amber-400">
        1
      </span>
    );
  if (rank === 2)
    return (
      <span className="w-6 shrink-0 text-center text-xs font-semibold tabular-nums text-slate-300">
        2
      </span>
    );
  if (rank === 3)
    return (
      <span className="w-6 shrink-0 text-center text-xs font-semibold tabular-nums text-amber-700/90">
        3
      </span>
    );
  return (
    <span className="w-6 shrink-0 text-center text-xs tabular-nums text-muted-foreground/50">
      {rank}
    </span>
  );
};

export default RankBadge;
