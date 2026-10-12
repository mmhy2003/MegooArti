import { API_PREFIX, ApiError, csrfHeader, errorOf, REQUEST_ID } from "./client";

export type Sent = { sent: number; total: number };

export type UploadOptions = {
  /** Called as the body goes out. `fetch` cannot say how much has been sent. */
  onProgress?: (progress: Sent) => void;
  /** Stops the upload. The promise then rejects with an `AbortError`. */
  signal?: AbortSignal;
};

/**
 * Sends a form with files to the API. It is the one request that is not made with
 * `fetch`: an artifact can be gigabytes, and whoever sends one wants to see it go.
 * Failures are the same `ApiError` as everywhere else.
 */
export function upload<T>(path: string, form: FormData, options: UploadOptions = {}): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${API_PREFIX}${path}`);
    request.setRequestHeader("Accept", "application/json");
    for (const [name, value] of Object.entries(csrfHeader())) request.setRequestHeader(name, value);

    request.upload.onprogress = (event) => {
      if (event.lengthComputable) options.onProgress?.({ sent: event.loaded, total: event.total });
    };
    request.onerror = () => reject(new ApiError(0, "network_error", ""));
    request.onabort = () => reject(new DOMException("The upload was stopped.", "AbortError"));
    request.onload = () => {
      const requestId = request.getResponseHeader(REQUEST_ID);
      let body: unknown = null;
      try {
        body = JSON.parse(request.responseText);
      } catch {
        // Not JSON: a gateway's own page, or nothing at all.
      }
      if (request.status >= 200 && request.status < 300 && body !== null) resolve(body as T);
      else if (request.status >= 200 && request.status < 300) {
        reject(new ApiError(request.status, "unexpected_answer", "", [], requestId));
      } else reject(errorOf(request.status, body, requestId));
    };

    if (options.signal?.aborted) {
      reject(new DOMException("The upload was stopped.", "AbortError"));
      return;
    }
    options.signal?.addEventListener("abort", () => request.abort(), { once: true });
    request.send(form);
  });
}
