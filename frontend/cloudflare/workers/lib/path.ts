export function canonicalPathname(pathname: string): string {
  return pathname.replace(/\/+$/, "") || "/";
}
