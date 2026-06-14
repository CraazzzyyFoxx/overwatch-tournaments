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
  if (isLoading && !data) {
    return <UsersOverviewTableSkeleton />;
  }

  if (isError) {
    return <p className="text-sm text-destructive">{(error as Error)?.message || "Failed to load users overview."}</p>;
  }

  if (!data || data.results.length === 0) {
    return <p className="text-sm text-muted-foreground">No users found for current filters.</p>;
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
              <TableHead className="w-[22%] text-left">User</TableHead>
              <TableHead className="w-[28%] text-center">Divisions</TableHead>
              <TableHead className="text-center">Tournaments</TableHead>
              <TableHead className="text-center">Achievements</TableHead>
              <TableHead className="text-center">Avg placement</TableHead>
              <TableHead className="text-center">Top heroes</TableHead>
              <TableHead className="text-center">Details</TableHead>
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
            Page {data.page} of {maxPage} ({data.total} users)
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
