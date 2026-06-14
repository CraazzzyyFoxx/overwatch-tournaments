declare module "bun:test" {
  export const describe: any;
  export const expect: any;
  export const it: any;
}

interface ImportMeta {
  dir: string;
}
