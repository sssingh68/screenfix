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

# Hard-coded demo tenant — the only tenant allowed in this demo
DEMO_TENANT = "demo-msp"

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

# 3. Tool Declaration: execute_action
EXECUTE_ACTION_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="execute_action",
            description=(
                "Executes an approved runbook action against the simulated endpoint. "
                "Requires a valid approval_id that was approved by the L1 engineer in the console. "
                "The server will independently verify approval before running anything."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "runbook_id": types.Schema(
                        type=types.Type.STRING,
                        description="The ID of the approved runbook, e.g. 'vpn-error-809'"
                    ),
                    "ticket_id": types.Schema(
                        type=types.Type.STRING,
                        description="The ticket ID for this session, e.g. 'TKT-123456'"
                    ),
                    "approval_id": types.Schema(
                        type=types.Type.STRING,
                        description="The approval ID returned from request_approval, e.g. 'APP-ABCDEF'"
                    )
                },
                required=["runbook_id", "ticket_id", "approval_id"]
            )
        )
    ]
)

# Combined tools list for Gemini Live session
TOOLS = [MATCH_RUNBOOK_TOOL, REQUEST_APPROVAL_TOOL, EXECUTE_ACTION_TOOL]


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


# ---------------------------------------------------------------------------
# Simulated endpoint: called internally (same process, no HTTP round-trip)
# ---------------------------------------------------------------------------

async def _simulate_reset_vpn_profile() -> Dict[str, Any]:
    """Simulates a VPN profile reset. Waits 2 seconds to mimic real work."""
    await asyncio.sleep(2)
    return {"result": "success", "detail": "VPN profile re-created with company settings"}


# Map of action_id -> internal handler function
_SIMULATED_ACTIONS: Dict[str, Any] = {
    "reset_vpn_profile": _simulate_reset_vpn_profile,
}


async def execute_action(runbook_id: str, ticket_id: str, approval_id: str) -> Dict[str, Any]:
    """
    Executes an approved runbook action with full server-side verification.

    Server-side checks (never trusts Gemini's word):
      1. Approval doc must exist in Firestore.
      2. status must be "approved".
      3. tenant_id must match DEMO_TENANT.
      4. ticket_id and runbook_id must match what is in the approval doc.
      5. action_id from the skill's SKILL.md must match what was stored in the approval doc.

    If any check fails: writes a refused audit record and returns {"status": "refused", ...}.
    If all checks pass: runs the simulated action, writes a success audit record.
    """
    executed_at = datetime.now(timezone.utc).isoformat()

    print(f"[Tool] execute_action called: runbook_id='{runbook_id}', ticket_id='{ticket_id}', approval_id='{approval_id}'")

    # --- Step 1: Read approval document from Firestore ---
    doc_ref = db.collection("approvals").document(approval_id)
    doc = doc_ref.get()

    # Helper: write a refused audit record and return the refused response
    def _refuse(reason: str) -> Dict[str, Any]:
        audit = {
            "tenant_id": DEMO_TENANT,
            "ticket_id": ticket_id,
            "runbook_id": runbook_id,
            "action_id": "unknown",
            "approval_id": approval_id,
            "approved_by": "n/a",
            "executed_at": executed_at,
            "result": "refused",
            "reason": reason,
        }
        db.collection("audit_log").add(audit)
        print(f"[Audit] written (refused): {audit}")
        return {"status": "refused", "reason": reason}

    if not doc.exists:
        return _refuse("Approval document not found in Firestore.")

    data = doc.to_dict()

    # --- Step 2: Verify approval status ---
    if data.get("status") != "approved":
        return _refuse(f"Approval status is '{data.get('status')}', not 'approved'.")

    # --- Step 3: Verify tenant isolation ---
    if data.get("tenant_id") != DEMO_TENANT:
        return _refuse("Tenant mismatch — cross-tenant execution blocked.")

    # --- Step 4: Verify ticket_id and runbook_id match ---
    if data.get("ticket_id") != ticket_id:
        return _refuse(f"ticket_id mismatch: approval has '{data.get('ticket_id')}', got '{ticket_id}'.")
    if data.get("runbook_id") != runbook_id:
        return _refuse(f"runbook_id mismatch: approval has '{data.get('runbook_id')}', got '{runbook_id}'.")

    # --- Step 5: Verify action_id from SKILL.md matches the stored approval ---
    skill = skills.get_skill(runbook_id)
    if not skill:
        return _refuse(f"Skill '{runbook_id}' not found in loaded skills.")

    skill_action_id = skill.get("action_id", "")
    stored_action_id = data.get("action_id", "")

    if skill_action_id != stored_action_id:
        return _refuse(
            f"action_id mismatch: skill says '{skill_action_id}', approval stored '{stored_action_id}'."
        )

    action_id = skill_action_id
    approved_by = data.get("approved_by", "unknown")

    # --- Step 6: Run the simulated action ---
    handler = _SIMULATED_ACTIONS.get(action_id)
    if not handler:
        return _refuse(f"No simulated handler found for action_id '{action_id}'.")

    sim_result = await handler()

    # --- Step 7: Write success audit record (every field includes tenant_id) ---
    audit = {
        "tenant_id": DEMO_TENANT,
        "ticket_id": ticket_id,
        "runbook_id": runbook_id,
        "action_id": action_id,
        "approval_id": approval_id,
        "approved_by": approved_by,          # read from Firestore doc, never hardcoded
        "executed_at": executed_at,
        "result": sim_result.get("result", "unknown"),
        "detail": sim_result.get("detail", ""),
    }
    db.collection("audit_log").add(audit)
    print(f"[Audit] written: {audit}")

    response = {
        "status": sim_result.get("result", "unknown"),
        "detail": sim_result.get("detail", ""),
        "action_id": action_id,
        "ticket_id": ticket_id,
        "approval_id": approval_id,
    }
    print(f"[Tool] execute_action result: {response}")
    return response


def get_audit_log(tenant_id: str = "demo-msp", limit: int = 10) -> List[Dict[str, Any]]:
    """Returns the last `limit` audit records for the given tenant, newest first.

    Uses only a tenant_id filter (no order_by) to avoid requiring a composite Firestore index.
    Sorting is done in Python after fetching.
    """
    docs = (
        db.collection("audit_log")
        .where(filter=firestore.FieldFilter("tenant_id", "==", tenant_id))
        .stream()
    )
    records = [d.to_dict() for d in docs]
    # Sort by executed_at descending in Python, then take the latest `limit`
    records.sort(key=lambda r: r.get("executed_at", ""), reverse=True)
    return records[:limit]
