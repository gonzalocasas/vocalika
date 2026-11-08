import { isDesktopApp } from "./api"

/**
 * Open a web link outside the app.
 *
 * In a browser the link's own `target="_blank"` does it. The desktop app's
 * window would instead replace Vocalika with the page, so there the server
 * opens it in the system browser. Use as a link's click handler.
 */
export async function openExternal(event: MouseEvent): Promise<void> {
  const link = (event.currentTarget as HTMLElement).closest("a")
  if (!link?.href.startsWith("https://")) return
  // Decide synchronously: after an await, the default can no longer be held.
  event.preventDefault()
  if (await isDesktopApp()) {
    await fetch("/api/about/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: link.href }),
    })
  } else {
    window.open(link.href, "_blank", "noopener")
  }
}
