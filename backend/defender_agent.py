"""Autonomous Microsoft Defender security agent.

Polls Graph Security API for Defender alerts every N seconds (default 120).
Classifies each new alert against a decision rule table and dispatches safe
remediation actions through the existing user_admin_jobs and security_device_jobs
queues.  Every decision — including skips — is logged durably in
defender_agent_store for operator review.

Safety tiers
------------
T1 (immediate)  — Revoke sessions, device sync.  Auto-executed on first cycle.
T2 (delayed)    — Disable sign-in.  Queued with not_before_at = now +
                  tier2_delay_minutes.  Operator can cancel before window passes.
T3 (recommend)  — Device wipe / retire.  Logged only; requires human approval
                  via the /api/azure/security/defender-agent/decisions/{id}/approve
                  endpoint.
Skip            — Alert below min_severity or category not in rule table.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from config import (
    AZURE_DEFENDER_AGENT_POLL_SECONDS,
    DEFENDER_AGENT_MAX_JOBS_PER_CYCLE,
    DEFENDER_AGENT_TEAMS_NOTIFY_T1,
    DEFENDER_AGENT_TEAMS_NOTIFY_T2,
    DEFENDER_AGENT_TEAMS_WEBHOOK_URL,
)

logger = logging.getLogger(__name__)

_AGENT_EMAIL = "defender-agent@system.internal"
_AGENT_NAME = "Defender Autonomous Agent"

# ---------------------------------------------------------------------------
# Severity ordering
# ---------------------------------------------------------------------------

_SEV_ORDER: dict[str, int] = {
    "informational": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
    "unknown": 0,
}

# ---------------------------------------------------------------------------
# Time-gating helpers (Pacific Time)
# ---------------------------------------------------------------------------


def _is_off_hours_pt() -> bool:
    """Return True if the current moment is outside business hours in Pacific Time.

    Business hours: Monday–Friday, 08:00–17:00 US/Pacific (DST-aware).
    Weekends and outside 08:00–17:00 are considered off-hours.
    Rules tagged with ``off_hours_escalate=True`` use this to automatically
    upgrade from T2-queue to T1-execute when no operator is available to cancel.
    """
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
        tz: Any = ZoneInfo("America/Los_Angeles")
    except Exception:
        # Fallback: UTC-8 (no DST — conservative, slightly wrong for PDT)
        tz = timezone(timedelta(hours=-8))

    now_pt = datetime.now(tz)
    weekday = now_pt.weekday()  # 0=Mon … 6=Sun
    hour = now_pt.hour
    if weekday >= 5:          # Saturday or Sunday
        return True
    return hour < 8 or hour >= 17  # before 08:00 or at/after 17:00


# ---------------------------------------------------------------------------
# Decision rule table
# (evaluated top-to-bottom; first match wins)
# ---------------------------------------------------------------------------

_RULES: list[dict[str, Any]] = [
    # T1 — device sync
    {
        "title_keywords": ("antivirus", "signature", "out of date", "not reporting"),
        "service_source_contains": ("defender", "endpoint", "intune"),
        "min_severity": "high",
        "tier": 1,
        "decision": "execute",
        "action_type": "device_sync",
        "reason": "Defender reported antivirus/signature issue on device; sync to force policy refresh.",
    },
    # T1 — revoke sessions (fast, reversible)
    {
        "title_keywords": (
            "suspicious signin", "unfamiliar features", "impossible travel",
            "anonymous ip", "malicious ip", "malware ip",
            "atypical travel", "unfamiliar sign-in",
        ),
        "min_severity": "high",
        "tier": 1,
        "decision": "execute",
        "action_type": "revoke_sessions",
        "reason": "Defender detected suspicious identity activity; revoking active sessions.",
    },
    # T2 — disable sign-in (queued with delay; escalates to T1 off-hours)
    {
        "title_keywords": (
            "password spray", "brute force", "unusual volume",
            "suspicious api", "suspicious mailbox", "suspicious inbox",
        ),
        "min_severity": "high",
        "tier": 2,
        "decision": "queue",
        "action_type": "disable_sign_in",
        "off_hours_escalate": True,
        "reason": "Defender detected credential or mailbox attack pattern; sign-in disable queued with cancellation window.",
    },
    {
        "title_keywords": ("credential harvesting", "credential access"),
        "min_severity": "critical",
        "tier": 2,
        "decision": "queue",
        "action_type": "disable_sign_in",
        "reason": "Critical credential harvesting alert; sign-in disable queued with cancellation window.",
    },
    # T2 — lateral movement
    {
        "title_keywords": ("lateral movement", "pass the hash", "pass the ticket", "overpass the hash"),
        "min_severity": "high",
        "tier": 2,
        "decision": "queue",
        "action_type": "disable_sign_in",
        "reason": "Lateral movement technique detected; sign-in disable queued with cancellation window.",
    },
    # T1 — MDO confirmed malicious URL click (RC-6) — takes priority over generic phishing T2
    {
        "title_keywords": (
            "malicious url click", "clicked malicious url", "url click blocked",
            "user clicked on malicious", "confirmed malicious click",
            "clicks on a malicious", "url detonation",
        ),
        "service_source_contains": ("office365", "mdo", "microsoftdefenderforoffice"),
        "min_severity": "high",
        "tier": 1,
        "decision": "execute",
        "action_type": "revoke_sessions",
        "reason": "MDO confirmed malicious URL click (high severity); revoking sessions immediately.",
    },
    # T2 — phishing / malicious link
    {
        "title_keywords": ("phishing", "suspicious email", "suspicious link click", "malicious url"),
        "min_severity": "high",
        "tier": 2,
        "decision": "queue",
        "action_type": "disable_sign_in",
        "reason": "Phishing or malicious link activity detected; sign-in disable queued with cancellation window.",
    },
    # T2 — MFA fatigue (escalates to T1 off-hours — attacker persistence exploit)
    {
        "title_keywords": ("mfa fatigue", "mfa spam", "suspicious mfa", "push notification flooding"),
        "min_severity": "medium",
        "tier": 2,
        "decision": "queue",
        "action_type": "disable_sign_in",
        "off_hours_escalate": True,
        "reason": "MFA fatigue attack pattern detected; sign-in disable queued with cancellation window.",
    },
    # T2 — AiTM / session hijacking → revoke sessions (escalates to T1 off-hours)
    {
        "title_keywords": (
            "adversary-in-the-middle", "aitm", "phishing site",
            "suspicious activity network", "session hijacking",
            "token theft via aitm", "evilginx",
        ),
        "min_severity": "medium",
        "tier": 2,
        "decision": "queue",
        "action_type": "revoke_sessions",
        "off_hours_escalate": True,
        "reason": "AiTM phishing / session-hijacking detected; revoking active sessions pending investigation.",
    },
    # T1/T2 — anomalous token activity (RC-7)
    {
        "title_keywords": (
            "anomalous token", "token anomaly", "unusual token", "suspicious token",
            "token issuer anomaly", "atypical token",
        ),
        "min_severity": "high",
        "tier": 1,
        "decision": "execute",
        "action_type": "revoke_sessions",
        "reason": "Anomalous token activity (high severity); revoking active sessions immediately.",
    },
    {
        "title_keywords": (
            "anomalous token", "token anomaly", "unusual token", "suspicious token",
            "token issuer anomaly", "atypical token",
        ),
        "min_severity": "medium",
        "tier": 2,
        "decision": "queue",
        "action_type": "disable_sign_in",
        "off_hours_escalate": True,
        "reason": "Anomalous token activity (medium severity); sign-in disable queued with cancellation window.",
    },
    # T2 — suspicious OAuth / app consent
    {
        "title_keywords": ("suspicious oauth", "risky oauth", "oauth application", "app granted permissions"),
        "min_severity": "high",
        "tier": 2,
        "decision": "queue",
        "action_type": "disable_sign_in",
        "reason": "Suspicious OAuth app consent detected; sign-in disable queued with cancellation window.",
    },
    # T2 — MCAS / Defender for Cloud Apps behavioral anomaly → account lockout (RC-8)
    {
        "title_keywords": (
            "suspicious cloud activity", "mass download", "unusual admin activity",
            "cloud app anomaly", "suspicious app access", "activity from anonymous ip",
            "activity from suspicious ip", "ransomware activity in cloud",
            "cloud storage data exfiltration", "unusual file download",
        ),
        "service_source_contains": ("cloudappsecurity", "microsoftcloudappsecurity", "defenderforcloud"),
        "min_severity": "medium",
        "tier": 2,
        "decision": "queue",
        "action_type": "account_lockout",
        "reason": "MCAS/Defender for Cloud Apps behavioral anomaly; account lockout (revoke + disable) queued.",
    },
    # T1 — cryptominer (non-destructive policy sync sufficient)
    {
        "title_keywords": ("bitcoin miner", "cryptominer", "coinminer", "crypto miner"),
        "min_severity": "medium",
        "tier": 1,
        "decision": "execute",
        "action_type": "device_sync",
        "reason": "Cryptominer detected on device; sync to force AV/policy update.",
    },
    # T3 — recommend only (irreversible)
    {
        "title_keywords": ("ransomware",),
        "min_severity": "critical",
        "tier": 3,
        "decision": "recommend",
        "action_type": "device_wipe",
        "reason": "Ransomware activity detected on device; wipe recommended — requires human approval.",
    },
    {
        "title_keywords": ("malicious activity", "active malware"),
        "min_severity": "high",
        "tier": 2,
        "decision": "queue",
        "action_type": "isolate_device",
        "reason": "Active malware confirmed on device; isolating to prevent lateral spread (preserves for forensics).",
    },
    # T3 — data exfiltration
    {
        "title_keywords": ("data exfiltration", "unusual data transfer", "mass download", "sensitive file"),
        "min_severity": "high",
        "tier": 3,
        "decision": "recommend",
        "action_type": "device_retire",
        "reason": "Data exfiltration pattern detected; device retire recommended — requires human approval.",
    },
    # T3 — persistence mechanisms
    {
        "title_keywords": (
            "persistence", "scheduled task", "startup folder", "registry run key",
            "suspicious service", "autorun entry", "lsa notification", "boot execute",
            "auto start extensibility", "winlogon helper", "image file execution options",
        ),
        "min_severity": "high",
        "tier": 3,
        "decision": "recommend",
        "action_type": "device_retire",
        "reason": "Persistence mechanism detected on device; retire recommended — requires human approval.",
    },
    # T2 — C2 communication → isolate (was T3 retire; isolation is better first response)
    {
        "title_keywords": ("command and control", "c2 communication", "beaconing"),
        "min_severity": "high",
        "tier": 2,
        "decision": "queue",
        "action_type": "isolate_device",
        "reason": "C2/beaconing detected; isolating device to cut attacker network access.",
    },
    # T2 — ransomware/wipers → isolate immediately to prevent spread
    {
        "title_keywords": ("ransomware", "locker", "cryptolocker", "ryuk", "lockbit",
                           "wiper", "petya", "sodinokibi", "conti"),
        "min_severity": "high",
        "tier": 2,
        "decision": "queue",
        "action_type": "isolate_device",
        "reason": "Ransomware/wiper detected; isolating device to prevent encryption spread.",
    },
    # T2 — backdoors and RATs → isolate to cut persistence channel
    {
        "title_keywords": ("backdoor", "rootkit", "remote access trojan", "rat implant"),
        "min_severity": "high",
        "tier": 2,
        "decision": "queue",
        "action_type": "isolate_device",
        "reason": "Backdoor/RAT implant detected; isolating device to cut persistence channel.",
    },
    # T1 — malware signature detected → trigger AV scan (non-destructive first response)
    {
        "title_keywords": ("malware detected", "trojan detected", "virus detected",
                           "spyware detected", "suspicious file detected"),
        "min_severity": "medium",
        "tier": 1,
        "decision": "execute",
        "action_type": "run_av_scan",
        "reason": "Potential malware signature detected; triggering full AV scan.",
    },
    # T1 — suspicious process/exploit → AV scan to confirm threat
    {
        "title_keywords": ("suspicious process", "malicious process", "exploit attempt",
                           "shellcode", "powershell obfusc"),
        "min_severity": "high",
        "tier": 1,
        "decision": "execute",
        "action_type": "run_av_scan",
        "reason": "Suspicious process/exploit activity detected; triggering AV scan to confirm threat.",
    },
    # T3 — privilege escalation / credential dumping → restrict app execution
    {
        "title_keywords": ("privilege escalation", "token theft", "credential dumping",
                           "mimikatz", "dcsync", "golden ticket", "silver ticket"),
        "min_severity": "high",
        "tier": 3,
        "decision": "recommend",
        "action_type": "restrict_app_execution",
        "reason": "Active credential/privilege escalation attack detected; app execution restriction recommended.",
    },
    # T2 — forensic investigation requested → collect investigation package
    {
        "title_keywords": ("investigation package", "forensic collection"),
        "min_severity": "high",
        "tier": 2,
        "decision": "queue",
        "action_type": "collect_investigation_package",
        "reason": "Complex attack pattern detected; collecting forensic investigation package.",
    },
    # --- Email / Collaboration threats ---
    # T1 — HIGH-severity inbox manipulation → revoke sessions immediately (RC-20 upgrade)
    {
        "title_keywords": (
            "inbox rule", "mailbox forwarding", "email forwarding rule",
            "suspicious forwarding", "auto-forward", "suspicious inbox manipulation",
        ),
        "min_severity": "high",
        "tier": 1,
        "decision": "execute",
        "action_type": "revoke_sessions",
        "reason": "High-severity inbox manipulation detected; revoking sessions immediately to cut attacker access.",
    },
    # T2 — inbox rule manipulation / email forwarding abuse (medium severity; escalates T1 off-hours)
    {
        "title_keywords": (
            "inbox rule", "mailbox forwarding", "email forwarding rule",
            "suspicious forwarding", "auto-forward", "suspicious inbox manipulation",
        ),
        "min_severity": "medium",
        "tier": 2,
        "decision": "queue",
        "action_type": "disable_sign_in",
        "off_hours_escalate": True,
        "reason": "Attacker-created inbox rule or forwarding detected; disabling sign-in to cut persistent access.",
    },
    # T2 — BEC / email impersonation (escalates to T1 off-hours)
    {
        "title_keywords": (
            "business email compromise", "bec attack", "email impersonation",
            "account impersonation", "lookalike domain",
        ),
        "min_severity": "high",
        "tier": 2,
        "decision": "queue",
        "action_type": "disable_sign_in",
        "off_hours_escalate": True,
        "reason": "Business email compromise / impersonation detected; disabling sign-in pending investigation.",
    },
    # T1 — email-delivered malware / phishing link clicked
    {
        "title_keywords": (
            "email messages containing malicious", "malware campaign detected after delivery",
            "phishing click", "user clicked phishing", "malicious attachment opened",
        ),
        "min_severity": "medium",
        "tier": 1,
        "decision": "execute",
        "action_type": "revoke_sessions",
        "reason": "Email-delivered malware or phishing link clicked; revoking sessions immediately.",
    },
    # --- Endpoint technique gaps ---
    # T1 — process injection / code injection (title OR category match)
    {
        "title_keywords": (
            "process injection", "code injection", "process hollowing",
            "dll injection", "reflective dll", "memory injection",
        ),
        "category_keywords": ("Exploitation",),
        "min_severity": "high",
        "tier": 1,
        "decision": "execute",
        "action_type": "start_investigation",
        "reason": "Process/code injection technique detected; triggering MDE automated investigation.",
    },
    # T2 — DLL hijacking / side-loading
    {
        "title_keywords": (
            "dll hijacking", "dll side-loading", "dll planting",
            "dll search order hijacking", "dll preloading",
        ),
        "min_severity": "high",
        "tier": 2,
        "decision": "queue",
        "action_type": "start_investigation",
        "reason": "DLL hijacking/side-loading technique detected; investigation queued.",
    },
    # T2 — WMI / DCOM / PSExec lateral movement
    {
        "title_keywords": (
            "wmi lateral movement", "dcom lateral movement", "suspicious wmi",
            "wmi persistence", "psexec", "remote execution via wmi",
        ),
        "min_severity": "high",
        "tier": 2,
        "decision": "queue",
        "action_type": "isolate_device",
        "reason": "WMI/DCOM/PSExec lateral movement detected; isolating device to contain spread.",
    },
    # T1 — malicious Office macro / script
    {
        "title_keywords": (
            "malicious macro", "suspicious macro", "malicious office",
            "vba macro", "office document malware", "malicious script in office",
        ),
        "min_severity": "medium",
        "tier": 1,
        "decision": "execute",
        "action_type": "run_av_scan",
        "reason": "Malicious Office macro/script detected; triggering full AV scan.",
    },
    # T1 — malicious browser extension / modifier
    {
        "title_keywords": (
            "malicious browser extension", "browser modifier",
            "browser plugin malware", "browser hijack", "adware detected",
        ),
        "min_severity": "medium",
        "tier": 1,
        "decision": "execute",
        "action_type": "run_av_scan",
        "reason": "Malicious browser extension/modifier detected; triggering full AV scan.",
    },
    # --- Reconnaissance / discovery ---
    # T2 — network scan / port scan / recon
    {
        "title_keywords": (
            "network scan", "port scan", "port scanning", "network reconnaissance",
            "network enumeration", "host discovery",
        ),
        "min_severity": "medium",
        "tier": 2,
        "decision": "queue",
        "action_type": "collect_investigation_package",
        "reason": "Network reconnaissance/scanning detected; collecting forensic package for analysis.",
    },
    # T2 — LDAP / account enumeration / user discovery
    {
        "title_keywords": (
            "ldap enumeration", "account enumeration", "directory enumeration",
            "user discovery", "group enumeration", "active directory reconnaissance",
        ),
        "min_severity": "medium",
        "tier": 2,
        "decision": "queue",
        "action_type": "collect_investigation_package",
        "reason": "Directory/account enumeration detected; collecting investigation package.",
    },
    # --- High-impact CVE exploitation ---
    # T2 — named critical exploits → isolate immediately
    {
        "title_keywords": (
            "proxyshell", "proxylogon", "log4shell", "log4j",
            "eternalblue", "printspooler", "follina", "zerologon",
            "exchange exploitation", "rce via", "remote code execution via",
        ),
        "min_severity": "high",
        "tier": 2,
        "decision": "queue",
        "action_type": "isolate_device",
        "reason": "High-impact CVE exploitation detected; isolating device immediately.",
    },
    # T3 — confirmed account compromise → recommend password reset
    {
        "title_keywords": (
            "account compromise", "credential compromised", "account takeover",
            "stolen credentials used", "token replay", "session token abuse",
        ),
        "min_severity": "high",
        "tier": 3,
        "decision": "recommend",
        "action_type": "reset_password",
        "reason": "Confirmed account compromise; password reset recommended — requires human approval.",
    },
    # --- Red Canary parity rules ---
    # T1 — active malicious file execution → stop process and quarantine file immediately
    {
        "title_keywords": (
            "malicious file", "file quarantine", "malware executed",
            "ransomware executed", "trojan executed", "malicious executable",
        ),
        "min_severity": "high",
        "tier": 1,
        "decision": "execute",
        "action_type": "stop_and_quarantine_file",
        "reason": "Active malicious file execution detected; stopping process and quarantining file.",
    },
    # T1 — fileless / multi-stage / supply-chain → trigger MDE automated investigation
    {
        "title_keywords": (
            "living off the land", "lolbas", "fileless malware",
            "multi-stage attack", "advanced persistent threat", "apt activity",
        ),
        "min_severity": "high",
        "tier": 1,
        "decision": "execute",
        "action_type": "start_investigation",
        "reason": "Complex/fileless attack pattern; triggering automated MDE investigation.",
    },
    # T1 — supply chain attack → trigger investigation
    {
        "title_keywords": (
            "supply chain", "dependency confusion", "package tampering",
            "software supply chain",
        ),
        "min_severity": "high",
        "tier": 1,
        "decision": "execute",
        "action_type": "start_investigation",
        "reason": "Supply chain attack pattern detected; triggering MDE automated investigation.",
    },
    # T2 — known malicious IOC (IP/domain/C2 infrastructure) → block indicator tenant-wide
    {
        "title_keywords": (
            "known malicious ip", "blocked ip communication",
            "malicious domain", "known c2 infrastructure",
            "threat intelligence match", "known bad indicator",
        ),
        "min_severity": "medium",
        "tier": 2,
        "decision": "queue",
        "action_type": "create_block_indicator",
        "reason": "Confirmed malicious IOC detected; blocking indicator tenant-wide.",
    },
    # T2 — known malware file hash → block indicator tenant-wide
    {
        "title_keywords": (
            "known malware hash", "blocked file hash",
            "file reputation", "known malicious file",
        ),
        "min_severity": "medium",
        "tier": 2,
        "decision": "queue",
        "action_type": "create_block_indicator",
        "reason": "Known malicious file hash detected; creating tenant-wide block indicator.",
    },
    # T2 — RC Containment: confirmed active attacker on endpoint + identity component
    # Composite: isolate device AND revoke sessions simultaneously
    {
        "title_keywords": (
            "hands-on-keyboard", "interactive attacker", "active incident",
            "active breach", "attacker in session", "confirmed attacker activity",
            "human operated attack", "operator activity detected",
        ),
        "min_severity": "high",
        "tier": 2,
        "decision": "queue",
        "action_types": ["isolate_device", "revoke_sessions"],
        "reason": "RC Containment: active attacker presence confirmed; isolating endpoint + revoking sessions simultaneously.",
    },
    # T2 — RC Full Containment: critical severity active exploitation with identity component
    # Composite: isolate device + revoke sessions + disable sign-in
    {
        "title_keywords": (
            "ransomware encryption in progress", "active encryption",
            "critical active exploitation", "confirmed active compromise",
            "critical ransomware", "mass encryption detected",
        ),
        "min_severity": "critical",
        "tier": 2,
        "decision": "queue",
        "action_types": ["isolate_device", "revoke_sessions", "disable_sign_in"],
        "reason": "RC Full Containment: critical active attack; isolating endpoint + full account lockout queued.",
    },
    # T2 — known threat actor families → isolate endpoint (RC-17)
    {
        "title_keywords": (
            "qbot", "qakbot", "gamarue", "andromeda botnet",
            "socgholish", "fakeupdates", "impacket",
            "chromeloader", "raspberry robin", "charcoal stork", "smashjacker",
        ),
        "min_severity": "medium",
        "tier": 2,
        "decision": "queue",
        "action_type": "isolate_device",
        "reason": "Known threat actor family (RC-17) detected on endpoint; isolating device to contain spread.",
    },
    # --- Catch-all (MUST remain last) ---
    # No title_keywords / category_keywords = universal match for any alert that
    # didn't match a specific rule above. T3 recommend so a human reviews it.
    {
        "min_severity": "high",
        "tier": 3,
        "decision": "recommend",
        "action_type": "start_investigation",
        "reason": "Unclassified high/critical alert; manual review and MDE investigation recommended.",
    },
]


def _classify_alert(alert: dict[str, Any], min_severity: str) -> tuple[int | None, str, list[str], str]:
    """Return (tier, decision_type, action_types, reason).

    decision_type: "execute" | "queue" | "recommend" | "skip"
    action_types:  list of action type strings (composite rules have >1; empty for skip)
    """
    severity = (alert.get("severity") or "unknown").lower()
    title = (alert.get("title") or "").lower()
    service_source = (alert.get("serviceSource") or "").lower()

    # Reject alerts below operator-configured floor
    if _SEV_ORDER.get(severity, 0) < _SEV_ORDER.get(min_severity, 3):
        return None, "skip", [], f"Severity '{severity}' is below configured minimum '{min_severity}'."

    for rule in _RULES:
        # Severity gate
        rule_min = rule.get("min_severity", "high")
        if _SEV_ORDER.get(severity, 0) < _SEV_ORDER.get(rule_min, 3):
            continue
        # Title / category keyword match (either can satisfy; empty both = catch-all)
        title_kw = rule.get("title_keywords", ())
        cat_kw = rule.get("category_keywords", ())
        if title_kw or cat_kw:
            category = (alert.get("category") or "").lower()
            title_match = bool(title_kw) and any(kw in title for kw in title_kw)
            cat_match = bool(cat_kw) and any(ck.lower() in category for ck in cat_kw)
            if not title_match and not cat_match:
                continue
        # Optional service source filter
        svc_filter = rule.get("service_source_contains")
        if svc_filter and not any(s in service_source for s in svc_filter):
            continue
        # Support composite action_types list or single action_type
        ats: list[str] = rule.get("action_types") or ([rule["action_type"]] if rule.get("action_type") else [])
        tier: int = rule["tier"]
        decision: str = rule["decision"]
        reason: str = rule["reason"]
        # Off-hours escalation: T2/queue → T1/execute outside PT business hours.
        # Only applies to rules explicitly tagged off_hours_escalate=True.
        if (
            rule.get("off_hours_escalate")
            and tier == 2
            and decision == "queue"
            and _is_off_hours_pt()
        ):
            tier = 1
            decision = "execute"
            reason = reason + " [Off-hours: escalated to T1 — no cancellation window available.]"
        return tier, decision, ats, reason

    return None, "skip", [], "Alert category/title did not match any decision rule."


def _check_entity_cooldown(
    entities: list[dict[str, Any]],
    action_types: list[str],
    recent_actions: dict[str, set[str]],
) -> tuple[bool, str]:
    """Return (on_cooldown, reason) if any entity already had the same action dispatched recently.

    ``recent_actions`` maps entity_id → set of dispatched action_types (built
    from defender_agent_store.get_recent_entity_actions()).

    Cooldown fires when ALL actionable entities for a given action type are
    already covered.  If at least one entity is new or uncooled, we let the
    cycle proceed — the dispatch handlers already target only the relevant IDs.
    """
    if not recent_actions or not action_types or not entities:
        return False, ""

    for at in action_types:
        # Determine which entity types this action targets
        is_user_action = at in (
            "revoke_sessions", "disable_sign_in", "account_lockout",
            "reset_password",
        )
        is_device_action = at in (
            "isolate_device", "unisolate_device", "run_av_scan",
            "device_sync", "device_wipe", "device_retire",
            "restrict_app_execution", "unrestrict_app_execution",
            "collect_investigation_package", "start_investigation",
            "stop_and_quarantine_file", "create_block_indicator",
        )
        if not is_user_action and not is_device_action:
            continue

        if is_user_action:
            target_entities = [e for e in entities if e.get("type") == "user" and e.get("id")]
        else:
            target_entities = [e for e in entities if e.get("type") == "device" and e.get("id")]

        if not target_entities:
            continue

        cooled = [
            e for e in target_entities
            if at in recent_actions.get(str(e["id"]), set())
        ]
        if cooled and len(cooled) == len(target_entities):
            names = ", ".join(e.get("name") or e["id"] for e in cooled[:2])
            if len(cooled) > 2:
                names += f" +{len(cooled) - 2}"
            return True, (
                f"Cooldown: {at.replace('_', ' ')} was already applied to "
                f"{names} within the cooldown window."
            )

    return False, ""


def _build_dedup_index(
    recent_decisions: list[dict[str, Any]],
) -> dict[tuple[str, str], str]:
    """Build (entity_id, action_type) → decision_id mapping from recent non-skip decisions.

    Used at cycle start to seed the within-cycle deduplication check.  The index
    is then updated in-place as actions are dispatched during the cycle so that
    multiple related alerts arriving in the same fetch are collapsed correctly.
    """
    index: dict[tuple[str, str], str] = {}
    for dec in recent_decisions:
        eid_list = [str(e.get("id") or "") for e in dec.get("entities", []) if e.get("id")]
        ats = dec.get("action_types") or []
        for eid in eid_list:
            for at in ats:
                if eid and at:
                    key = (eid, at)
                    if key not in index:
                        index[key] = dec["decision_id"]
    return index


def _find_correlated_decision(
    entities: list[dict[str, Any]],
    action_types: list[str],
    dedup_index: dict[tuple[str, str], str],
) -> tuple[str | None, str]:
    """Return (existing_decision_id, reason) if this alert overlaps a recent decision.

    Checks each (entity_id, action_type) pair against the dedup index.  The first
    match is returned so the caller can log a correlated-skip instead of creating
    a duplicate action.
    """
    for at in action_types:
        for entity in entities:
            eid = str(entity.get("id") or "")
            if not eid:
                continue
            existing_id = dedup_index.get((eid, at))
            if existing_id:
                name = entity.get("name") or eid
                return existing_id, (
                    f"Correlated: {at.replace('_', ' ')} already actioned for "
                    f"'{name}' by decision {existing_id[:8]} within dedup window."
                )
    return None, ""


def _is_suppressed(
    alert: dict[str, Any],
    entities: list[dict[str, Any]],
    suppressions: list[dict[str, Any]],
) -> tuple[bool, str]:
    """Return (suppressed, reason) if the alert matches any active suppression rule."""
    title = (alert.get("title") or "").lower()
    category = (alert.get("category") or "").lower()

    for s in suppressions:
        stype = str(s.get("suppression_type") or "")
        val = str(s.get("value") or "").lower()
        if not val:
            continue

        if stype == "alert_title" and val in title:
            return True, f"Suppressed: alert title matches '{s['value']}' (rule {s['id'][:8]})"
        if stype == "alert_category" and val == category:
            return True, f"Suppressed: alert category '{s['value']}' is suppressed (rule {s['id'][:8]})"
        if stype == "entity_user":
            for e in entities:
                if e.get("type") == "user":
                    name_match = val == (e.get("name") or "").lower()
                    id_match = val == (e.get("id") or "").lower()
                    if name_match or id_match:
                        display = e.get("name") or e.get("id") or val
                        return True, f"Suppressed: user '{display}' is suppressed (rule {s['id'][:8]})"
        if stype == "entity_device":
            for e in entities:
                if e.get("type") == "device":
                    name_match = val == (e.get("name") or "").lower()
                    id_match = val == (e.get("id") or "").lower()
                    if name_match or id_match:
                        display = e.get("name") or e.get("id") or val
                        return True, f"Suppressed: device '{display}' is suppressed (rule {s['id'][:8]})"

    return False, ""


def _extract_mitre_techniques(alert: dict[str, Any]) -> list[str]:
    """Return deduplicated MITRE ATT&CK technique IDs from a Graph Security alert.

    Graph surfaces these in two places:
    - Top-level ``mitreTechniques`` list (e.g. ["T1078", "T1110.003"])
    - Per-evidence ``detectionStatus``/``techniques`` on some alert types
    We prefer the top-level field and fall back to evidence scanning.
    """
    seen: set[str] = set()
    techniques: list[str] = []

    def _add(val: str) -> None:
        normalized = val.strip().upper()
        if normalized and normalized not in seen:
            seen.add(normalized)
            techniques.append(normalized)

    for t in (alert.get("mitreTechniques") or []):
        if isinstance(t, str):
            _add(t)

    # Fallback: some alert types embed techniques in evidence items
    if not techniques:
        for item in (alert.get("evidence") or []):
            for t in (item.get("techniques") or []):
                if isinstance(t, str):
                    _add(t)

    return techniques


def _extract_entities(alert: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract user and device entities from Graph alert evidence."""
    entities: list[dict[str, Any]] = []
    for item in (alert.get("evidence") or []):
        odata = (item.get("@odata.type") or "").lower()
        if "userevidence" in odata:
            acct = item.get("userAccount") or {}
            upn = acct.get("userPrincipalName") or ""
            uid = acct.get("azureAdUserId") or acct.get("accountObjectId") or ""
            if upn or uid:
                entities.append({"type": "user", "id": uid, "name": upn or uid})
        elif "deviceevidence" in odata:
            dev = item.get("device") or {}
            did = dev.get("deviceId") or item.get("deviceId") or ""
            dname = dev.get("deviceName") or item.get("deviceName") or did
            if did or dname:
                entities.append({"type": "device", "id": did, "name": dname})
    return entities


# ---------------------------------------------------------------------------
# Teams notification helper (sync — runs in executor thread)
# ---------------------------------------------------------------------------

_SEV_EMOJI: dict[str, str] = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🔵",
    "informational": "⚪",
}

_TIER_LABEL: dict[int, str] = {1: "T1 Immediate", 2: "T2 Queued", 3: "T3 Approval Required"}


def _notify_teams(
    *,
    title: str,
    severity: str,
    tier: int | None,
    action_type: str,
    service_source: str,
    entities: list[dict],
    reason: str,
    is_approval: bool = False,
    console_url: str = "https://azure.movedocs.com/security/agent",
) -> None:
    """Post an Adaptive Card to the configured Teams webhook. Best-effort — never raises."""
    webhook_url = DEFENDER_AGENT_TEAMS_WEBHOOK_URL
    if not webhook_url:
        return
    try:
        import httpx

        sev_emoji = _SEV_EMOJI.get(severity.lower(), "⚠️")
        tier_label = _TIER_LABEL.get(tier or 0, "Agent Action")
        entity_names = [e.get("name") or e.get("id") for e in entities[:3] if e.get("name") or e.get("id")]
        entity_str = ", ".join(str(n) for n in entity_names) if entity_names else "—"
        if is_approval:
            header = f"✅ T3 Approved — {title}"
            body_text = f"Action **{action_type.replace('_', ' ')}** dispatched by operator."
        elif tier == 3:
            header = f"⚠️ Approval Required — {title}"
            body_text = f"**T3 action needs human approval** before executing `{action_type.replace('_', ' ')}`."
        else:
            header = f"{sev_emoji} Defender Agent — {title}"
            body_text = reason

        card: dict = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "text": header, "weight": "Bolder", "size": "Medium", "wrap": True},
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "Severity", "value": severity.capitalize()},
                                {"title": "Tier", "value": tier_label},
                                {"title": "Action", "value": action_type.replace("_", " ").title()},
                                {"title": "Source", "value": service_source or "—"},
                                {"title": "Entities", "value": entity_str},
                            ],
                        },
                        {"type": "TextBlock", "text": body_text, "wrap": True, "spacing": "Small"},
                    ],
                    "actions": [
                        {"type": "Action.OpenUrl", "title": "Open Agent Console", "url": console_url},
                    ],
                },
            }],
        }
        with httpx.Client(timeout=15) as client:
            resp = client.post(webhook_url, json=card)
            if not resp.is_success:
                logger.warning("Teams webhook returned %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("_notify_teams failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Agent cycle
# ---------------------------------------------------------------------------


def _run_agent_cycle() -> None:
    """Synchronous cycle called from an executor thread."""
    from defender_agent_store import defender_agent_store
    from user_admin_jobs import user_admin_jobs
    from security_device_jobs import security_device_jobs

    config = defender_agent_store.get_config()
    if not config.get("enabled"):
        return

    # Lazy import to avoid circular imports at module load time
    try:
        from azure_client import AzureClient
    except Exception as exc:
        logger.warning("Defender agent: could not import AzureClient: %s", exc)
        return

    run_id = uuid.uuid4().hex
    defender_agent_store.create_run(run_id)

    alerts_fetched = 0
    alerts_new = 0
    decisions_made = 0
    actions_queued = 0
    skip_count = 0

    try:
        client = AzureClient()
        alerts = client.list_security_alerts(
            lookback_hours=48,
            top=200,
        )
        alerts_fetched = len(alerts)

        seen_ids = defender_agent_store.get_seen_alert_ids(since_hours=168)
        new_alerts = [a for a in alerts if a.get("id") and a["id"] not in seen_ids]
        alerts_new = len(new_alerts)

        min_severity = str(config.get("min_severity") or "high").lower()
        dry_run = bool(config.get("dry_run", False))
        tier2_delay = int(config.get("tier2_delay_minutes") or 15)
        jobs_dispatched = 0

        active_suppressions = defender_agent_store.get_active_suppressions()
        cooldown_hours = int(config.get("entity_cooldown_hours") or 24)
        recent_entity_actions = (
            defender_agent_store.get_recent_entity_actions(hours=cooldown_hours)
            if cooldown_hours > 0 else {}
        )
        dedup_minutes = int(config.get("alert_dedup_window_minutes") or 30)
        dedup_index = _build_dedup_index(
            defender_agent_store.get_recent_decisions_for_dedup(since_minutes=dedup_minutes)
            if dedup_minutes > 0 else []
        )

        for alert in new_alerts:
            alert_id = alert.get("id", uuid.uuid4().hex)
            alert_title = str(alert.get("title") or "")
            alert_severity = str(alert.get("severity") or "")
            alert_service_source = str(alert.get("serviceSource") or "")
            entities = _extract_entities(alert)

            mitre_techniques = _extract_mitre_techniques(alert)

            suppressed, suppress_reason = _is_suppressed(alert, entities, active_suppressions)
            if suppressed:
                decision_id = uuid.uuid4().hex
                defender_agent_store.create_decision(
                    decision_id=decision_id,
                    run_id=run_id,
                    alert_id=alert_id,
                    alert_title=alert_title,
                    alert_severity=alert_severity,
                    alert_category=str(alert.get("category") or ""),
                    alert_created_at=str(alert.get("createdDateTime") or ""),
                    service_source=alert_service_source,
                    entities=entities,
                    tier=None,
                    decision="skip",
                    action_type="",
                    action_types=[],
                    job_ids=[],
                    reason=suppress_reason,
                    not_before_at=None,
                    alert_raw=alert,
                    mitre_techniques=mitre_techniques,
                )
                decisions_made += 1
                skip_count += 1
                logger.info("Defender agent: suppressed alert %s — %s", alert_id, suppress_reason)
                continue

            tier, decision_type, action_types, reason = _classify_alert(alert, min_severity)
            # Primary action_type is first in list (for display / backward compat)
            action_type = action_types[0] if action_types else ""

            # Deduplication check: skip if we already have a non-skip decision for these
            # entities + actions within the dedup window (catches within-cycle duplicates too)
            if decision_type in ("execute", "queue") and dedup_minutes > 0:
                correlated_id, corr_reason = _find_correlated_decision(
                    entities, action_types, dedup_index
                )
                if correlated_id:
                    decision_id = uuid.uuid4().hex
                    defender_agent_store.create_decision(
                        decision_id=decision_id,
                        run_id=run_id,
                        alert_id=alert_id,
                        alert_title=alert_title,
                        alert_severity=alert_severity,
                        alert_category=str(alert.get("category") or ""),
                        alert_created_at=str(alert.get("createdDateTime") or ""),
                        service_source=alert_service_source,
                        entities=entities,
                        tier=tier,
                        decision="skip",
                        action_type=action_type,
                        action_types=action_types,
                        job_ids=[],
                        reason=corr_reason,
                        not_before_at=None,
                        alert_raw=alert,
                        mitre_techniques=mitre_techniques,
                    )
                    decisions_made += 1
                    skip_count += 1
                    logger.info("Defender agent: correlated skip for alert %s — %s", alert_id, corr_reason)
                    continue

            # Entity cooldown check: skip if all target entities already had this action recently
            if decision_type in ("execute", "queue") and cooldown_hours > 0:
                on_cooldown, cooldown_reason = _check_entity_cooldown(
                    entities, action_types, recent_entity_actions
                )
                if on_cooldown:
                    decision_id = uuid.uuid4().hex
                    defender_agent_store.create_decision(
                        decision_id=decision_id,
                        run_id=run_id,
                        alert_id=alert_id,
                        alert_title=alert_title,
                        alert_severity=alert_severity,
                        alert_category=str(alert.get("category") or ""),
                        alert_created_at=str(alert.get("createdDateTime") or ""),
                        service_source=alert_service_source,
                        entities=entities,
                        tier=tier,
                        decision="skip",
                        action_type=action_type,
                        action_types=action_types,
                        job_ids=[],
                        reason=cooldown_reason,
                        not_before_at=None,
                        alert_raw=alert,
                        mitre_techniques=mitre_techniques,
                    )
                    decisions_made += 1
                    skip_count += 1
                    logger.info("Defender agent: cooldown skip for alert %s — %s", alert_id, cooldown_reason)
                    continue

            decision_id = uuid.uuid4().hex
            not_before_at: str | None = None

            if decision_type == "queue":
                not_before_at = (
                    datetime.now(timezone.utc) + timedelta(minutes=tier2_delay)
                ).isoformat()

            defender_agent_store.create_decision(
                decision_id=decision_id,
                run_id=run_id,
                alert_id=alert_id,
                alert_title=alert_title,
                alert_severity=alert_severity,
                alert_category=str(alert.get("category") or ""),
                alert_created_at=str(alert.get("createdDateTime") or ""),
                service_source=alert_service_source,
                entities=entities,
                tier=tier,
                decision=decision_type,
                action_type=action_type,
                action_types=action_types,
                job_ids=[],
                reason=reason,
                not_before_at=not_before_at,
                alert_raw=alert,
                mitre_techniques=mitre_techniques,
            )
            decisions_made += 1
            if decision_type == "skip":
                skip_count += 1

            # Mark alert inProgress in Defender; set TruePositive verdict for actioned alerts
            if decision_type != "skip":
                try:
                    classification = None
                    determination = None
                    if decision_type in ("execute", "queue"):
                        classification = "truePositive"
                        determination = "malware"
                    written_back = client.update_security_alert(
                        alert_id,
                        classification=classification,
                        determination=determination,
                    )
                    if written_back:
                        defender_agent_store.update_decision_writeback(decision_id)
                except Exception:
                    pass

            # T1 — execute immediately (subject to per-cycle cap)
            if decision_type == "execute" and not dry_run:
                if jobs_dispatched < DEFENDER_AGENT_MAX_JOBS_PER_CYCLE:
                    all_job_ids: list[str] = []
                    for at in action_types:
                        jids = _dispatch_action(
                            action_type=at,
                            entities=entities,
                            alert=alert,
                            user_admin_jobs=user_admin_jobs,
                            security_device_jobs=security_device_jobs,
                            reason=reason,
                            alert_severity=alert_severity,
                        )
                        all_job_ids.extend(jids)
                    if all_job_ids:
                        defender_agent_store.update_decision_jobs(decision_id, all_job_ids)
                        actions_queued += len(all_job_ids)
                        jobs_dispatched += len(all_job_ids)
                        # Update in-memory indexes so within-cycle duplicates are caught
                        for at in action_types:
                            for entity in entities:
                                eid = str(entity.get("id") or "")
                                if eid:
                                    dedup_index[(eid, at)] = decision_id
                                    if eid not in recent_entity_actions:
                                        recent_entity_actions[eid] = set()
                                    recent_entity_actions[eid].add(at)
                    if DEFENDER_AGENT_TEAMS_NOTIFY_T1:
                        _notify_teams(
                            title=alert_title, severity=alert_severity, tier=tier,
                            action_type=action_type, service_source=alert_service_source,
                            entities=entities, reason=reason,
                        )
                else:
                    logger.warning(
                        "Defender agent: per-cycle job cap (%d) reached; T1 action for alert %s deferred",
                        DEFENDER_AGENT_MAX_JOBS_PER_CYCLE, alert_id,
                    )

            # T2 — notify operator of queued action
            elif decision_type == "queue" and not dry_run and DEFENDER_AGENT_TEAMS_NOTIFY_T2:
                _notify_teams(
                    title=alert_title, severity=alert_severity, tier=tier,
                    action_type=action_type, service_source=alert_service_source,
                    entities=entities, reason=reason,
                )

            # T3 — always notify (human approval required)
            elif decision_type == "recommend":
                _notify_teams(
                    title=alert_title, severity=alert_severity, tier=tier,
                    action_type=action_type, service_source=alert_service_source,
                    entities=entities, reason=reason,
                )

        # Dispatch T2 rows whose delay window has now passed
        pending_t2 = defender_agent_store.list_pending_tier2()
        for row in pending_t2:
            if dry_run:
                continue
            if jobs_dispatched >= DEFENDER_AGENT_MAX_JOBS_PER_CYCLE:
                logger.warning("Defender agent: per-cycle job cap reached during T2 flush; deferring remaining T2 rows")
                break
            stored_entities: list[dict[str, Any]] = row.get("entities") or []
            stored_ats: list[str] = row.get("action_types") or [str(row.get("action_type") or "")]
            t2_job_ids: list[str] = []
            for at in stored_ats:
                jids = _dispatch_action(
                    action_type=at,
                    entities=stored_entities,
                    alert={},
                    user_admin_jobs=user_admin_jobs,
                    security_device_jobs=security_device_jobs,
                    reason=str(row.get("reason") or ""),
                    alert_severity=str(row.get("alert_severity") or ""),
                )
                t2_job_ids.extend(jids)
            if t2_job_ids:
                defender_agent_store.update_decision_jobs(str(row["decision_id"]), t2_job_ids)
                actions_queued += len(t2_job_ids)
                jobs_dispatched += len(t2_job_ids)

        defender_agent_store.complete_run(
            run_id,
            alerts_fetched=alerts_fetched,
            alerts_new=alerts_new,
            decisions_made=decisions_made,
            actions_queued=actions_queued,
            skips=skip_count,
        )

    except Exception as exc:
        logger.exception("Defender agent cycle error")
        defender_agent_store.complete_run(
            run_id,
            alerts_fetched=alerts_fetched,
            alerts_new=alerts_new,
            decisions_made=decisions_made,
            actions_queued=actions_queued,
            skips=skip_count,
            error=str(exc),
        )


def _dispatch_action(
    *,
    action_type: str,
    entities: list[dict[str, Any]],
    alert: dict[str, Any],
    user_admin_jobs: Any,
    security_device_jobs: Any,
    reason: str = "",
    alert_severity: str = "",
) -> list[str]:
    """Dispatch a single action to the appropriate job runner.  Returns job IDs created."""
    job_ids: list[str] = []

    if action_type == "revoke_sessions":
        user_ids = [e["id"] for e in entities if e.get("type") == "user" and e.get("id")]
        if not user_ids:
            logger.info("Defender agent: revoke_sessions — no user IDs in entities, skipping")
            return []
        try:
            job = user_admin_jobs.create_job(
                action_type="revoke_sessions",
                target_user_ids=user_ids,
                params=None,
                requested_by_email=_AGENT_EMAIL,
                requested_by_name=_AGENT_NAME,
            )
            job_ids.append(str(job.get("job_id") or ""))
            logger.info(
                "Defender agent: queued revoke_sessions for %d user(s) (job %s)",
                len(user_ids), job_ids[-1],
            )
        except Exception as exc:
            logger.warning("Defender agent: revoke_sessions dispatch failed: %s", exc)

    elif action_type == "disable_sign_in":
        user_ids = [e["id"] for e in entities if e.get("type") == "user" and e.get("id")]
        if not user_ids:
            logger.info("Defender agent: disable_sign_in — no user IDs in entities, skipping")
            return []
        try:
            job = user_admin_jobs.create_job(
                action_type="disable_sign_in",
                target_user_ids=user_ids,
                params=None,
                requested_by_email=_AGENT_EMAIL,
                requested_by_name=_AGENT_NAME,
            )
            job_ids.append(str(job.get("job_id") or ""))
            logger.info(
                "Defender agent: queued disable_sign_in for %d user(s) (job %s)",
                len(user_ids), job_ids[-1],
            )
        except Exception as exc:
            logger.warning("Defender agent: disable_sign_in dispatch failed: %s", exc)

    elif action_type == "account_lockout":
        # Composite: revoke active sessions AND disable sign-in simultaneously
        user_ids = [e["id"] for e in entities if e.get("type") == "user" and e.get("id")]
        if not user_ids:
            logger.info("Defender agent: account_lockout — no user IDs in entities, skipping")
            return []
        for at in ("revoke_sessions", "disable_sign_in"):
            try:
                job = user_admin_jobs.create_job(
                    action_type=at,
                    target_user_ids=user_ids,
                    params=None,
                    requested_by_email=_AGENT_EMAIL,
                    requested_by_name=_AGENT_NAME,
                )
                job_ids.append(str(job.get("job_id") or ""))
                logger.info(
                    "Defender agent: account_lockout — queued %s for %d user(s) (job %s)",
                    at, len(user_ids), job_ids[-1],
                )
            except Exception as exc:
                logger.warning("Defender agent: account_lockout/%s dispatch failed: %s", at, exc)

    elif action_type == "reset_password":
        user_ids = [e["id"] for e in entities if e.get("type") in ("user", "account") and e.get("id")]
        if not user_ids:
            logger.info("Defender agent: reset_password — no user IDs in entities, skipping")
            return []
        try:
            user_names = [e.get("name") or e["id"] for e in entities
                          if e.get("type") in ("user", "account") and e.get("id")]
            job = user_admin_jobs.create_job(
                action_type="reset_password",
                target_user_ids=user_ids,
                params={"user_names": user_names, "reason": reason, "force_change": True},
                requested_by_email=_AGENT_EMAIL,
                requested_by_name=_AGENT_NAME,
            )
            job_ids.append(str(job.get("job_id") or ""))
            logger.info(
                "Defender agent: queued reset_password for %d user(s) (job %s)",
                len(user_ids), job_ids[-1],
            )
        except Exception as exc:
            logger.warning("Defender agent: reset_password dispatch failed: %s", exc)

    elif action_type == "device_sync":
        device_ids = [e["id"] for e in entities if e.get("type") == "device" and e.get("id")]
        if not device_ids:
            logger.info("Defender agent: device_sync — no device IDs in entities, skipping")
            return []
        try:
            job = security_device_jobs.create_job(
                action_type="device_sync",
                device_ids=device_ids,
                reason="Autonomous agent: Defender antivirus/compliance alert",
                params=None,
                confirm_device_count=None,
                confirm_device_names=None,
                requested_by_email=_AGENT_EMAIL,
                requested_by_name=_AGENT_NAME,
            )
            job_ids.append(str(job.get("job_id") or ""))
            logger.info(
                "Defender agent: queued device_sync for %d device(s) (job %s)",
                len(device_ids), job_ids[-1],
            )
        except Exception as exc:
            logger.warning("Defender agent: device_sync dispatch failed: %s", exc)

    elif action_type in ("device_wipe", "device_retire"):
        # T3 — should never reach _dispatch_action normally; only via approve endpoint
        device_ids = [e["id"] for e in entities if e.get("type") == "device" and e.get("id")]
        if not device_ids:
            return []
        try:
            job = security_device_jobs.create_job(
                action_type=action_type,
                device_ids=device_ids,
                reason="Defender agent: approved by operator",
                params=None,
                confirm_device_count=len(device_ids),
                confirm_device_names=[e["name"] for e in entities if e.get("type") == "device"],
                requested_by_email=_AGENT_EMAIL,
                requested_by_name=_AGENT_NAME,
            )
            job_ids.append(str(job.get("job_id") or ""))
        except Exception as exc:
            logger.warning("Defender agent: %s dispatch failed: %s", action_type, exc)

    elif action_type in (
        "isolate_device", "unisolate_device", "run_av_scan",
        "collect_investigation_package", "restrict_app_execution",
        "start_investigation", "unrestrict_app_execution",
    ):
        # MDE (Microsoft Defender for Endpoint) machine actions — use mdeDeviceId, not Intune deviceId
        device_entities = [e for e in entities if e.get("type") == "device" and e.get("id")]
        if not device_entities:
            logger.info("Defender agent: %s — no device IDs in entities, skipping", action_type)
            return []
        mde_device_ids = [e["id"] for e in device_entities]
        device_names = [e.get("name") or e["id"] for e in device_entities]
        try:
            job = security_device_jobs.create_job(
                action_type=action_type,  # type: ignore[arg-type]
                device_ids=mde_device_ids,
                reason=reason,
                params={"device_names": device_names, "reason": reason},
                confirm_device_count=None,
                confirm_device_names=None,
                requested_by_email=_AGENT_EMAIL,
                requested_by_name=_AGENT_NAME,
            )
            job_ids.append(str(job.get("job_id") or ""))
            logger.info(
                "Defender agent: queued %s for %d device(s) (job %s)",
                action_type, len(mde_device_ids), job_ids[-1],
            )
        except Exception as exc:
            logger.warning("Defender agent: %s dispatch failed: %s", action_type, exc)

    elif action_type == "stop_and_quarantine_file":
        # Requires Machine.StopAndQuarantine — stops the running process and quarantines the file
        device_entities = [e for e in entities if e.get("type") == "device" and e.get("id")]
        file_entities = [
            e for e in entities
            if e.get("type") in ("file", "process") and (e.get("sha1") or e.get("sha256"))
        ]
        if not device_entities or not file_entities:
            logger.info(
                "Defender agent: stop_and_quarantine_file — missing device or file entities, skipping"
            )
            return []
        for file_ent in file_entities:
            sha1 = str(file_ent.get("sha1") or "")
            file_name = str(file_ent.get("fileName") or "")
            for dev in device_entities:
                try:
                    job = security_device_jobs.create_job(
                        action_type="stop_and_quarantine_file",  # type: ignore[arg-type]
                        device_ids=[dev["id"]],
                        reason=reason,
                        params={
                            "sha1": sha1,
                            "file_name": file_name,
                            "device_names": [dev.get("name") or dev["id"]],
                            "reason": reason,
                        },
                        confirm_device_count=None,
                        confirm_device_names=None,
                        requested_by_email=_AGENT_EMAIL,
                        requested_by_name=_AGENT_NAME,
                    )
                    job_ids.append(str(job.get("job_id") or ""))
                    logger.info(
                        "Defender agent: queued stop_and_quarantine_file for device %s file %s (job %s)",
                        dev["id"], sha1 or file_name, job_ids[-1],
                    )
                except Exception as exc:
                    logger.warning("Defender agent: stop_and_quarantine_file dispatch failed: %s", exc)

    elif action_type == "create_block_indicator":
        # Requires Ti.ReadWrite.All — tenant-wide block for file hashes, IPs, domains
        ioc_entities: list[dict[str, Any]] = []
        for e in entities:
            etype = str(e.get("type") or "")
            if etype == "file":
                for htype, itype in (
                    ("sha256", "FileSha256"), ("sha1", "FileSha1"), ("md5", "FileMd5")
                ):
                    if e.get(htype):
                        ioc_entities.append({
                            "value": e[htype],
                            "indicator_type": itype,
                            "name": str(e.get("fileName") or e[htype]),
                        })
                        break
            elif etype == "ip" and e.get("address"):
                ioc_entities.append({
                    "value": str(e["address"]),
                    "indicator_type": "IpAddress",
                    "name": str(e["address"]),
                })
            elif etype in ("url", "domain"):
                val = str(e.get("url") or e.get("domainName") or "")
                if val:
                    ioc_entities.append({
                        "value": val,
                        "indicator_type": "Url" if etype == "url" else "DomainName",
                        "name": val,
                    })
        if not ioc_entities:
            logger.info("Defender agent: create_block_indicator — no IOC entities found, skipping")
            return []
        sev = alert_severity.capitalize() if alert_severity else "High"
        for ioc in ioc_entities:
            try:
                job = security_device_jobs.create_job(
                    action_type="create_block_indicator",  # type: ignore[arg-type]
                    device_ids=[ioc["value"]],
                    reason=reason,
                    params={
                        "indicator_value": ioc["value"],
                        "indicator_type": ioc["indicator_type"],
                        "device_names": [ioc["name"]],
                        "reason": reason,
                        "title": f"Blocked by Defender agent: {reason[:80]}",
                        "severity": sev,
                    },
                    confirm_device_count=None,
                    confirm_device_names=None,
                    requested_by_email=_AGENT_EMAIL,
                    requested_by_name=_AGENT_NAME,
                )
                job_ids.append(str(job.get("job_id") or ""))
                logger.info(
                    "Defender agent: queued create_block_indicator for %s %s (job %s)",
                    ioc["indicator_type"], ioc["value"], job_ids[-1],
                )
            except Exception as exc:
                logger.warning("Defender agent: create_block_indicator dispatch failed: %s", exc)

    else:
        if action_type:
            logger.warning(
                "Defender agent: no dispatch handler for action_type=%r; returning no jobs",
                action_type,
            )

    return [j for j in job_ids if j]


def dispatch_approved_t3(decision_id: str) -> list[str]:
    """Called by the approve endpoint to execute a T3 decision immediately."""
    from defender_agent_store import defender_agent_store
    from user_admin_jobs import user_admin_jobs
    from security_device_jobs import security_device_jobs

    row = defender_agent_store.get_decision(decision_id)
    if not row:
        return []
    stored_ats: list[str] = row.get("action_types") or [str(row.get("action_type") or "")]
    all_job_ids: list[str] = []
    for at in stored_ats:
        jids = _dispatch_action(
            action_type=at,
            entities=row.get("entities") or [],
            alert={},
            user_admin_jobs=user_admin_jobs,
            security_device_jobs=security_device_jobs,
            reason=str(row.get("reason") or ""),
            alert_severity=str(row.get("alert_severity") or ""),
        )
        all_job_ids.extend(jids)
    if all_job_ids:
        defender_agent_store.update_decision_jobs(decision_id, all_job_ids)
    return all_job_ids


# ---------------------------------------------------------------------------
# Background worker lifecycle
# ---------------------------------------------------------------------------

_bg_task: asyncio.Task[None] | None = None


async def _agent_loop() -> None:
    while True:
        try:
            await asyncio.get_running_loop().run_in_executor(None, _run_agent_cycle)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Defender agent loop iteration failed")
        await asyncio.sleep(AZURE_DEFENDER_AGENT_POLL_SECONDS)


async def start_worker() -> None:
    global _bg_task
    if _bg_task and not _bg_task.done():
        return
    _bg_task = asyncio.get_running_loop().create_task(_agent_loop())
    logger.info("Defender autonomous agent worker started (poll interval %ds)", AZURE_DEFENDER_AGENT_POLL_SECONDS)


async def stop_worker() -> None:
    global _bg_task
    if not _bg_task:
        return
    _bg_task.cancel()
    try:
        await _bg_task
    except asyncio.CancelledError:
        pass
    _bg_task = None
    logger.info("Defender autonomous agent worker stopped")
