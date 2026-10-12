// For the container's health check: the server is up and answering.
export function GET() {
  return new Response("ok\n", {
    headers: { "Content-Type": "text/plain", "Cache-Control": "no-store" },
  });
}
