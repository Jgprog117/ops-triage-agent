# Ops Triage Agent

An autonomous AI agent that monitors data center alerts, triages incidents, and escalates critical issues — replacing manual on-call toil with a tool-use loop that reasons, correlates, and acts in real time.

Internal AI tooling that keeps infrastructure teams focused on what matters: an agent that handles the repetitive alert noise so engineers can focus on the hard problems.

![Architecture](docs/architecture.svg)

## Quick start

```bash
cp .env.example .env
# Set LLM_PROVIDER, LLM_MODEL, and LLM_API_KEY in .env
docker compose up --build
# Open http://localhost:3000
```

Or without Docker:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env
uvicorn backend.main:app --port 8000
```

### LLM providers

Set `LLM_PROVIDER` in `.env`:

```bash
# Anthropic
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6-latest
LLM_API_KEY=sk-ant-...

# OpenAI
LLM_PROVIDER=openai
LLM_MODEL=gpt-4.1-mini
LLM_API_KEY=sk-...

```

## How the agent works

![Agent flow](docs/agent-flow.svg)

The triage agent runs a tool-use loop: it receives an alert, gathers context by calling tools (query correlated alerts, look up host info, search runbooks), then decides on a classification and next steps. Each step is streamed to the dashboard via SSE.

**Tools available to the agent:**

| Tool | Purpose |
|------|---------|
| `query_recent_alerts` | Find correlated alerts by rack, host, category |
| `get_host_info` | Hardware specs, status, incident history |
| `search_runbooks` | RAG search over 14 operational runbooks |
| `create_incident` | Create a tracked incident record |
| `escalate` | Escalate to on-call with webhook notification |

**Classifications:** noise, acknowledged, incident, critical_escalation

## Simulated failure scenarios

The alert simulator generates 5 realistic multi-step failure patterns:

- **Thermal cascade** — CRAC failure triggers GPU throttling and training degradation
- **GPU hardware failure** — ECC errors escalate to NVLink failures and node drain
- **Network partition** — Switch flapping causes packet loss and training stalls
- **Storage degradation** — SMART warnings lead to checkpoint write failures
- **Power anomaly** — Voltage fluctuation triggers UPS engagement and load shedding

The agent must determine which alerts are correlated across these scenarios.

## Configuration

See [`.env.example`](.env.example) for all options. Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `openai` |
| `LLM_MODEL` | `claude-sonnet-4-6-latest` | Model name |
| `ALERT_INTERVAL_MIN` | `90` | Min seconds between alerts |
| `WEBHOOK_URL` | — | Outgoing webhook for escalations (HMAC-signed) |

## Testing

```bash
python -m pytest tests/ -v
```

68 tests covering the parser, Pydantic models, scenario structure, RAG chunking, and LLM client (including Anthropic format conversion).

## Design principles

- **Model-agnostic** — swap LLM providers (or plug in your own inference endpoint) without touching agent logic
- **Observable** — every reasoning step is streamed to the dashboard; audit logs capture all tool calls and decisions
- **Evaluation-aware** — see [EVALUATION.md](EVALUATION.md) for the triage accuracy assessment framework
