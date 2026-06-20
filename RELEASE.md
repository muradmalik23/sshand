# Release guide

This document covers where to release SSHand and the exact steps to do it.

---

## Where to release

### 1. PyPI (primary — required)

PyPI is the main distribution channel. After publishing, users install with:

```bash
pip install sshand
uvx sshand setup
```

This is how most developers and AI-client power users will find the package.

### 2. GitHub Releases (required)

Tag each release on GitHub so there is a stable, versioned source download and a public changelog entry. GitHub also powers the `uvx` zero-install flow (uv resolves the package from PyPI but links back here for issues and source).

### 3. MCP Registry (recommended — biggest discovery boost)

Anthropic maintains an official registry of MCP servers at:
**https://github.com/modelcontextprotocol/servers**

Submitting SSHand there means it will appear in MCP client discovery UIs (Claude Desktop, etc.) and in documentation. This is the highest-value listing for an MCP server.

To submit: open a PR against that repo adding an entry to `README.md` in the correct category, following their contribution guidelines.

### 4. Glama.ai / Smithery (optional — community directories)

Community MCP directories that aggregate servers for easy discovery:
- **https://glama.ai/mcp/servers** — submit via their web form
- **https://smithery.ai** — submit via their web form

These are worth doing after the GitHub and PyPI releases are stable.

---

## Release checklist

### Pre-release

- [ ] Delete stale build artifacts from old package names: `rm -rf ssh_mcp.egg-info emissary.egg-info`
- [ ] All 11 tools verified end-to-end with MCP Inspector (`pytest` currently reports "no tests ran" — there's no unit test suite yet, so the Inspector pass is the real verification step; see `CONTRIBUTING.md`)
- [ ] `hosts.yaml` contains no real credentials (check against `hosts.yaml.example`)
- [ ] `hosts.yaml` is listed in `.gitignore`
- [ ] Version bumped in `pyproject.toml` (currently `0.1.0`)
- [ ] `CHANGELOG.md` updated — move items from `[Unreleased]` to the new version section
- [ ] GitHub URL placeholders replaced in `pyproject.toml`, `CHANGELOG.md`, `CONTRIBUTING.md`, and `RELEASE.md`
  - Find: `YOUR_GITHUB_USERNAME`
  - Replace with your actual GitHub username
- [ ] Quick-start test in a clean venv: `pip install sshand && sshand setup`

### Build and publish to PyPI

```bash
# Install build tools (one-time)
pip install build twine

# Build source + wheel
python -m build

# Upload to PyPI
twine upload dist/*
# → enter your PyPI API token when prompted
#   Get one at: https://pypi.org/manage/account/token/
```

For a dry run (TestPyPI), use:
```bash
twine upload --repository testpypi dist/*
```

### Tag and publish a GitHub Release

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

Then on GitHub: **Releases → Draft a new release → choose tag v0.1.0 → paste CHANGELOG section → Publish release**.

Attach the files from `dist/` (the `.whl` and `.tar.gz`) as release assets.

### Submit to the MCP Registry

1. Fork https://github.com/modelcontextprotocol/servers
2. Add an entry to the README in the **"Remote access / Infrastructure"** category (or the closest match):

```markdown
- **[SSHand](https://github.com/YOUR_GITHUB_USERNAME/sshand)** — Full SSH shell access,
  file read/write, and SFTP for any Linux/Unix machine. Works with Claude Desktop, Claude.ai,
  ChatGPT Desktop, Cursor, VS Code Copilot, OpenAI Agents SDK, and any HTTP MCP client.
```

3. Open a PR. Include a brief description and a link to the PyPI page.

### Post-release

- [ ] Announce on relevant communities (r/ClaudeAI, Anthropic Discord, Hacker News "Show HN")
- [ ] Submit to Glama.ai and Smithery if desired
- [ ] Update the GitHub repo description and topics:
  - Topics: `mcp`, `ssh`, `claude`, `chatgpt`, `ai-agent`, `llm`, `openai`, `modelcontextprotocol`

---

## Versioning policy

This project follows **Semantic Versioning**:

- **Patch** (0.1.x) — bug fixes, no API changes
- **Minor** (0.x.0) — new tools or options, backwards-compatible
- **Major** (x.0.0) — breaking changes to tool names, parameters, or auth format

Update `version` in `pyproject.toml` and add a section to `CHANGELOG.md` for every release.
