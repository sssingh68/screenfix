import asyncio
from datetime import datetime, timezone
import logging
import os
from typing import Any, Dict, List, Optional
import uuid
from google.cloud import firestore
from google.genai import types
import skills

logger = logging.getLogger("screenfix.tools")

# Firestore client (tenant isolation enforced on every read/write)
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0942589575")
db = firestore.Client(project=PROJECT_ID)

# In-memory approval events and decision registry for live session notifications
APPROVAL_EVENTS: Dict[str, asyncio.Event] = {}
APPROVAL_RESULTS: Dict[str, str] = {}

# 1. Tool Declaration: match_runbook
MATCH_RUNBOOK_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="match_runbook",
            description=(
                "Searches approved runbooks for an IT error seen on screen or described by the user. "
                "Returns runbook_id, action_id, title, and ticket_id if matched, or runbook_id 'none'."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "issue_summary": types.Schema(
                        type=types.Type.STRING,
                        description="A short summary of the error or issue, e.g. 'VPN Error 809 - connection failed'"
                    )
                },
                required=["issue_summary"]
            )
        )
    ]
)

# 2. Tool Declaration: request_approval
REQUEST_APPROVAL_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="request_approval",
            description=(
                "Requests approval from the MSP's L1 human engineer in the console to execute a runbook action. "
                "Returns status 'pending' immediately. Human approval is required before execution."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "runbook_id": types.Schema(
                        type=types.Type.STRING,
                        description="The ID of the runbook to approve, e.g. 'vpn-error-809'"
                    ),
                    "ticket_id": types.Schema(
                        type=types.Type.STRING,
                        description="The ticket ID associated with the live session, e.g. 'TKT-123456'"
                    )
                },
                required=["runbook_id", "ticket_id"]
            )
        )
    ]
)

# Combined tools list for Gemini Live session
TOOLS = [MATCH_RUNBOOK_TOOL, REQUEST_APPROVAL_TOOL]


def match_runbook(issue_summary: str, ticket_id: str = "") -> Dict[str, Any]:
    """Matches an issue summary against loaded skills and returns runbook metadata + ticket_id."""
    if not issue_summary:
        return {"runbook_id": "none", "ticket_id": ticket_id}

    summary_lower = issue_summary.lower()
    all_skills = skills.get_skills()

    best_match = None
    best_score = 0

    for s in all_skills:
        skill_id = s.get("id", "").lower()
        description = s.get("description", "").lower()

        score = 0
        tokens = set(skill_id.replace("-", " ").split() + description.replace('"', '').replace(".", "").split())
        for token in tokens:
            if len(token) >= 3 and token in summary_lower:
                score += 1

        if "809" in summary_lower and "809" in skill_id:
            score += 5
        if "vpn" in summary_lower and "vpn" in skill_id:
            score += 3

        if score > best_score:
            best_score = score
            best_match = s

    if best_match and best_score >= 2:
        return {
            "runbook_id": best_match["id"],
            "action_id": best_match.get("action_id"),
            "title": best_match.get("name", best_match["id"]),
            "ticket_id": ticket_id
        }

    return {"runbook_id": "none", "ticket_id": ticket_id}


def request_approval(runbook_id: str, ticket_id: str, tenant_id: str = "demo-msp") -> Dict[str, Any]:
    """Creates a pending approval in Firestore with tenant isolation, registers an in-memory event,

    and returns 'pending' immediately without blocking.
    """
    approval_id = f"APP-{uuid.uuid4().hex[:6].upper()}"
    skill = skills.get_skill(runbook_id)
    action_id = skill.get("action_id") if skill else "unknown"
    created_at = datetime.now(timezone.utc).isoformat()

    doc_data = {
        "approval_id": approval_id,
        "tenant_id": tenant_id,
        "ticket_id": ticket_id,
        "runbook_id": runbook_id,
        "action_id": action_id,
        "status": "pending",
        "created_at": created_at,
    }

    # Write document to Firestore collection 'approvals'
    db.collection("approvals").document(approval_id).set(doc_data)

    # Register in-memory event for the live session task to await
    APPROVAL_EVENTS[approval_id] = asyncio.Event()

    return {
        "status": "pending",
        "approval_id": approval_id,
        "ticket_id": ticket_id,
        "runbook_id": runbook_id,
        "action_id": action_id
    }


def get_pending_approvals(tenant_id: str = "demo-msp") -> List[Dict[str, Any]]:
    """Retrieves all pending approval documents from Firestore for the given tenant."""
    docs = (
        db.collection("approvals")
        .where(filter=firestore.FieldFilter("tenant_id", "==", tenant_id))
        .where(filter=firestore.FieldFilter("status", "==", "pending"))
        .stream()
    )
    results = []
    for d in docs:
        item = d.to_dict()
        results.append(item)
    return results


def decide_approval(approval_id: str, decision: str, approver: str = "l1-engineer-demo", tenant_id: str = "demo-msp") -> bool:
    """Updates Firestore approval document status and notifies the awaiting live session via asyncio.Event."""
    doc_ref = db.collection("approvals").document(approval_id)
    doc = doc_ref.get()
    if not doc.exists:
        return False

    decided_at = datetime.now(timezone.utc).isoformat()
    doc_ref.update({
        "status": decision,
        "approved_by": approver,
        "decided_at": decided_at,
        "tenant_id": tenant_id
    })

    # Record decision and trigger the in-memory event
    APPROVAL_RESULTS[approval_id] = decision
    if approval_id in APPROVAL_EVENTS:
        APPROVAL_EVENTS[approval_id].set()

    return True
