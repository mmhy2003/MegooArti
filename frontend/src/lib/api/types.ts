/** The API's shapes, by the names the UI uses. They come from the backend's own document. */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type SessionInfo = Schemas["SessionInfo"];
export type UserSummary = Schemas["UserSummary"];
export type RepositoryView = Schemas["RepositoryView"];

/** A page of a list, as every list endpoint answers. */
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
