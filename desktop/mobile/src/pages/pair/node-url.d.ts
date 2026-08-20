declare module "node:url" {
  export function fileURLToPath(url: string | URL): string;
  export const URL: typeof globalThis.URL;
}
