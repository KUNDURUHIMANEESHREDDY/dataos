export function safeNextPath(value) {
  if (typeof value !== "string" || !value.startsWith("/")) return "/dataspace";
  if (value.startsWith("//") || value.includes("\\") || /[\r\n]/.test(value)) {
    return "/dataspace";
  }

  try {
    const destination = new URL(value, "https://dataos.invalid");
    const isDataspaceRoute =
      destination.pathname === "/dataspace" ||
      destination.pathname.startsWith("/dataspace/");
    if (destination.origin !== "https://dataos.invalid" || !isDataspaceRoute) {
      return "/dataspace";
    }
    return `${destination.pathname}${destination.search}${destination.hash}`;
  } catch {
    return "/dataspace";
  }
}
