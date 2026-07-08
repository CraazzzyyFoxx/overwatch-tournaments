import { useTranslations } from "next-intl";

import { PaginationWithLinks } from "@/components/ui/pagination-with-links";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PaginatedResponse } from "@/types/pagination.types";
import { UserOverviewRow } from "@/types/user.types";

import UsersOverviewTableRow from "./UsersOverviewTableRow";
import UsersOverviewTableSkeleton from "./UsersOverviewTableSkeleton";

type UsersOverviewTableProps = {
  data?: PaginatedResponse<UserOverviewRow>;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  error: unknown;
  maxPage: number;
  expandedRows: Set<number>;
  onToggleRow: (id: number) => void;
};

const UsersOverviewTable = ({
  data,
  isLoading,
  isError,
  isFetching,
  error,
  maxPage,
  expandedRows,
  onToggleRow
}: UsersOverviewTableProps) => {
  const t = useTranslations();

  if (isLoading && !data) {
    return <UsersOverviewTableSkeleton />;
  }

  if (isError) {
    return (
      <p className="text-sm text-destructive">{(error as Error)?.message || t("users.list.errors.overview")}</p>
    );
  }

  if (!data || data.results.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("users.list.empty")}</p>;
  }

  return (
    <>
      <div className="relative">
        {isFetching ? (
          <div className="mb-3 flex items-center gap-2">
            <Skeleton className="h-2 w-20" />
            <Skeleton className="h-2 flex-1" />
          </div>
        ) : null}

        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-[22%] text-left">{t("users.list.table.user")}</TableHead>
              <TableHead className="w-[28%] text-center">{t("users.list.table.divisions")}</TableHead>
              <TableHead className="text-center">{t("common.tournaments")}</TableHead>
              <TableHead className="text-center">{t("users.list.table.achievements")}</TableHead>
              <TableHead className="text-center">{t("users.list.table.avgPlacement")}</TableHead>
              <TableHead className="text-center">{t("users.list.table.topHeroes")}</TableHead>
              <TableHead className="text-center">{t("users.list.table.details")}</TableHead>
            </TableRow>
          </TableHeader>

          <TableBody>
            {data.results.map((user) => (
              <UsersOverviewTableRow
                key={user.id}
                user={user}
                isExpanded={expandedRows.has(user.id)}
                onToggleRow={onToggleRow}
              />
            ))}
          </TableBody>
        </Table>

        <div className="mt-4 flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            {t("users.list.table.pageCount", { page: String(data.page), maxPage: String(maxPage), total: data.total })}
          </p>
          <PaginationWithLinks
            page={data.page}
            pageSize={data.per_page}
            totalCount={data.total}
            pageSearchParam="page"
            pageSizeSelectOptions={{
              pageSizeSearchParam: "per_page",
              pageSizeOptions: [10, 20, 30, 50]
            }}
          />
        </div>
      </div>
    </>
  );
};

export default UsersOverviewTable;
