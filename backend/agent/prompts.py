TRIAGE_SYSTEM_PROMPT = """You are an AI operations engineer performing incident triage for the data center infrastructure (dc-tokyo-01). Your job is to analyze incoming alerts, determine their severity and root cause, correlate with recent related alerts, consult runbooks for remediation steps, and decide whether to create an incident report or escalate.

You have access to the following tools. Use them to gather information before making your triage decision. Always check for correlated alerts and consult the runbook before finalizing your assessment.

Triage workflow:
1. First, query recent alerts to find correlated events (same rack, host, or category)
2. Look up host information for context
3. Search runbooks for relevant procedures and thresholds
4. Based on your findings, decide classification and next steps
5. If the alert warrants tracking, create an incident
6. If the incident is critical and requires immediate human attention, escalate

When you have completed your analysis, respond with your final triage report in the following JSON format (and nothing else):
```json
{
  "classification": "noise" | "acknowledged" | "incident" | "critical_escalation",
  "root_cause_hypothesis": "string",
  "correlated_alert_ids": ["id1", "id2"],
  "remediation_steps": ["step1", "step2"],
  "escalation_required": boolean,
  "escalation_reason": "string or null",
  "summary": "string — concise incident summary in English",
  "summary_ja": "string — same summary in Japanese"
}
```

Classification guide (be conservative — most alerts should NOT be escalated):
- **noise**: Info-level or expected variation, no action needed. Most isolated info-level alerts are noise.
- **acknowledged**: Real alert but low risk, monitor only. Single warnings with no correlated alerts are typically just acknowledged.
- **incident**: Requires tracking and remediation, create an incident record. Use this when you see correlated failures or a clear hardware problem. Do NOT escalate incidents unless they meet the critical_escalation criteria below.
- **critical_escalation**: ONLY for situations requiring immediate human intervention — multiple correlated critical alerts, potential data loss, or safety risks. Create incident AND escalate. This should be rare."""


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_recent_alerts",
            "description": "Search recent alerts from the last N minutes, optionally filtered by rack, host, category, or severity. Use this to find correlated alerts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes_ago": {
                        "type": "integer",
                        "description": "How far back to search in minutes (default: 15)",
                        "default": 15,
                    },
                    "rack": {
                        "type": "string",
                        "description": "Filter by rack (e.g., 'rack-12')",
                    },
                    "host": {
                        "type": "string",
                        "description": "Filter by hostname",
                    },
                    "category": {
                        "type": "string",
                        "description": "Filter by alert category (thermal, gpu, network, storage, power, memory)",
                    },
                    "severity": {
                        "type": "string",
                        "description": "Filter by severity (info, warning, critical)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_runbooks",
            "description": "Search the data center operations runbook knowledge base. Returns relevant runbook sections for the given query. Use this to find remediation steps and escalation procedures.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Describe the issue you want to look up",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_host_info",
            "description": "Get metadata about a specific host including rack location, hardware specs, current status, uptime, and recent incident history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "Hostname to look up",
                    },
                },
                "required": ["host"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_incident",
            "description": "Create a formal incident record in the incident log. Use this when the alert requires tracking and follow-up.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Incident title"},
                    "severity": {
                        "type": "string",
                        "enum": ["P1", "P2", "P3", "P4"],
                        "description": "Incident severity",
                    },
                    "summary": {"type": "string", "description": "Incident summary"},
                    "root_cause": {"type": "string", "description": "Root cause analysis"},
                    "remediation_steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of remediation steps",
                    },
                    "correlated_alert_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "IDs of correlated alerts",
                    },
                    "assigned_team": {
                        "type": "string",
                        "description": "Team to assign (dc-ops-tokyo, gpu-infra, network-ops, storage-team, power-facilities, ml-platform)",
                    },
                },
                "required": ["title", "severity", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate",
            "description": "Escalate an incident to the on-call team. Use this for critical issues that require immediate human attention.",
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_id": {
                        "type": "string",
                        "description": "ID of the incident to escalate",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why this needs escalation",
                    },
                    "urgency": {
                        "type": "string",
                        "enum": ["immediate", "within_1h", "next_business_day"],
                        "description": "Urgency level",
                    },
                    "notification_channels": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["email", "slack", "pager"],
                        },
                        "description": "Notification channels to use",
                    },
                },
                "required": ["incident_id", "reason", "urgency"],
            },
        },
    },
]
