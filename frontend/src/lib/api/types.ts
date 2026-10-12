/** The API's shapes, by the names the UI uses. They come from the backend's own document. */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type SessionInfo = Schemas["SessionInfo"];
export type UserSummary = Schemas["UserSummary"];
export type RepositoryView = Schemas["RepositoryView"];
/** One thing in a folder: a folder, or a file with its size and when it changed. */
export type Entry = Schemas["Entry"];
/** A folder's entries, and the cursor for those that follow. */
export type Listing = Schemas["Listing"];
export type AssetView = Schemas["AssetView"];
export type ComponentRef = Schemas["ComponentRef"];
export type ComponentDetail = Schemas["ComponentDetail"];
export type UsageView = Schemas["UsageView"];
export type SearchResult = Schemas["Result"];
export type Uploaded = Schemas["Uploaded"];
export type FolderDeleted = Schemas["FolderDeleted"];

/** A page of a list, as every list endpoint answers. */
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
