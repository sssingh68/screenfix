import logging
from typing import Any, Dict
from google.genai import types
import skills

logger = logging.getLogger("screenfix.tools")

# Gemini tool declaration for match_runbook
MATCH_RUNBOOK_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="match_runbook",
            description=(
                "Searches approved runbooks for an IT error seen on screen or described by the user. "
                "Returns runbook_id, action_id, and title if matched, or runbook_id 'none'."
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


def match_runbook(issue_summary: str) -> Dict[str, Any]:
    """Matches an issue summary against loaded skills using keyword matching."""
    if not issue_summary:
        return {"runbook_id": "none"}

    summary_lower = issue_summary.lower()
    all_skills = skills.get_skills()

    best_match = None
    best_score = 0

    for s in all_skills:
        skill_id = s.get("id", "").lower()
        description = s.get("description", "").lower()
        title = s.get("name", s.get("id", ""))

        # Score matching: check presence of key tokens in summary
        score = 0
        tokens = set(skill_id.replace("-", " ").split() + description.replace('"', '').replace(".", "").split())
        for token in tokens:
            if len(token) >= 3 and token in summary_lower:
                score += 1

        # Direct error code / prominent keyword bonus (e.g. "809", "vpn")
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
            "title": best_match.get("name", best_match["id"])
        }

    return {"runbook_id": "none"}


if __name__ == "__main__":
    print("Testing match_runbook tool locally...")
    test_queries = [
        "VPN Error 809: connection to the remote computer could not be established",
        "User having trouble with VPN connection error 809",
        "Outlook is disconnected and offline",
        ""
    ]

    for q in test_queries:
        res = match_runbook(q)
        print(f"Query: '{q}' -> Result: {res}")
