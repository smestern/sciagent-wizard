# <img src="logo.svg" height="32" alt="SciAgent"> SciAgent Wizard

**Self-assembly wizard for building domain-specific [SciAgent](https://github.com/smestern/sciagent) agents.**

()

Describe your research domain in plain language, upload example data, and the wizard automatically discovers relevant scientific packages, fetches their documentation, and generates a ready-to-use agent project — no programming required.

---

## Quick Start

```bash
pip install sciagent-wizard          # install the wizard
sciagent-wizard                      # launch conversational wizard
```

Or install via the core framework:

```bash
pip install sciagent[wizard]         # install sciagent + wizard plugin
sciagent wizard                      # launch via sciagent CLI
```

Three CLI entry points are available:

| Command | Description |
|---------|-------------|
| `sciagent-wizard` | Conversational wizard (freeform chat) |
| `sciagent-public` | Guided public wizard (structured questions, rate-limited) |
| `sciagent-docs` | Docs ingestor agent (deep documentation extraction) |

---

## How It Works

The wizard is itself an LLM-powered agent. It walks you through a conversational workflow:

```
Interview → Discover packages → Analyze example data → Recommend
    → Confirm selections → Fetch docs → Set identity → Generate project
```

1. **Interview** — Describe your research domain, data types, and analysis goals
2. **Discover** — The wizard searches 5 sources in parallel for relevant scientific packages
3. **Analyze** — Upload example data files; the wizard infers file types, column names, value ranges, and domain hints (e.g. electrophysiology, genomics, chemistry)
4. **Recommend** — Candidates are ranked by relevance, deduplicated across sources, and presented for review
5. **Confirm** — Accept, reject, or add packages manually
6. **Fetch docs** — Full documentation is crawled for each confirmed package (GitHub README, PyPI, ReadTheDocs)
7. **Identity** — Name your agent, add a description and emoji
8. **Generate** — Choose an output mode and the wizard scaffolds the entire project

---

## Multi-Source Package Discovery

The wizard searches five independent sources in parallel and merges results:

| Source | What it finds |
|--------|---------------|
| **PyPI** | Keyword + convention-pattern matching against the full package index; science classifier boosting |
| **bio.tools** | ELIXIR curated registry; EDAM ontology topic matching; peer-review flags from linked DOIs |
| **Papers With Code** | Academic papers with linked repositories; star count and official-repo boosting |
| **PubMed** | Europe PMC search; extracts GitHub URLs and `pip install` mentions from abstracts; citation counts |
| **Google CSE** | Playwright-based web search (no API key needed); mines PyPI/GitHub URLs from results |

Packages found by multiple sources receive a **multi-source relevance boost** (+0.12 per additional confirmation). Results are deduplicated by normalized package name and sorted by relevance, citations, then name.

---

## Output Modes

The wizard generates agents in one of three formats:

| Mode | CLI flag | What you get |
|------|----------|-------------|
| **Fullstack** | `-m fullstack` | Complete Python submodule with CLI, web UI, sandboxed code execution, guardrails, config, tools, and domain prompt |
| **Copilot / Claude Code** | `-m copilot_agent` | `.github/agents/{name}.agent.md` + `.claude/agents/{name}.md` + shared instructions — drops into your IDE |
| **Markdown** | `-m markdown` | Platform-agnostic spec files (`system-prompt.md`, `tools-reference.md`, `guardrails.md`, etc.) — paste into any LLM |

### Fullstack output includes:

- `agent.py` — Domain-specific agent subclass
- `config.py` — `AgentConfig` with file types, suggestion chips, bounds, guardrail patterns
- `tools.py` — `@tool`-decorated wrappers per confirmed package
- `domain_prompt.py` — `DOMAIN_EXPERTISE` system prompt constant
- `requirements.txt`, `README.md`, `docs/`, `sample_data/`

### Copilot / Claude Code output includes:

- `.github/agents/{name}.agent.md` — VS Code Copilot custom agent (YAML frontmatter)
- `.claude/agents/{name}.md` — Claude Code sub-agent
- `.github/instructions/{name}.instructions.md` — Shared domain expertise
- `docs/`, `README.md`

### Markdown output includes:

- `system-prompt.md`, `tools-reference.md`, `data-guide.md`, `guardrails.md`, `workflow.md`, `agent-spec.md`
- `docs/`, `README.md`

---

## Docs Ingestor

The docs ingestor is a standalone agent that deep-crawls documentation for confirmed packages and produces structured API reference files.

```bash
sciagent-docs
```

It crawls multiple sources per package (PyPI metadata, GitHub README + source files, ReadTheDocs, docs/notebooks directories) and uses an LLM to extract four structured sections:

- **Core Classes** — Key classes with signatures and descriptions
- **Key Functions** — Important functions with usage patterns
- **Common Pitfalls** — Gotchas and mistakes to avoid
- **Quick-Start Recipes** — Copy-paste code snippets

Output is assembled into a `library_api.md` reference file. The ingestor exposes a web UI at `/ingestor` with WebSocket-based chat and a download endpoint for results.

---

## Python API

```python
from sciagent_wizard import create_wizard, WIZARD_CONFIG

# Standard conversational mode
wizard = create_wizard()

# Guided mode (structured questions, for public-facing deployments)
wizard = create_wizard(guided_mode=True)
```

The wizard is a `BaseScientificAgent` subclass — it can be used programmatically, embedded in a Quart web app, or run via the CLI.

### Plugin integration

`sciagent-wizard` registers as a [`sciagent.plugins`](https://github.com/smestern/sciagent) entry point. When installed alongside the core framework, the wizard's web blueprints (`/wizard/`, `/public/`, `/ingestor/`), CLI commands, and auth middleware are automatically discovered and mounted.

---

## Deployment

A production `Dockerfile` and `railway.toml` are included for deploying the public wizard + docs ingestor.

```bash
docker build -t sciagent-wizard .
docker run -p 8080:8080 \
  -e GITHUB_OAUTH_CLIENT_ID=... \
  -e GITHUB_OAUTH_CLIENT_SECRET=... \
  sciagent-wizard
```

The container runs a single Hypercorn worker (in-memory session state) serving both `/public/` and `/ingestor/` routes. Playwright + Chromium are pre-installed for Google CSE discovery.

### Railway

The included `railway.toml` is pre-configured for one-click Railway deployment with health checks on `/public/`.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_OAUTH_CLIENT_ID` | For auth | GitHub OAuth App client ID |
| `GITHUB_OAUTH_CLIENT_SECRET` | For auth | GitHub OAuth App client secret |
| `SCIAGENT_SESSION_SECRET` | Recommended | Session cookie signing key (random string) |
| `SCIAGENT_SESSION_SECURE` | No | Set to `1` for HTTPS-only session cookies |
| `SCIAGENT_ALLOWED_ORIGINS` | No | Restrict CORS origins (default: `*`) |
| `SCIAGENT_INVITE_CODE` | No | Alternative to OAuth — simple invite code gate |
| `GOOGLE_CSE_CX` | No | Custom Google CSE engine ID (default: built-in) |
| `PORT` | No | Server port (default: `8080`) |

---

<details>
<summary><strong>Authentication (Optional)</strong></summary>

The public wizard (`/public`) and docs ingestor (`/ingestor`) support **opt-in GitHub OAuth** via the [Copilot SDK auth flow](https://github.com/github/copilot-sdk/blob/main/docs/auth/index.md#github-signed-in-user). When enabled, users sign in with GitHub and their OAuth token is passed through to the Copilot SDK, billing LLM usage to their own Copilot subscription.

An alternative **invite code** gate is also available via `SCIAGENT_INVITE_CODE`.

**When auth env vars are not set, the app runs fully open — no middleware, no redirects, no cookies.**

### Setup

1. [Create a GitHub OAuth App](https://docs.github.com/en/developers/apps/building-oauth-apps/creating-an-oauth-app):
   - **Homepage URL:** `https://your-domain.com`
   - **Authorization callback URL:** `https://your-domain.com/auth/callback`

2. Set `GITHUB_OAUTH_CLIENT_ID` and `GITHUB_OAUTH_CLIENT_SECRET` environment variables.

3. Run: `sciagent-public` or `sciagent-docs`

### How it works

- `/auth/login` → GitHub OAuth authorize → `/auth/callback` exchanges code for token → stored in HttpOnly session cookie
- Protected routes redirect unauthenticated users to `/auth/login`
- Token threaded through to `CopilotClient({"github_token": ...})`

### Security

- Session cookies: `HttpOnly`, `SameSite=Lax`, 1-hour lifetime
- CSRF protection via `secrets.token_urlsafe(32)` state parameter
- Only `gho_*`, `ghu_*`, `github_pat_*` tokens accepted (classic `ghp_*` PATs rejected)
- When auth is disabled: **zero auth code runs**

</details>

---

## Development

```bash
git clone https://github.com/smestern/sciagent-wizard.git
cd sciagent-wizard
pip install -e ".[dev]"
pytest
```

Dev dependencies: pytest, pytest-asyncio, pytest-cov, black, ruff.

---

## See Also

- [SciAgent](https://github.com/smestern/sciagent) — the core framework this wizard builds agents for
- [PatchAgent](https://github.com/smestern/patchAgent) — a full SciAgent implementation for electrophysiology
- [DAAF](https://github.com/DAAF-Contribution-Community/daaf) — Data Analyst Augmentation Framework by Brian Heseung Kim, a project with parallel evolution of similar ideas

---

## License

MIT
