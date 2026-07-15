import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "bun:test";
import ts from "typescript";

const routeDir = import.meta.dir;

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

  it("wraps the server boundary in Suspense with the shared exact shell fallback", () => {
    const sourceFile = parsedSource("layout.tsx");
    const source = sourceFor("layout.tsx");
    const suspense = jsxElements(sourceFile, "Suspense");
    const stateCall = nodesMatching(sourceFile, ts.isCallExpression).find(
      (call) => call.expression.getText(sourceFile) === "getTournamentOverviewState"
    );

    expect(importedNames(sourceFile, "react")).toContain("Suspense");
    expect(stateCall).toBeDefined();
    expect(stateCall?.getStart(sourceFile) ?? Number.POSITIVE_INFINITY).toBeLessThan(
      suspense[0].getStart(sourceFile)
    );
    expect(source).toMatch(
      /if\s*\(overviewState\.kind\s*===\s*["']not-found["']\)[\s\S]*?notFound\(\)/
    );
    expect(source).toMatch(
      /if\s*\(overviewState\.kind\s*===\s*["']error["']\)[\s\S]*?<TournamentShellError\s*\/>/
    );
    expect(jsxElements(sourceFile, "TournamentOverviewBoundary")).toHaveLength(1);
    expect(suspense).toHaveLength(1);
    expect(
      hasJsxAttribute(sourceFile, suspense[0], "fallback", "<TournamentShellSkeleton />")
    ).toBe(true);
  });

  it("hydrates the resolved overview with a request-local query client", () => {
    const sourceFile = parsedSource("TournamentOverviewBoundary.tsx");
    const source = sourceFor("TournamentOverviewBoundary.tsx");
    const queryClients = nodesMatching(sourceFile, ts.isNewExpression).filter(
      (expression) => expression.expression.getText(sourceFile) === "QueryClient"
    );
    const seedCall = nodesMatching(sourceFile, ts.isCallExpression).find(
      (call) => call.expression.getText(sourceFile) === "queryClient.setQueryData"
    );

    expect(importedNames(sourceFile, "./_queries/tournamentOverview")).toContain(
      "tournamentOverviewQueryOptions"
    );
    expect(calledIdentifiers(sourceFile)).not.toContain("getTournamentOverview");
    expect(calledIdentifiers(sourceFile)).not.toContain("isNotFoundError");
    expect(calledIdentifiers(sourceFile)).not.toContain("notFound");
    expect(queryClients).toHaveLength(1);
    expect(isInsideFunction(queryClients[0])).toBe(true);
    expect(source).toMatch(/overview:\s*Tournament/);
    expect(calledMethods(sourceFile)).toContain("setQueryData");
    expect(seedCall?.arguments.map((argument) => argument.getText(sourceFile))).toEqual([
      "overviewOptions.queryKey",
      "overview"
    ]);
    expect(calledIdentifiers(sourceFile)).toContain("dehydrate");
    expect(jsxElements(sourceFile, "HydrationBoundary")).toHaveLength(1);
    expect(jsxElements(sourceFile, "TournamentShellError")).toHaveLength(0);
    expect(source).not.toContain("prefetchQuery");
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

  it("reuses overview summaries for metadata and the index redirect", () => {
    const layout = parsedSource("layout.tsx");
    const page = parsedSource("page.tsx");
    const pageSource = sourceFor("page.tsx");

    expect(calledIdentifiers(layout)).toContain("getTournamentOverviewState");
    expect(calledIdentifiers(page)).toContain("getTournamentOverviewState");
    expect(pageSource).toContain("overviewState.overview.stages.length");
    expect(pageSource).not.toContain("getTournamentStages");
    expect(calledMethods(page)).not.toContain("getStages");
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
    expect(source).toContain('t("common.retry")');
    expect(component?.parameters).toHaveLength(0);
  });
});
