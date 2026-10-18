"""MegooArti for AI agents: an MCP server at `/mcp`.

Each tool does what the REST API does for the same caller, through the same route
functions and the same `authorize()`: only what the caller may, and less where its token
says so. The design is docs/superpowers/specs/2026-10-18-mcp-design.md.
"""
