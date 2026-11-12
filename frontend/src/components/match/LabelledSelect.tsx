"use client";

import { useId } from "react";

import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";

/** A visible label and a select whose trigger is named by it, so assistive technology hears what it chooses. */
export default function LabelledSelect({
  label,
  value,
  onValueChange,
  options,
  className = "w-[170px]"
}: Readonly<{
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  options: readonly { value: string; label: string }[];
  className?: string;
}>) {
  const labelId = useId();
  return (
    <div className="flex items-center gap-2">
      <Eyebrow id={labelId} className="aqt-tnum">
        {label}
      </Eyebrow>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger aria-labelledby={labelId} size="sm" className={className}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
