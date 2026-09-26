"use client";

import { useId } from "react";

import { conditionLabel, formatParamsSummary, type FlatNode } from "./condition-flow.model";

/**
 * Screen-reader outline of the tree.
 *
 * The canvas nesting exists only visually — React Flow lays every node out as
 * an absolutely positioned sibling and draws the parent/child relationship as
 * an SVG edge, which assistive tech cannot follow. This mirrors the same data
 * as a real nested list so the shape of the boolean expression is readable.
 * It is deliberately read-only: the editable controls stay on the canvas and
 * each one is named with its path so the two views line up.
 */
export function ConditionTreeOutline({
  nodes,
  paths,
}: Readonly<{
  nodes: FlatNode[];
  paths: Record<string, string>;
}>) {
  const headingId = useId();

  const renderLevel = (parentId: string | undefined) => {
    const children = nodes.filter((node) => node.parentId === parentId);
    if (children.length === 0) {
      return null;
    }
    return (
      <ul>
        {children.map((node) => {
          const path = paths[node.id] ?? "?";
          let description: string;
          if (node.type === "logical") {
            description = `${path} ${node.logicalOp ?? "AND"} group`;
          } else {
            const label = conditionLabel(node.conditionType);
            const summary = formatParamsSummary(node.conditionType ?? "", node.params ?? {});
            description = summary ? `${path} ${label} · ${summary}` : `${path} ${label}`;
          }
          return (
            <li key={node.id}>
              {description}
              {renderLevel(node.id)}
            </li>
          );
        })}
      </ul>
    );
  };

  return (
    <div className="sr-only">
      <p id={headingId}>Condition tree outline</p>
      <div role="group" aria-labelledby={headingId}>
        {renderLevel(undefined)}
      </div>
    </div>
  );
}
