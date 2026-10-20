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
/** An API token as it is listed: never its secret. */
export type TokenInfo = Schemas["TokenInfo"];
/** A token that was just made, with its secret, which is given this once. */
export type TokenCreated = Schemas["TokenCreated"];
export type TokenCreate = Schemas["TokenCreate"];
export type UserOut = Schemas["UserOut"];
export type UserCreate = Schemas["UserCreate"];
export type UserUpdate = Schemas["UserUpdate"];
export type PasswordReset = Schemas["PasswordReset"];
export type RoleOut = Schemas["RoleOut"];
export type RoleCreate = Schemas["RoleCreate"];
export type RoleContent = Schemas["RoleContent"];
export type SettingsOut = Schemas["SettingsOut"];
/** The default role, and whether MegooArti's own users sign in (spec 4.1). */
export type SignInSettings = Schemas["SignInSettings"];
/** A sign-in source as an administrator sees it: never its secrets. */
export type SourceOut = Schemas["SourceOut"];
export type SourceIn = Schemas["SourceIn"];
export type SourceCreate = Schemas["SourceCreate"];
/** A source the sign-in screen offers: signed in to at a provider, in the browser. */
export type SignInSource = Schemas["SignInSource"];
/** What testing a source found. */
export type SourceTested = Schemas["TestOut"];
/** A repository as an administrator sees it: how it is set up, and a proxy's state. */
export type RepositoryOut = Schemas["RepositoryOut"];
export type RepositoryCreate = Schemas["RepositoryCreate"];
export type RepositoryUpdate = Schemas["RepositoryUpdate"];
export type ProxyStatus = Schemas["ProxyStatus"];
export type IndexRebuilt = Schemas["IndexRebuilt"];
/** What a repository signs its indexes with: never its private key. */
export type SigningKeyOut = Schemas["SigningKeyOut"];
export type SigningKeyGenerate = Schemas["SigningKeyGenerate"];
export type SigningKeyImport = Schemas["SigningKeyImport"];
export type BlobStoreOut = Schemas["BlobStoreOut"];
/** An application a user let sign in as them with OAuth (MCP spec 7.6). */
export type ConnectedApp = Schemas["ConnectedApp"];
/** What an application asks, as the consent page shows it. */
export type Asked = Schemas["Asked"];
export type Consent = Schemas["Consent"];
/** Where the browser goes after the consent page: back to the application. */
export type Redirect = Schemas["Redirect"];
/** A format the server has: its types, and the public repository a new proxy is given. */
export type FormatOut = Schemas["FormatOut"];
export type BlobStoreCreate = Schemas["BlobStoreCreate"];
/** A change of configuration or security, or a sign-in, as the audit log keeps it (spec 9). */
export type AuditRecordOut = Schemas["AuditRecordOut"];
/** How many days the audit log keeps a record. */
export type Retention = Schemas["Retention"];
/** A certificate outbound TLS trusts besides the usual authorities (spec 6). */
export type CertificateOut = Schemas["CertificateOut"];
/** A certificate as a person checks it: what a host presented, before it is trusted. */
export type CertificateView = Schemas["CertificateView"];
/** What is running: version, schema, runtime, database. */
export type Information = Schemas["Information"];

/** A page of a list, as every list endpoint answers. */
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
