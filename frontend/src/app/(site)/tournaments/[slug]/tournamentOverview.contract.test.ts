import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";
import ts from "typescript";

const routeDir = import.meta.dirname;

function sourceFor(relativePath: string): string {
  const path = join(routeDir, relativePath);
  return existsSync(path) ? readFileSync(path, "utf8") : "";
}

function parsedSource(relativePath: string): ts.SourceFile {
  return ts.createSourceFile(
    relativePath,
    sourceFor(relativePath),
    ts.ScriptTarget.Latest,
    true,
    relativePath.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  );
}

function importedNames(sourceFile: ts.SourceFile, moduleName: string): Set<string> {
  const names = new Set<string>();

  for (const statement of sourceFile.statements) {
    if (
      !ts.isImportDeclaration(statement) ||
      !ts.isStringLiteral(statement.moduleSpecifier) ||
      statement.moduleSpecifier.text !== moduleName
    ) {
      continue;
    }

    const clause = statement.importClause;
    if (clause?.name) names.add(clause.name.text);
    if (clause?.namedBindings && ts.isNamedImports(clause.namedBindings)) {
      for (const element of clause.namedBindings.elements) names.add(element.name.text);
    }
  }

  return names;
}

function nodesMatching<T extends ts.Node>(
  sourceFile: ts.SourceFile,
  predicate: (node: ts.Node) => node is T
): T[] {
  const matches: T[] = [];
  const visit = (node: ts.Node) => {
    if (predicate(node)) matches.push(node);
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return matches;
}

function calledMethods(sourceFile: ts.SourceFile): string[] {
  return nodesMatching(sourceFile, ts.isCallExpression)
    .map((call) => call.expression)
    .filter(ts.isPropertyAccessExpression)
    .map((access) => access.name.text);
}

function calledIdentifiers(sourceFile: ts.SourceFile): string[] {
  return nodesMatching(sourceFile, ts.isCallExpression)
    .map((call) => call.expression)
    .filter(ts.isIdentifier)
    .map((identifier) => identifier.text);
}

function jsxElements(sourceFile: ts.SourceFile, componentName: string): ts.JsxOpeningLikeElement[] {
  return nodesMatching(
    sourceFile,
    (node): node is ts.JsxOpeningLikeElement =>
      (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) &&
      node.tagName.getText(sourceFile) === componentName
  );
}

function hasJsxAttribute(
  sourceFile: ts.SourceFile,
  element: ts.JsxOpeningLikeElement,
  attributeName: string,
  expressionText?: string
): boolean {
  return element.attributes.properties.some((attribute) => {
    if (!ts.isJsxAttribute(attribute) || attribute.name.getText(sourceFile) !== attributeName) {
      return false;
    }
    if (!expressionText) return true;
    return (
      attribute.initializer !== undefined &&
      ts.isJsxExpression(attribute.initializer) &&
      attribute.initializer.expression?.getText(sourceFile) === expressionText
    );
  });
}

function isInsideFunction(node: ts.Node): boolean {
  for (let current = node.parent; current; current = current.parent) {
    if (ts.isFunctionLike(current)) return true;
  }
  return false;
}

describe("tournament overview server contract", () => {
  it("uses one request-scoped public overview loader without cross-request caching", () => {
    const sourceFile = parsedSource("_data.ts");
    const source = sourceFor("_data.ts");

    expect(importedNames(sourceFile, "react")).toContain("cache");
    expect(source).toMatch(/export const getTournamentOverviewState\s*=\s*cache\s*\(/);
    expect(calledMethods(sourceFile)).toContain("getPublicOverview");
    expect(source).not.toContain("unstable_cache");
    expect(source).not.toContain("getStages");
  });

  it("wraps only the overview hydration boundary in Suspense, decoupled from the client shell", () => {
    const sourceFile = parsedSource("layout.tsx");
    const source = sourceFor("layout.tsx");
    const suspense = jsxElements(sourceFile, "Suspense");
    const overviewBoundaryEl = jsxElements(sourceFile, "TournamentOverviewBoundary");
    const layoutFunction = nodesMatching(sourceFile, ts.isFunctionDeclaration).find(
      (declaration) => declaration.name?.text === "TournamentLayout"
    );

    expect(importedNames(sourceFile, "react")).toContain("Suspense");
    // No client-side format validation is meaningful for a slug (any
    // non-empty string is a legitimate ref) -- the raw URL segment goes
    // straight to TournamentOverviewBoundary, which 404s upstream misses.
    expect(source).toContain("slug={resolvedParams.slug}");
    expect(layoutFunction?.getText(sourceFile)).not.toContain("getTournamentOverviewState");
    expect(overviewBoundaryEl).toHaveLength(1);
    expect(suspense).toHaveLength(1);
    expect(hasJsxAttribute(sourceFile, suspense[0], "fallback", "null")).toBe(true);
    // Self-closing: takes no children, so a re-suspended overview fetch (this
    // segment is force-dynamic) can never unmount TournamentClientLayout —
    // it's a sibling, not a descendant, of this Suspense boundary.
    expect(ts.isJsxSelfClosingElement(overviewBoundaryEl[0])).toBe(true);
  });

  it("resolves the same raw slug ref across layout, metadata, and index route", () => {
    const dataSource = sourceFor("_data.ts");
    const data = parsedSource("_data.ts");
    const layout = parsedSource("layout.tsx");
    const layoutSource = sourceFor("layout.tsx");
    const page = parsedSource("page.tsx");
    const pageSource = sourceFor("page.tsx");
    const prefetch = parsedSource("_prefetch.tsx");
    const prefetchSource = sourceFor("_prefetch.tsx");

    expect(dataSource).not.toMatch(/^[\s\S]*["']use client["']/);
    // getTournamentOverviewState takes the ref as-is -- no parseCanonicalTournamentId
    // or any other numeric coercion survives the slug migration.
    expect(dataSource).not.toContain("parseCanonicalTournamentId");
    expect(layoutSource).not.toContain("parseCanonicalTournamentId");
    expect(pageSource).not.toContain("parseCanonicalTournamentId");
    expect(importedNames(layout, "./_data")).toContain("getTournamentOverviewState");
    expect(importedNames(prefetch, "./_data")).toContain("getTournamentOverviewState");
    expect(layoutSource).toContain("params.slug");
    // The layout keeps a `resolvedParams` object because it hands the segment to
    // two children; the index destructures. What matters either way is that the
    // awaited segment reaches the loader with nothing in between, so pin that
    // rather than the name a local happens to carry.
    expect(pageSource).toMatch(/const\s*\{\s*slug\s*\}\s*=\s*await\s+params/);
    expect(prefetchSource).toMatch(/getTournamentOverviewState\(\s*slug\s*\)/);
    // The state object itself never calls notFound -- only the callers
    // (page.tsx, TournamentOverviewBoundary) act on its "not-found" kind.
    expect(calledIdentifiers(data)).not.toContain("notFound");
  });

  it("hydrates with a request-local query client and lets the client shell own errors", () => {
    const sourceFile = parsedSource("TournamentOverviewBoundary.tsx");
    const source = sourceFor("TournamentOverviewBoundary.tsx");
    const queryClients = nodesMatching(sourceFile, ts.isNewExpression).filter(
      (expression) => expression.expression.getText(sourceFile) === "QueryClient"
    );
    const seedCall = nodesMatching(sourceFile, ts.isCallExpression).find(
      (call) => call.expression.getText(sourceFile) === "queryClient.setQueryData"
    );
    const boundaryFunction = nodesMatching(sourceFile, ts.isFunctionDeclaration).find(
      (declaration) => declaration.name?.text === "TournamentOverviewBoundary"
    );

    expect(importedNames(sourceFile, "@/lib/tournament/overview-query")).toContain(
      "tournamentOverviewQueryOptions"
    );
    expect(calledIdentifiers(sourceFile)).toContain("getTournamentOverviewState");
    expect(calledIdentifiers(sourceFile)).toContain("notFound");
    expect(source).toContain("streamed soft-404");
    // No children prop: it never wraps TournamentClientLayout, and the error
    // branch defers to the client shell's own query state instead of
    // rendering a shell-replacing error element itself.
    expect(boundaryFunction?.parameters[0]?.getText(sourceFile)).not.toContain("children");
    expect(source).not.toContain("TournamentShellError");
    expect(queryClients).toHaveLength(1);
    expect(isInsideFunction(queryClients[0])).toBe(true);
    expect(calledMethods(sourceFile)).toContain("setQueryData");
    expect(seedCall?.arguments.map((argument) => argument.getText(sourceFile))).toEqual([
      "overviewOptions.queryKey",
      "overviewState.overview"
    ]);
    expect(calledIdentifiers(sourceFile)).toContain("dehydrate");
    expect(jsxElements(sourceFile, "HydrationBoundary")).toHaveLength(1);
    expect(source).not.toContain("prefetchQuery");
  });

  it("shows the shared error card from the client shell when the overview query errors", () => {
    const sourceFile = parsedSource("_components/TournamentClientLayout.tsx");
    const source = sourceFor("_components/TournamentClientLayout.tsx");

    expect(importedNames(sourceFile, "../TournamentShellError")).toContain("TournamentShellError");
    expect(jsxElements(sourceFile, "TournamentShellError")).toHaveLength(1);
    expect(source).toContain("tournamentQuery.isError");
  });

  it("keeps the client shell on the hydrated overview without legacy requests", () => {
    const sourceFile = parsedSource("_components/TournamentClientLayout.tsx");
    const source = sourceFor("_components/TournamentClientLayout.tsx");

    expect(calledIdentifiers(sourceFile)).toContain("useTournamentQuery");
    expect(calledIdentifiers(sourceFile)).not.toContain("useTournamentStagesQuery");
    expect(calledIdentifiers(sourceFile)).not.toContain("useQuery");
    expect(calledMethods(sourceFile)).not.toContain("getStages");
    expect(calledMethods(sourceFile)).not.toContain("getCount");
    expect(source).not.toContain("teamService");
    expect(source).toContain("tournament.teams_count");
    expect(source).toContain("tournament.stages");
  });

  it("makes the header the tournament's identity and state, not its reference sheet", () => {
    const sourceFile = parsedSource("_components/TournamentClientLayout.tsx");
    const source = sourceFor("_components/TournamentClientLayout.tsx");
    const hero = jsxElements(sourceFile, "PageHero");

    expect(hero).toHaveLength(1);
    // The organizer's banner and mark, which until now only the list card
    // rendered while the admin's Branding panel promised the public page.
    expect(hasJsxAttribute(sourceFile, hero[0]!, "coverUrl", "tournament.cover_image_url")).toBe(
      true
    );
    expect(hasJsxAttribute(sourceFile, hero[0]!, "coverFade")).toBe(true);
    expect(source).toContain("tournament.logo_url");
    // Cover fades in from the right. Without a cover the metrics take that column.
    expect(hasJsxAttribute(sourceFile, hero[0]!, "aside")).toBe(true);
    expect(hasJsxAttribute(sourceFile, hero[0]!, "stamp")).toBe(true);
    expect(source).not.toContain("asideFlush");
    expect(source).toContain("{registerButton}");
    expect(hasJsxAttribute(sourceFile, hero[0]!, "actions")).toBe(false);
    expect(hasJsxAttribute(sourceFile, hero[0]!, "lede")).toBe(false);
    expect(source).not.toContain('t("common.format")');
    expect(source).not.toContain('t("common.teamFormation")');
    // ...but the draft room is an action, so it stays in the action row.
    expect(source).toContain("/draft/${tournament.slug}");
  });

  it("serves metadata and the index screen from the one overview read, with no hop", () => {
    const layout = parsedSource("layout.tsx");
    const page = parsedSource("page.tsx");
    const pageSource = sourceFor("page.tsx");
    const prefetch = parsedSource("_prefetch.tsx");

    expect(calledIdentifiers(layout)).toContain("getTournamentOverviewState");
    expect(calledIdentifiers(prefetch)).toContain("getTournamentOverviewState");
    // `getTournamentOverviewState` is react-`cache`d (asserted above), so both
    // callers in the same request share one read rather than paying for two.
    expect(pageSource).not.toContain("getTournamentStages");
    expect(calledMethods(page)).not.toContain("getStages");
    // The bare URL IS the overview screen. The index used to count stages to
    // decide where to send the visitor, and every such hop is a place
    // navigation can land on the wrong screen — so the redirect is gone and
    // the route renders the view in place.
    expect(calledIdentifiers(page)).not.toContain("redirect");
    expect(jsxElements(page, "TournamentOverviewPage")).toHaveLength(1);
  });

  it("shares the structural shell skeleton with route loading", () => {
    const loading = parsedSource("loading.tsx");
    const skeleton = parsedSource("_components/TournamentSkeletons.tsx");
    const skeletonSource = sourceFor("_components/TournamentSkeletons.tsx");

    expect(importedNames(loading, "./_components/TournamentSkeletons")).toContain(
      "TournamentShellSkeleton"
    );
    expect(jsxElements(loading, "TournamentShellSkeleton")).toHaveLength(1);
    expect(jsxElements(skeleton, "PageHero")).toHaveLength(1);
    expect(skeletonSource).toContain('role="status"');
    expect(skeletonSource).toContain('aria-live="polite"');
    expect(skeletonSource).toContain('t("common.loading")');
    expect(skeletonSource.match(/role="status"/g)).toHaveLength(1);
    expect(skeletonSource).toMatch(/aria-hidden="true"[\s\S]*?<PageHero/);
    expect(skeletonSource).toContain("tabs");
    expect(skeletonSource).toContain("min-w-0");
  });

  it("offers a client retry through router.refresh without non-serializable props", () => {
    const sourceFile = parsedSource("TournamentShellError.tsx");
    const source = sourceFor("TournamentShellError.tsx");
    const component = nodesMatching(sourceFile, ts.isFunctionDeclaration).find(
      (declaration) => declaration.name?.text === "TournamentShellError"
    );

    expect(source).toMatch(/^\s*["']use client["']/);
    expect(calledIdentifiers(sourceFile)).toContain("useRouter");
    expect(calledMethods(sourceFile)).toContain("refresh");
    // The retry label is the shared card's default rather than a fourth
    // hand-rolled error design in this file.
    expect(source).toContain('from "@/components/ui/page-state-card"');
    expect(source).toContain("onAction={() => router.refresh()}");
    expect(sourceFor("../../../../components/ui/page-state-card.tsx")).toContain(
      't("common.retry")'
    );
    expect(component?.parameters).toHaveLength(0);
  });
});
