TRIAGE_SYSTEM_PROMPT = """You are an AI operations engineer performing incident triage for the data center infrastructure (dc-tokyo-01). Your job is to analyze incoming alerts, determine their severity and root cause, correlate with recent related alerts, consult runbooks for remediation steps, and decide whether to create an incident report or escalate.

You have access to the following tools. Use them to gather information before making your triage decision. Always check for correlated alerts and consult the runbook before finalizing your assessment.

Triage workflow:
1. Query recent alerts in the same rack/host/category to find correlated events. If any of them already have an `open_incident_id` set, the same scenario is already being tracked — go to step 6.
2. Call `find_open_incidents` for the alert's rack/host/category. If a relevant open incident exists, **attach this alert to it instead of creating a new one**.
3. Look up host information for context (only if you need hardware specs or recent incident history).
4. Search runbooks for relevant procedures and thresholds.
5. Decide classification using the rules below. Most alerts are NOT critical_escalation.
6. Action:
   - If an open incident already covers this alert: call `attach_to_incident` and reuse its escalation status. Do NOT create a duplicate incident. Do NOT re-escalate an already-escalated incident.
   - Otherwise, if the alert warrants tracking: call `create_incident` once.
   - Only call `escalate` if the alert meets the strict critical_escalation criteria below AND the incident is not already escalated.

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
- **noise**: Single info-level alert with no correlated alerts within 15 minutes on the same host or rack. Expected metric variation, no action needed.
- **acknowledged**: Single warning with 0-1 correlated alerts and no critical indicators. Real alert but low risk — monitor only.
- **incident**: 2+ correlated warnings or criticals in the same rack within 15 minutes, OR a clear hardware problem (ECC errors, disk SMART warnings, NVLink failures). Create an incident record. Do NOT escalate unless criteria below are met.
- **critical_escalation**: ONLY when: (a) 3+ correlated critical alerts in the same rack within 30 minutes, OR (b) any alert indicating potential data loss (uncorrectable ECC, RAID degradation, checkpoint write failures), OR (c) thermal readings above 95°C, OR (d) safety-related power anomalies on multiple PDUs. Create incident AND escalate."""


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_recent_alerts",
            "description": "Search recent alerts from the last N minutes, optionally filtered by rack, host, category, or severity. Use this to find correlated alerts. The response includes an 'open_incident_id' field on each alert — if any of the returned alerts have one set, the same scenario is already being tracked and you should call find_open_incidents next, NOT create_incident.",
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
                    "exclude_id": {
                        "type": "string",
                        "description": "Alert id to exclude from results (typically the alert you are currently triaging)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_open_incidents",
            "description": "Find open incidents whose primary alert matches the given rack, host, or category within the last hour. ALWAYS call this before create_incident — if a matching open incident exists, attach this alert to it with attach_to_incident instead of creating a duplicate. Returns an empty list when there is no match (in which case create_incident is appropriate).",
            "parameters": {
                "type": "object",
                "properties": {
                    "rack": {
                        "type": "string",
                        "description": "Rack to look for open incidents in (e.g., 'rack-12')",
                    },
                    "host": {
                        "type": "string",
                        "description": "Host to look for open incidents on",
                    },
                    "category": {
                        "type": "string",
                        "description": "Alert category to look for (thermal, gpu, network, storage, power, memory)",
                    },
                    "minutes_ago": {
                        "type": "integer",
                        "description": "How far back to look in minutes (default: 60)",
                        "default": 60,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "attach_to_incident",
            "description": "Attach the alert you are triaging to an existing open incident. Use this whenever find_open_incidents returns a matching incident — it is the correct action for any follow-on alert in an active scenario. After calling this, do NOT call create_incident, and do NOT call escalate (the existing incident's escalation status is reused).",
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_id": {
                        "type": "string",
                        "description": "The id of the existing open incident (e.g., 'INC-AB12CD34EF56')",
                    },
                    "alert_id": {
                        "type": "string",
                        "description": "The id of the alert being triaged",
                    },
                },
                "required": ["incident_id", "alert_id"],
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
            "description": (
                "Create a NEW incident record. Call this only after find_open_incidents "
                "has returned no matching incident. DO NOT call create_incident when: "
                "(a) any alert returned by query_recent_alerts has an open_incident_id set, "
                "(b) find_open_incidents returned a matching incident — use attach_to_incident "
                "instead, or (c) the alert is an isolated info-level event (those should be "
                "classified as 'noise' with no incident at all)."
            ),
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
                        "description": "IDs of correlated alerts (include the alert being triaged)",
                    },
                    "primary_alert_id": {
                        "type": "string",
                        "description": "The id of the alert being triaged. This becomes the canonical link for future dedupe lookups.",
                    },
                    "assigned_team": {
                        "type": "string",
                        "description": "Team to assign (dc-ops-tokyo, gpu-infra, network-ops, storage-team, power-facilities, ml-platform)",
                    },
                },
                "required": ["title", "severity", "summary", "primary_alert_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate",
            "description": (
                "Page the on-call team. This wakes a human up — use it only when "
                "the incident genuinely requires immediate attention. "
                "DO NOT escalate when: "
                "(1) the alert is an isolated warning with no correlated alerts — "
                "use the 'acknowledged' classification instead; "
                "(2) the alert is a single-PDU power fluctuation that may recover "
                "(power escalation requires anomalies on MULTIPLE PDUs); "
                "(3) the alert is a SMART pre-failure warning without correlated I/O "
                "latency degradation — that is an 'incident', not an escalation; "
                "(4) the incident has already been escalated — the tool will refuse "
                "and you should not retry; "
                "(5) you just attached this alert to an existing open incident — its "
                "escalation status is already set."
            ),
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
