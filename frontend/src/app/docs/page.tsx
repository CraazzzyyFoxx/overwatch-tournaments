import { DocsExplorer } from "./DocsExplorer";

// Client-side rendering only: mermaid is heavy and browser-only, so the whole
// explorer is a client component that imports it dynamically. This server page
// is just the entry point.
export default function DocsPage() {
  return <DocsExplorer />;
}
