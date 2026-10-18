# AI agents (MCP)

An AI agent works with MegooArti through the Model Context Protocol (MCP), at the
installation's `/mcp` address: `https://artifacts.example.org/mcp`. A coding agent in
your editor asks it which versions of a package there are, where they come from, what
to add to a project to use one, and how to point a project's package manager at a
repository. It can also tell you whether a proxy's remote is failing, and what it said.

The agent does what you may do, and no more: it signs in with one of your API tokens,
and a token whose scopes are narrower narrows it too.

## Signing in

Make an API token in the web UI under Account, Tokens (or at `/api/v1/me/tokens`), and
give it to the agent as a bearer token: `Authorization: Bearer mga_...`. Nothing else
signs in to `/mcp`: not a password, not the web UI's session, and not anonymous access.

Give an agent a token of its own, with the scopes it needs, and an expiry. For an agent
that only reads, `repository:*:*:browse` and `repository:*:*:read`. The token's
scopes narrow what the agent may do, and what it is shown: a tool it could not use is
not listed to it.

## Connecting a client

Any client that speaks MCP's Streamable HTTP transport, and can send a header, connects.

**Claude Code:**

```sh
claude mcp add --transport http megooarti https://artifacts.example.org/mcp \
  --header "Authorization: Bearer $MEGOOARTI_TOKEN"
```

**Cursor** (`~/.cursor/mcp.json`, or `.cursor/mcp.json` in a project):

```json
{
  "mcpServers": {
    "megooarti": {
      "url": "https://artifacts.example.org/mcp",
      "headers": { "Authorization": "Bearer mga_..." }
    }
  }
}
```

**VS Code** (`.vscode/mcp.json`):

```json
{
  "servers": {
    "megooarti": {
      "type": "http",
      "url": "https://artifacts.example.org/mcp",
      "headers": { "Authorization": "Bearer ${input:megooarti-token}" }
    }
  },
  "inputs": [
    { "id": "megooarti-token", "type": "promptString", "description": "MegooArti API token", "password": true }
  ]
}
```

A client that only signs in with OAuth, such as claude.ai's connectors, cannot connect
yet.

## The tools

| Tool | What it answers |
| --- | --- |
| `search_packages` | Packages by words, format, repository, namespace, name, version or the checksum of a file |
| `package_versions` | Every version of one package, the newest first as its format orders them, which repositories have each (hosted, or a proxy's cache), and the newest release |
| `package_details` | One version's files, with sizes, checksums and download addresses, and how a project uses it: the dependency for a `pom.xml`, a `package.json`, a `.csproj` |
| `browse` | The folders and files of a repository |
| `list_repositories` | The repositories, with their format, type, address and whether they are online |
| `repository_details` | A repository's address, a group's members, and how a client is set up to use it (`nuget.config`, a sources line, a Docker login) |
| `whoami` | Who the agent acts as, what they may do, and the token's scopes and expiry |
| `system_status` | The version, and whether the server is ready |

Each tool answers as the REST API does for the same caller: a list leaves out what the
caller may not browse. Those who may read repositories' settings also get, from
`list_repositories` and `repository_details`, a proxy's remote, its settings (never a
secret), whether it is blocked, and the last error its remote gave; those who may read
the system's settings and blob stores get what `system_status` says of them.

A proxy's versions are those it has fetched so far, not all its remote has. Docker's
tags have no order: they are listed from the one pushed or fetched last. Where packages
of one name are in several namespaces (`react` and `@types/react`, a Maven artifact in two
groups), `package_versions` and `package_details` ask which: `namespace` names it, and
`""` names none. A group holds nothing of its own: `search_packages` and
`package_details` name its members to ask instead, and `package_versions` gives its
members' versions.

## What an agent is given

- **A page at a time.** A list gives 50 items, or up to 200 if asked, and a
  `next_cursor` to ask for the next. No answer's text is longer than 64 KiB; one that
  would be is cut, and says so (`truncated`).
- **Refusals in the API's words.** A tool that is refused answers with the error the
  REST API gives, its code first: `forbidden: You do not have permission to do this.`
- **Text from elsewhere, marked.** What a remote server or a package's author wrote is
  in a field whose name ends in `_untrusted`, and the server tells the agent never to
  follow instructions found there. A package can be written to mislead an agent that
  reads it.

Each tool call is logged (`mcp_tool_called`): who made it, with which token, the tool,
its arguments, how it ended and how long it took.

## Behind your own reverse proxy

The gateway passes `/mcp` to the backend (see
[Behind your own reverse proxy](installation.md#behind-your-own-reverse-proxy)). A
reverse proxy of your own in front of the backend must pass `/mcp` too.
