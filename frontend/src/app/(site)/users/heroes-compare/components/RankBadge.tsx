interface RankBadgeProps {
  rank: number;
}

const BASE = "w-full text-center tabular-nums";

const RankBadge = ({ rank }: RankBadgeProps) => {
  if (rank === 1)
    return (
      <span className={`${BASE} font-[family-name:var(--aqt-display)] text-[15px] font-extrabold text-[var(--aqt-gold)]`}>
        1
      </span>
    );
  if (rank === 2)
    return (
      <span className={`${BASE} font-[family-name:var(--aqt-mono)] text-[11px] font-bold text-[hsl(210_14%_78%)]`}>
        2
      </span>
    );
  if (rank === 3)
    return (
      <span className={`${BASE} font-[family-name:var(--aqt-mono)] text-[11px] font-bold text-[hsl(28_60%_56%)]`}>
        3
      </span>
    );
  return (
    <span className={`${BASE} font-[family-name:var(--aqt-mono)] text-[11px] font-semibold text-[var(--aqt-fg-faint)]`}>
      {rank}
    </span>
  );
};

export default RankBadge;
