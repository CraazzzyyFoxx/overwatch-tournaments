import React from "react";
import Image from "next/image";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { UserRoleType } from "@/types/user.types";

import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { getDivisionIconSrc } from "@/lib/division-grid";
import {
  getDivisionOptions,
  ROLE_LABEL_KEY,
  ROLE_OPTIONS,
  SORT_OPTIONS,
  UsersOverviewOrderValue,
  UsersOverviewSortValue
} from "./utils";

type UsersOverviewFiltersProps = {
  searchInput: string;
  role?: UserRoleType;
  divMinInput: string;
  divMaxInput: string;
  sort: UsersOverviewSortValue;
  order: UsersOverviewOrderValue;
  onSearchChange: (value: string) => void;
  onRoleChange: (value: "all" | UserRoleType) => void;
  onDivMinChange: (value: string) => void;
  onDivMaxChange: (value: string) => void;
  onSortChange: (value: UsersOverviewSortValue) => void;
  onOrderChange: (value: UsersOverviewOrderValue) => void;
  onReset: () => void;
};

const UsersOverviewFilters = ({
  searchInput,
  role,
  divMinInput,
  divMaxInput,
  sort,
  order,
  onSearchChange,
  onRoleChange,
  onDivMinChange,
  onDivMaxChange,
  onSortChange,
  onOrderChange,
  onReset
}: UsersOverviewFiltersProps) => {
  const grid = useDivisionGrid();
  const t = useTranslations();
  const divisionOptions = getDivisionOptions(grid);

  const resolveIconUrl = (divisionNumber: number) => {
    return getDivisionIconSrc(grid, divisionNumber) ?? "";
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <h1 className="text-2xl font-semibold">{t("users.list.filters.heading")}</h1>
        <p className="text-sm text-muted-foreground">{t("users.list.filters.subheading")}</p>
      </CardHeader>

      <CardContent>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
          <Input
            value={searchInput}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={t("users.list.filters.searchByName")}
            className="xl:col-span-2"
          />

          <Select value={role ?? "all"} onValueChange={(value) => onRoleChange(value as "all" | UserRoleType)}>
            <SelectTrigger className="liquid-glass-panel">
              <div className="flex items-center gap-2">
                {role ? (
                  <Image
                    src={`/roles/${role}.png`}
                    alt={t("users.list.a11y.roleIcon", { role: t(ROLE_LABEL_KEY[role]) })}
                    width={22}
                    height={22}
                    className="h-[22px] w-[22px]"
                  />
                ) : null}
                <span className="truncate">{role ? t(ROLE_LABEL_KEY[role]) : t("users.list.filters.allRoles")}</span>
              </div>
            </SelectTrigger>
            <SelectContent className="liquid-glass-panel">
              {ROLE_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  <div className="flex items-center gap-2">
                    {option.value === "all" ? null : (
                      <Image
                        src={`/roles/${option.value}.png`}
                        alt={t("users.list.a11y.roleIcon", { role: t(option.labelKey) })}
                        width={20}
                        height={20}
                        className="h-5 w-5"
                      />
                    )}
                    <span>{t(option.labelKey)}</span>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={divMinInput || "all"} onValueChange={onDivMinChange}>
            <SelectTrigger className="liquid-glass-panel">
              <div className="flex items-center gap-2">
                {divMinInput ? (
                  <Image
                    src={resolveIconUrl(Number(divMinInput))}
                    alt={t("common.divisionWithId", { id: divMinInput })}
                    width={22}
                    height={22}
                    className="h-[22px] w-[22px]"
                  />
                ) : null}
                <span className="truncate">
                  {divMinInput ? t("common.divisionWithId", { id: divMinInput }) : t("users.list.filters.allDivisions")}
                </span>
              </div>
            </SelectTrigger>
            <SelectContent className="liquid-glass-panel">
              <SelectItem value="all">{t("users.list.filters.allDivisions")}</SelectItem>
              {divisionOptions.map((division) => (
                <SelectItem key={`min-${division}`} value={String(division)}>
                  <div className="flex items-center gap-2">
                    <Image
                      src={resolveIconUrl(division)}
                      alt={t("common.divisionWithId", { id: String(division) })}
                      width={20}
                      height={20}
                      className="h-5 w-5"
                    />
                    <span>{t("common.divisionWithId", { id: String(division) })}</span>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={divMaxInput || "all"} onValueChange={onDivMaxChange}>
            <SelectTrigger className="liquid-glass-panel">
              <div className="flex items-center gap-2">
                {divMaxInput ? (
                  <Image
                    src={resolveIconUrl(Number(divMaxInput))}
                    alt={t("common.divisionWithId", { id: divMaxInput })}
                    width={22}
                    height={22}
                    className="h-[22px] w-[22px]"
                  />
                ) : null}
                <span className="truncate">
                  {divMaxInput ? t("common.divisionWithId", { id: divMaxInput }) : t("users.list.filters.allDivisions")}
                </span>
              </div>
            </SelectTrigger>
            <SelectContent className="liquid-glass-panel">
              <SelectItem value="all">{t("users.list.filters.allDivisions")}</SelectItem>
              {divisionOptions.map((division) => (
                <SelectItem key={`max-${division}`} value={String(division)}>
                  <div className="flex items-center gap-2">
                    <Image
                      src={resolveIconUrl(division)}
                      alt={t("common.divisionWithId", { id: String(division) })}
                      width={20}
                      height={20}
                      className="h-5 w-5"
                    />
                    <span>{t("common.divisionWithId", { id: String(division) })}</span>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div className="flex items-center gap-2">
            <Button type="button" className="flex-1 bg-emerald-600 text-white hover:bg-emerald-500" onClick={onReset}>
              {t("users.list.filters.reset")}
            </Button>
          </div>

          <Select value={sort} onValueChange={(value) => onSortChange(value as UsersOverviewSortValue)}>
            <SelectTrigger className="liquid-glass-panel">
              <SelectValue placeholder={t("common.sortBy")} />
            </SelectTrigger>
            <SelectContent className="liquid-glass-panel">
              {SORT_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {t(option.labelKey)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={order} onValueChange={(value) => onOrderChange(value as UsersOverviewOrderValue)}>
            <SelectTrigger className="liquid-glass-panel">
              <SelectValue placeholder={t("common.order")} />
            </SelectTrigger>
            <SelectContent className="liquid-glass-panel">
              <SelectItem value="asc">{t("common.ascending")}</SelectItem>
              <SelectItem value="desc">{t("common.descending")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </CardContent>
    </Card>
  );
};

export default React.memo(UsersOverviewFilters);
