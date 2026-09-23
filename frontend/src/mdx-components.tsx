import type { MDXComponents } from "mdx/types";

// Required by @next/mdx. The docs route passes its own components per render,
// so there is nothing global to provide.
export function useMDXComponents(components: MDXComponents): MDXComponents {
  return components;
}
