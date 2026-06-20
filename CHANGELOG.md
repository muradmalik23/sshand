# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] — 2025-06-01

Initial public release.

### Added

- **11 MCP tools** exposed over stdio and streamable-HTTP transports:
  - `ssh_list_hosts` — show the full host inventory
  - `ssh_add_host` — register a new SSH target
  - `ssh_remove_host` — remove a host from the inventory
  - `ssh_test_connection` — verify credentials before use
  - `ssh_run_command` — execute a shell command and capture output
  - `ssh_read_file` — read a remote file via SFTP
  - `ssh_write_file` — create or overwrite a remote file via SFTP
  - `ssh_list_directory` — browse a remote directory
  - `ssh_upload_file` — push a local file to the remote host
  - `ssh_download_file` — pull a remote file to the local machine
  - `ssh_get_local_info` — discover OS and path style of the MCP server host
- **Three auth types**: SSH private key, password, and ssh-agent delegation
- **Interactive setup wizard** (`sshand setup`) with per-client config snippets for Claude Desktop, Cursor, VS Code, OpenAI Agents SDK, and generic HTTP clients
- **Rich agent instructions** — embedded workflow guide, tool cheat-sheet, and safety notes surfaced to every AI client
- **Connection cache** — paramiko connections are reused across tool calls to avoid repeated handshakes
- **`cwd` and `sudo` support** in `ssh_run_command`
- **Binary file support** — base64 encoding/decoding in `ssh_read_file` and `ssh_write_file`
- **Automatic remote `mkdir -p`** when writing or uploading files to paths with missing parent directories
- **Windows SSH agent detection** — setup wizard checks the OpenSSH Authentication Agent service and offers to enable it
- **MCP annotations** — tools declare `readOnlyHint`, `destructiveHint`, and `idempotentHint` so compliant clients can prompt before running destructive operations
- **`pip install sshand`** and **`uvx sshand`** install modes
- **Markdown and JSON output formats** on all listing/inspection tools

[0.1.0]: https://github.com/YOUR_GITHUB_USERNAME/sshand/releases/tag/v0.1.0
