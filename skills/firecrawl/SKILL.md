---
name: firecrawl
description: |
  Firecrawl gives AI agents and apps fast, reliable web context with
  strong search, scraping, and interaction tools. One install command
  sets up both live CLI tools and app-integration skills. Route the
  reader to the right usage path after install.
---

# Firecrawl

Firecrawl helps agents search first, scrape clean content, and interact
with live pages when plain extraction is not enough.

## Repository Rules

- Do not commit Firecrawl API keys or generated credentials. Use `FIRECRAWL_API_KEY`, `firecrawl login --browser`, or local machine config.
- Prefer the repo wrapper over ad hoc commands from this repository:

```powershell
npm run firecrawl -- <args>
```

- Use `.firecrawl/` for install checks and temporary Firecrawl outputs; it is ignored by git.
- Use `--only-main-content` for article/docs-style extraction unless the user asks for full page chrome.
- For long crawls, set explicit limits such as `--limit`, `--max-depth`, `--timeout`, and `--max-concurrency`.
- For current behavior, verify against official docs at `https://docs.firecrawl.dev/sdks/cli` when unsure.

## Install

One command installs everything: the Firecrawl CLI for live web work
and the build skills for integrating Firecrawl into application code. It
also opens browser auth so the human can sign in or create an account.

```powershell
npm run firecrawl:init
```

This wraps:

```powershell
npx -y firecrawl-cli@latest init --all --browser
```

This gives you:

- **CLI tools**: `firecrawl search`, `firecrawl scrape`, `firecrawl interact`, `firecrawl ask`, `firecrawl docs-search`, and more.
- **CLI skills**: `firecrawl/cli`, `firecrawl-search`, `firecrawl-scrape`, `firecrawl-interact`, `firecrawl-crawl`, `firecrawl-map`, `firecrawl-ask`, `firecrawl-docs-search`.
- **Build skills**: `firecrawl-build`, `firecrawl-build-onboarding`, `firecrawl-build-scrape`, `firecrawl-build-search`, `firecrawl-build-interact`, `firecrawl-build-crawl`, `firecrawl-build-map`.
- **Browser auth**: walks the human through sign-in or account creation.

Before real work, verify the install:

```powershell
New-Item -ItemType Directory -Force -Path .firecrawl | Out-Null
npm run firecrawl:status
npm run firecrawl -- scrape "https://firecrawl.dev" -o .firecrawl/install-check.md
```

## Choose Your Path

Both paths use the same install above. The difference is what you do next.

- **Need web data during this session**: Path A, live tools.
- **Need to add Firecrawl to app code**: Path B, app integration.
- **Need both**: do both; the install already covers everything.
- **Need an account or API key first**: Path C, auth only.
- **Do not want to install anything**: Path D, REST API directly.

## Path A: Live Web Tools

Use this when you need web data during your work: searching the web,
scraping known URLs, interacting with live pages, crawling docs, or
mapping a site.

After install, hand off to the CLI skill:

- `firecrawl/cli` for the overall command workflow.
- `firecrawl-search` when discovery is needed.
- `firecrawl-scrape` when the URL is already known.
- `firecrawl-interact` when the page needs clicks, forms, login, or live browser actions.
- `firecrawl-crawl` for bulk extraction.
- `firecrawl-map` for URL discovery.
- `firecrawl-ask` when a Firecrawl call fails or returns unexpected output; pass the failing `jobId` and let the AI support agent diagnose it from team job logs and account state.
- `firecrawl-docs-search` for Firecrawl "how does X work?" questions grounded in current docs.

Default flow:

1. Start with search when discovery is needed.
2. Move to scrape when a URL is known.
3. Use interact only when the page needs clicks, forms, login, or live browser state.
4. If a step fails or returns unexpected output, run `firecrawl ask` with the failing `jobId` instead of guessing.

If the task becomes "wire Firecrawl into product code," switch to Path B.

## Path B: Integrate Firecrawl Into App Code

Use this when building an application, agent, or workflow that calls the
Firecrawl API from code and needs `FIRECRAWL_API_KEY` in `.env` or
runtime config.

The build skills are already installed from the same command above. No
separate install is needed.

Choose the project mode before writing code:

- Fresh project: pick the stack, install the SDK, add env vars, and run a smoke test.
- Existing project: inspect the repo first, then integrate Firecrawl where the project already handles APIs and secrets.

If a key is available, save it only in local secret storage such as `.env`, never in committed source:

```powershell
FIRECRAWL_API_KEY=fc-...
```

Then use:

- `firecrawl-build-onboarding` to finish auth and project setup.
- `firecrawl-build` to choose the right endpoint.
- Narrow `firecrawl-build-*` skills for implementation details.

Required build-path question: What should Firecrawl do in the product?

Use the answer to route to `/search`, `/scrape`, `/interact`, `/crawl`, or `/map`, then run one real Firecrawl request as a smoke test.

If there is no key yet, do Path C first.

## Path C: Account Authorization Or API Key

Use this when the human still needs to sign up, sign in, authorize
access, or obtain an API key.

If install ran with `--browser`, the human was already prompted to sign in. Check status before running this flow:

```powershell
npm run firecrawl:status
```

If a valid `FIRECRAWL_API_KEY` exists, skip this path.

For browser login:

```powershell
npm run firecrawl:login
```

For direct API key login:

```powershell
npm run firecrawl -- login --api-key fc-YOUR-API-KEY
```

Human sign-up/sign-in URL:

```text
https://www.firecrawl.dev/signin?view=signup&source=agent-suggested
```

If an agent needs the human to authorize an API key, use this flow.

Step 1: Generate auth parameters:

```bash
SESSION_ID=$(openssl rand -hex 32)
CODE_VERIFIER=$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n' | head -c 43)
CODE_CHALLENGE=$(printf '%s' "$CODE_VERIFIER" | openssl dgst -sha256 -binary | openssl base64 -A | tr '+/' '-_' | tr -d '=')
```

Step 2: Ask the human to open this URL:

```text
https://www.firecrawl.dev/cli-auth?code_challenge=$CODE_CHALLENGE&source=coding-agent#session_id=$SESSION_ID
```

If they already have a Firecrawl account, they will sign in and
authorize. If not, they will create one first and then authorize.

Step 3: Poll for the API key every 3 seconds:

```http
POST https://www.firecrawl.dev/api/auth/cli/status
Content-Type: application/json

{"session_id": "$SESSION_ID", "code_verifier": "$CODE_VERIFIER"}
```

Responses:

- `{"status": "pending"}`: keep polling.
- `{"status": "complete", "apiKey": "fc-...", "teamName": "..."}`: done.

Step 4: Save the key to local secret storage and continue:

```bash
echo "FIRECRAWL_API_KEY=fc-..." >> .env
```

## Path D: Use Firecrawl Without Installing Anything

Use this when the user does not want to install a CLI or skills package.
This works for both live web work and app integration, but still needs
an API key.

- Base URL: `https://api.firecrawl.dev/v2`
- Auth header: `Authorization: Bearer fc-YOUR_API_KEY`

Useful endpoints:

- `POST /search`: discover pages by query, returns results with optional full-page content.
- `POST /scrape`: extract clean markdown from a single URL.
- `POST /interact`: browser actions on live pages, including clicks, forms, and navigation.
- `POST /support/ask`: diagnose a failing Firecrawl call. Pass `{ question, jobId? }`; returns a prose `answer` plus machine-readable `fixParameters` to retry with. Auto-scoped to the team via the bearer key.
- `POST /support/docs-search`: answer Firecrawl docs questions. Pass `{ question }`; returns the answer plus citations to the docs pages used.

Documentation and references:

- API reference: `https://docs.firecrawl.dev`
- Skills repo: `https://github.com/firecrawl/skills`

## Common CLI Workflows

Scrape one page:

```powershell
npm run firecrawl -- scrape https://example.com --only-main-content -o .firecrawl/page.md
```

Search and scrape results:

```powershell
npm run firecrawl -- search "query" --scrape --scrape-formats markdown --limit 5 --pretty -o .firecrawl/search.json
```

Map a site:

```powershell
npm run firecrawl -- map https://example.com --json --pretty -o .firecrawl/map.json
```

Crawl a docs site with guardrails:

```powershell
npm run firecrawl -- crawl https://example.com/docs --limit 50 --max-depth 2 --wait --progress --pretty -o .firecrawl/crawl.json
```

Structured extraction:

```powershell
npm run firecrawl -- scrape https://example.com --format json --schema-file .firecrawl/schema.json --pretty -o .firecrawl/extract.json
```

Agent job:

```powershell
npm run firecrawl -- agent "Find pricing information" --urls https://example.com --wait --timeout 300 --pretty -o .firecrawl/agent.json
```

Docs-search:

```powershell
npm run firecrawl -- docs-search "How does Firecrawl handle JavaScript-heavy pages?" --pretty
```

Ask support about a failed job:

```powershell
npm run firecrawl -- ask "Why did this scrape fail?" --job-id JOB_ID --pretty
```

## Output Handling

- Single-format scrape output may be raw markdown or HTML.
- Multiple formats or `--json` return JSON.
- Use `--pretty` for human review and omit it for machine pipelines.
- Summarize important findings in chat instead of pasting large Firecrawl outputs.
