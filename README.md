# ai& Ops Agent — Data Center Incident Triage

An AI-powered operations agent that monitors data center alerts, performs automated incident triage, and provides intelligent escalation — built to demonstrate how agentic AI workflows can make infrastructure teams more productive.

Built as a proof of concept for [ai&](https://aiand.com) by Josef Gustafson.

## What it does

- **Real-time alert monitoring** — Simulates a live data center alert stream with correlated failure scenarios (thermal cascades, GPU failures, network partitions, storage degradation, power anomalies)
- **Autonomous triage agent** — An AI agent that classifies alerts, correlates related events, consults operational runbooks, creates incident reports, and escalates critical issues — all autonomously with full reasoning traces
- **Knowledge base Q&A** — RAG-powered search over 14 data center operations runbooks
- **Full observability** — Live agent reasoning traces via SSE, audit logging, incident tracking
- **Bilingual output** — Triage summaries generated in both English and Japanese (日本語)

## Quick start

```bash
git clone https://github.com/josefgustafson/aiand-ops-agent.git
cd aiand-ops-agent
cp .env.example .env
# Add your LLM API key to .env
docker compose up
# Open http://localhost:3000
```

Within 60 seconds you'll see live alerts streaming in, being triaged by the AI agent in real time.

## Model-agnostic by design

This system integrates with **any** LLM inference endpoint. ai&'s own models can be plugged in by changing a single environment variable:

```bash
# Use ai&'s own inference endpoint
LLM_MODEL=ai-and-model
LLM_API_BASE=https://inference.aiand.com/v1
```

The LLM client is a minimal OpenAI-compatible wrapper with **zero third-party LLM SDK dependencies**. This is a deliberate architectural choice — lightweight dependencies reduce supply chain attack surface (see: LiteLLM PyPI compromise, March 2026), which is critical for internal tooling that handles infrastructure credentials. Any OpenAI-compatible endpoint works out of the box, including:

- ai&'s own inference infrastructure
- OpenAI API
- Ollama (local models)
- vLLM / TGI self-hosted endpoints
- Any OpenAI-compatible proxy

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Browser (localhost:3000)               │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │  Live Alert  │  │   Triage     │  │   Knowledge    │  │
│  │  Feed + SSE  │  │   Detail +   │  │   Base Q&A     │  │
│  │              │  │   Agent Trace│  │   (RAG Chat)   │  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬────────┘  │
└─────────┼────────────────┼──────────────────┼────────────┘
          │ SSE            │ SSE/REST         │ REST
          ▼                ▼                  ▼
┌─────────────────────────────────────────────────────────┐
│                  FastAPI Backend (:8000)                  │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  Alert       │  │  Triage      │  │  Knowledge    │  │
│  │  Simulator   │  │  Agent       │  │  Base (RAG)   │  │
│  │  (asyncio)   │  │  (tool-use)  │  │  (ChromaDB)   │  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘  │
│         │                 │                   │          │
│         ▼                 ▼                   ▼          │
│  ┌─────────────────────────────────────────────────┐    │
│  │              SQLite Database                     │    │
│  │  alerts | incidents | escalations | audit_log   │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │         Minimal OpenAI-Compatible Client         │    │
│  │  (zero LLM SDK deps — configure any endpoint)   │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

Single Docker container. Everything runs in one process.

## Agent tool-use flow

The triage agent operates in an iterative tool-use loop:

1. **Receive alert** → Parse severity, category, component, metric data
2. **Query correlated alerts** → Search recent alerts on the same rack/host/category to detect cascading failures
3. **Look up host info** → Get hardware specs, status, and incident history
4. **Search runbooks** → Vector search over operational knowledge base for relevant procedures
5. **Classify and decide** → Determine if the alert is noise, requires acknowledgment, warrants an incident, or needs critical escalation
6. **Create incident** → If warranted, create a formal incident record with root cause and remediation steps
7. **Escalate** → If critical, trigger escalation via the appropriate channels

Each step is streamed in real time to the frontend via SSE, creating a live reasoning trace.

## Correlated failure scenarios

The simulator generates 5 realistic multi-step failure scenarios:

| Scenario | Alerts | Description |
|----------|--------|-------------|
| Thermal Cascade | 4 | CRAC failure → GPU throttling → training degradation |
| GPU Hardware Failure | 4 | ECC errors → GPU lost → NVLink errors → node unhealthy |
| Network Partition | 4 | Switch flapping → packet loss → nodes unreachable → training stalled |
| Storage Degradation | 4 | SMART warnings → I/O latency → checkpoint write failure |
| Power Anomaly | 4 | Voltage fluctuation → UPS engagement → load shedding → recovery |

The agent must determine which alerts are correlated — this is what makes the triage interesting.

## Why this exists

ai& operates next-generation data centers for AI infrastructure. This PoC demonstrates how an agentic AI workflow can:

1. **Reduce mean time to triage** for data center incidents
2. **Ensure consistent, runbook-compliant** incident response across shifts
3. **Surface correlated failure patterns** that human operators might miss during alert storms
4. **Provide institutional knowledge access** through natural language Q&A over operational runbooks

This is the kind of internal tooling the Applied AI Engineer role would build — AI that makes every ops team member more effective, regardless of their experience level.

## Tech stack

| Component | Technology |
|-----------|-----------|
| Backend | Python, FastAPI, asyncio |
| LLM Integration | Custom OpenAI-compatible client (zero LLM SDK dependencies) |
| Agent | Hand-rolled tool-use loop (no framework dependencies) |
| Knowledge Base | ChromaDB + sentence-transformers (all-MiniLM-L6-v2) |
| Database | SQLite via aiosqlite |
| Frontend | HTML + Tailwind CSS + vanilla JavaScript |
| Deployment | Docker Compose (single container) |

## Project structure

```
aiand-ops-agent/
├── README.md
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── backend/
│   ├── main.py              # FastAPI app, lifespan, route mounting
│   ├── config.py            # Settings from .env via pydantic-settings
│   ├── auth.py              # API key middleware
│   ├── db/
│   │   ├── database.py      # SQLite connection, schema, CRUD operations
│   │   ├── models.py        # Pydantic models for all entities
│   │   └── seed.py          # Seed hosts table with sample data
│   ├── simulator/
│   │   ├── engine.py        # Alert generation loop
│   │   ├── scenarios.py     # 5 correlated failure scenario definitions
│   │   └── components.py    # DC component definitions (hosts, racks, GPUs)
│   ├── agent/
│   │   ├── triage.py        # Main agent loop with step broadcasting
│   │   ├── tools.py         # Tool definitions and implementations
│   │   ├── prompts.py       # System prompts and tool schemas
│   │   └── parser.py        # Response parsing (tool calls, triage result)
│   ├── knowledge/
│   │   ├── rag.py           # ChromaDB setup, embed, search
│   │   ├── qa.py            # RAG Q&A endpoint logic
│   │   └── runbooks/        # 14 operational runbook documents
│   ├── llm/
│   │   └── client.py        # Minimal OpenAI-compatible client
│   ├── routes/
│   │   ├── alerts.py        # Alert endpoints
│   │   ├── incidents.py     # Incident endpoints
│   │   ├── knowledge.py     # RAG Q&A endpoint
│   │   ├── stream.py        # SSE streaming endpoints
│   │   ├── stats.py         # Dashboard stats
│   │   └── config.py        # Config read/update
│   └── sse/
│       └── broadcaster.py   # SSE pub/sub for alerts and agent steps
├── frontend/
│   └── index.html           # Single-file dashboard
└── data/                    # Created at runtime (gitignored)
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MODEL` | `gpt-4o-mini` | Model name for the LLM endpoint |
| `LLM_API_KEY` | — | API key for the LLM endpoint |
| `LLM_API_BASE` | `https://api.openai.com/v1` | Base URL for the LLM API |
| `OPS_AGENT_API_KEY` | `demo-key-change-me` | API key for write endpoints |
| `ALERT_INTERVAL_MIN` | `3` | Minimum seconds between alerts |
| `ALERT_INTERVAL_MAX` | `8` | Maximum seconds between alerts |
| `SCENARIO_PROBABILITY` | `0.3` | Probability of correlated scenario vs isolated alert |
| `DATABASE_PATH` | `data/ops_agent.db` | SQLite database file path |
| `CHROMA_PATH` | `data/chroma` | ChromaDB persistence directory |

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serve frontend dashboard |
| `GET` | `/api/stream/alerts` | SSE stream of live alerts |
| `GET` | `/api/stream/triage/{id}` | SSE stream of agent triage steps |
| `GET` | `/api/alerts` | List alerts (paginated, filterable) |
| `GET` | `/api/alerts/{id}` | Alert detail + triage history |
| `GET` | `/api/incidents` | List incidents |
| `GET` | `/api/incidents/{id}` | Incident detail |
| `GET` | `/api/escalations` | List escalations |
| `POST` | `/api/knowledge/ask` | RAG Q&A endpoint |
| `GET` | `/api/stats` | Dashboard statistics |
| `GET` | `/api/config` | Current configuration |
| `POST` | `/api/config` | Update configuration (requires API key) |
| `GET` | `/health` | Health check |

## Local development (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API key
uvicorn backend.main:app --reload --port 8000
# Open http://localhost:8000
```
