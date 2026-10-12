import { vi } from "vitest";

/** One upload the UI started, as a test looks at it and answers it. */
export class FakeUpload {
  method = "";
  url = "";
  headers: Record<string, string> = {};
  /** The parts of the form that was sent: its name, and a text or a file's name. */
  parts: [string, string][] = [];
  status = 0;
  responseText = "";
  aborted = false;
  upload: { onprogress: ((event: unknown) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  private answered: Record<string, string> = {};

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value;
  }

  getResponseHeader(name: string): string | null {
    return this.answered[name] ?? null;
  }

  send(form: FormData): void {
    this.parts = Array.from(form.entries()).map(([name, value]) => [
      name,
      typeof value === "string" ? value : `file:${value.name}`,
    ]);
    sent.push(this);
  }

  abort(): void {
    this.aborted = true;
    this.onabort?.();
  }

  /** So much of the body has gone out. */
  progress(loaded: number, total: number): void {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total });
  }

  /** The API answers. */
  answer(status: number, body: unknown, headers: Record<string, string> = {}): void {
    this.status = status;
    this.responseText = typeof body === "string" ? body : JSON.stringify(body);
    this.answered = headers;
    this.onload?.();
  }

  /** No answer comes at all. */
  fail(): void {
    this.onerror?.();
  }
}

let sent: FakeUpload[] = [];

/** Stands in for the browser's uploader. What the UI sends is in the list it returns. */
export function mockUploads(): FakeUpload[] {
  sent = [];
  vi.stubGlobal("XMLHttpRequest", FakeUpload);
  return sent;
}
