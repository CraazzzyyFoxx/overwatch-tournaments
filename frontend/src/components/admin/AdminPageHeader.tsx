interface AdminPageHeaderProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  meta?: React.ReactNode;
}

export function AdminPageHeader({
  title,
  description,
  actions,
  meta,
}: AdminPageHeaderProps) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold tracking-tight text-foreground truncate">{title}</h1>
          {meta}
        </div>
        {description && (
          <p className="mt-0.5 text-[13px] text-muted-foreground/60 truncate">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  );
}
