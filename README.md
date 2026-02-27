# <img src="logo.svg" height="32" alt="SciAgent"> SciAgent

**A generic framework for building AI-powered scientific data analysis agents.**

## Alternate

You may be interested in [DAAF](https://github.com/DAAF-Contribution-Community/daaf), the Data Analyst Augmentation Framework, by Brian Heseung Kim! A framework with much of the same goals and ideas. We accidentally had parallel evolution of our ideas.


## Quick Start

```bash
pip install sciagent[all]       # install everything
sciagent wizard                 # launch the self-assembly wizard
```

The wizard walks you through a conversation — describe your research domain, confirm discovered packages, and choose an output mode. A ready-to-use agent drops out the other end.

---

## Three Output Streams

SciAgent generates a domain-specific scientific agent in one of three formats. Pick the one that fits your workflow:

### 1. Fullstack — Python agent with CLI & web UI

A complete, runnable Python submodule you can install and launch immediately. Includes sandboxed code execution, guardrails, Rich terminal REPL, and browser-based chat UI.

```bash
sciagent wizard -m fullstack
```

**[Full setup guide →](docs/getting-started-fullstack.md)**

### 2. Copilot / Claude Code — IDE config files

Markdown-based agent definitions that plug directly into VS Code Copilot Chat or Claude Code. No Python runtime needed at the endpoint.

```bash
sciagent wizard -m copilot_agent
```

**[Full setup guide →](docs/getting-started-copilot.md)**

### 3. Markdown — platform-agnostic spec files

A self-contained set of Markdown files defining persona, tools, data handling, guardrails, and workflow. Paste into any LLM — ChatGPT, Gemini, Claude, local models, etc.

```bash
sciagent wizard -m markdown
```

**[Full setup guide →](docs/getting-started-markdown.md)**

---

## Default Scientific Agents

SciAgent ships 5 ready-to-use agents in [`templates/agents/`](templates/agents/) that implement common scientific workflow roles:

| Agent | Role |
|-------|------|
| `analysis-planner` | Design the analysis roadmap (read-only) |
| `data-qc` | Check data quality before analysis |
| `rigor-reviewer` | Audit results for scientific rigor (read-only) |
| `report-writer` | Generate structured reports |
| `code-reviewer` | Review scripts for correctness (read-only) |

These agents support handoff workflows: `planner → QC → your agent → rigor review → report`. See [Copilot Agents & Skills Reference](docs/copilot-agents.md) for details.

---

## Guardrails

SciAgent enforces scientific rigor through a 5-layer system:

1. **System prompt principles** — embedded scientific best practices
2. **Tool priority hierarchy** — load real data before analysis
3. **Code scanner** — regex patterns block synthetic data generation, result fabrication
4. **Data validator** — checks for NaN, Inf, zero variance, suspicious smoothness
5. **Bounds checker** — domain-specific value range warnings

All layers are configurable and extensible. See [Architecture](docs/architecture.md) for the full pipeline diagram.

---

## Installation

```bash
pip install sciagent            # core only
pip install sciagent[cli]       # + terminal REPL
pip install sciagent[web]       # + browser chat UI
pip install sciagent[wizard]    # + self-assembly wizard
pip install sciagent[all]       # everything
```

See [Installation](docs/installation.md) for prerequisites, dev setup, and verification steps.

---

## See Also

- [PatchAgent](https://github.com/smestern/patchAgent) — a full SciAgent implementation for electrophysiology (see [Showcase](docs/showcase.md))
- [Templates README](templates/README.md) — blank templates for manual agent specification

---

<details>
<summary><strong>Authentication (Optional)</strong></summary>

The public wizard (`/public`) and docs ingestor (`/ingestor`) support **opt-in GitHub OAuth** via the [Copilot SDK auth flow](https://github.com/github/copilot-sdk/blob/main/docs/auth/index.md#github-signed-in-user). When enabled, users sign in with GitHub and their OAuth token is passed through to the Copilot SDK, billing LLM usage to their own Copilot subscription.

**When OAuth env vars are not set, the app behaves exactly as before — fully open, no auth.**

### Setup

1. [Create a GitHub OAuth App](https://docs.github.com/en/developers/apps/building-oauth-apps/creating-an-oauth-app):
   - **Homepage URL:** `https://your-domain.com`
   - **Authorization callback URL:** `https://your-domain.com/auth/callback`

2. Set environment variables:

   | Variable | Required | Description |
   |----------|----------|-------------|
   | `GITHUB_OAUTH_CLIENT_ID` | Yes | OAuth App client ID |
   | `GITHUB_OAUTH_CLIENT_SECRET` | Yes | OAuth App client secret |
   | `SCIAGENT_SESSION_SECRET` | Recommended | Session cookie signing key (random string) |
   | `SCIAGENT_SESSION_SECURE` | No | Set to `1` for HTTPS-only session cookies |
   | `SCIAGENT_ALLOWED_ORIGINS` | No | Restrict CORS origins (default: `*`) |

3. Run: `sciagent-public` (wizard) or `sciagent-docs` (ingestor)

### How it works

- `/auth/login` → GitHub OAuth authorize → `/auth/callback` exchanges code for token → stored in HttpOnly session cookie
- Protected routes redirect unauthenticated users to `/auth/login`
- Token threaded through to `CopilotClient({"github_token": ...})`

### Security

- Session cookies: `HttpOnly`, `SameSite=Lax`
- CSRF protection via `secrets.token_urlsafe(32)` state parameter
- Only `gho_*`, `ghu_*`, `github_pat_*` tokens accepted (classic `ghp_*` PATs rejected)
- When OAuth is disabled: **zero auth code runs** — no middleware, no redirects, no cookies

</details>

---

## License

MIT
