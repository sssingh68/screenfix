# ScreenFix ⚡
> **Voice AI L1 IT Support Engineer for Managed Service Providers (MSPs)**  
> *Startup Buildathon India 2026 (Google DeepMind + Google Cloud)*

**Live Demo URL:** [https://screenfix-backend-357061753002.asia-south1.run.app](https://screenfix-backend-357061753002.asia-south1.run.app)  
- **Employee Portal:** [https://screenfix-backend-357061753002.asia-south1.run.app/](https://screenfix-backend-357061753002.asia-south1.run.app/)  
- **L1 Engineer Console:** [https://screenfix-backend-357061753002.asia-south1.run.app/console](https://screenfix-backend-357061753002.asia-south1.run.app/console)  

---

## 1. What ScreenFix Does

When an enterprise employee runs into an IT issue (such as a failing VPN connection), standard IT support requires opening tickets, waiting in queues, or struggling through complex diagnostic steps.

With **ScreenFix**, an employee starts a live voice call directly in their browser and shares the single window showing the error:
1. **Sees & Speaks:** Gemini Live sees the shared window in real-time, reads the error message (e.g. *VPN Error 809*), and explains what is wrong in plain English or Hindi over natural, low-latency voice.
2. **Matches Approved Runbook:** ScreenFix matches the visible issue against pre-approved IT runbooks defined as **Google Agent Skills**.
3. **Requests Human L1 Approval:** Before making any system changes, the agent requests human authorization. An approval card instantly appears in the MSP L1 Engineer Console.
4. **Executes & Audits Fix:** Once the human L1 engineer clicks **Approve**, the backend executes the approved remediation action, logs an immutable record in Cloud Firestore, and informs the employee over voice to retry.

---

## 2. Architecture

```
 ┌─────────────────────────┐                 ┌─────────────────────────┐
 │     Employee Browser    │                 │   L1 Engineer Console   │
 │   (Mic PCM + Screen)    │                 │  (Approvals & Audit Log)│
 └───────────┬─────────────┘                 └────────────▲────────────┘
             │                                            │
   WebSocket │ (/ws/live)                       HTTP Polling / POST
             │                                            │
 ┌───────────▼────────────────────────────────────────────┴────────────┐
 │                   FastAPI Backend on Cloud Run                      │
 │                     (asia-south1, max-instances=1)                  │
 │                                                                     │
 │   ┌───────────────────────┐             ┌───────────────────────┐   │
 │   │  WebSocket Bridge     │◄───────────►│  Tool Verification    │   │
 │   │  (live.py)            │             │  & State (tools.py)   │   │
 │   └───────────┬───────────┘             └───────────┬───────────┘   │
 └───────────────┼─────────────────────────────────────┼───────────────┘
                 │ Bi-directional Live Session         │ Reads / Writes
                 ▼                                     ▼
 ┌───────────────────────────────┐     ┌───────────────────────────────┐
 │   Gemini Live API             │     │      Google Cloud Firestore   │
 │   (gemini-3.8-live)           │     │   - approvals (pending/done)  │
 │   Voice + Screen + Tool Calls │     │   - audit_log (tenant-scoped) │
 └───────────────────────────────┘     └───────────────────────────────┘
```

---

## 3. Google Services Used (100% Google Stack)

ScreenFix uses exclusively Google Cloud & Google DeepMind technologies:

* **Gemini Live API (`gemini-3.8-live`):** Powers the interactive real-time voice and vision loop. Ingests 16kHz PCM audio and JPEG screen frames, maintains multi-turn conversation context, and invokes function calls without disconnecting.
* **Google Agent Skills:** Every IT runbook is codified in standard Agent Skills format (`.agents/skills/<runbook-name>/SKILL.md`), specifying metadata, required actions, and trigger conditions.
* **Google Cloud Firestore:** Cloud-native NoSQL database storing tenant-scoped collections for `approvals` and immutable `audit_log` records.
* **Google Cloud Run (`asia-south1`):** Serverless container hosting the FastAPI backend, configured with WebSocket support, session affinity, 3600-second connection timeouts, and strict single-instance routing to maintain in-memory approval notification events.
* **Google Cloud Secret Manager:** Manages sensitive API credentials (`GEMINI_API_KEY`). The container image contains zero secrets; credentials are mounted dynamically as environment variables at runtime.

---

## 4. Safety & Security Design

ScreenFix was engineered with strict guardrails to prevent AI hallucinations, prompt injections, and unauthorized system access:

1. **Strictly Constrained Toolset (Only 3 Tools):**  
   The voice agent has access to exactly three functions:
   * `match_runbook(issue_summary)`: Searches local runbook skills.
   * `request_approval(runbook_id, ticket_id)`: Registers a pending approval in Firestore.
   * `execute_action(runbook_id, ticket_id, approval_id)`: Triggers the remediation action.  
   *The agent cannot generate, invent, or run arbitrary shell commands.*
2. **Server-Side Approval Verification:**  
   The agent's word that an action was approved is never trusted. Before executing anything, `execute_action` validates independently against Firestore:
   * Document must exist in `approvals` collection.
   * Document status must strictly equal `"approved"`.
   * `tenant_id` must match `demo-msp` (cross-tenant isolation).
   * `ticket_id` and `runbook_id` must match the stored approval record.
   * `action_id` must match the action declared in the approved `SKILL.md`.  
   *If any check fails, the execution is refused and an audit record is written.*
3. **Screen Content is Untrusted Data:**  
   Screen frames and OCR text are treated purely as visual data. System instructions explicitly forbid the model from following instructions or overrides displayed on the user's screen.
4. **Immutable Audit Trail:**  
   Every match, approval decision, executed fix, and refused execution writes an audit log entry in Firestore with ticket ID, runbook ID, action ID, approver name, timestamp, and outcome.
5. **Multi-Tenant Isolation:**  
   Every Firestore query and write explicitly filters and enforces `tenant_id`.

---

## 5. What is Simulated in this Demo

To allow safe, reproducible hackathon evaluations without requiring access to real corporate Active Directory domains or client networks:
* **Simulated Remediation Endpoint:** Instead of making live PowerShell/WMI calls to reconfigure Windows Network Adapters or delete registry entries, `execute_action` calls `_simulate_reset_vpn_profile` (which pauses for 2 seconds to mimic real-world network profile re-creation before returning success).
* **Enterprise Endpoints:** Customer laptops and corporate Active Directory are represented by safe simulated models in the demo tenant `demo-msp`.

---

## 6. Local Development Guide

### Prerequisites
* Python 3.11+
* Google Cloud CLI (`gcloud`) installed and authenticated
* A valid Gemini API Key enabled for Gemini 2.0 / 3.x Live

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/sssingh68/screenfix.git
   cd screenfix
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   # Windows PowerShell:
   .venv\Scripts\Activate.ps1
   # macOS/Linux:
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment:**
   Create a `.env` file in the project root:
   ```env
   GEMINI_API_KEY="your-gemini-api-key"
   GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
   ```
   Authenticate Google Application Default Credentials for Cloud Firestore:
   ```bash
   gcloud auth application-default login
   ```

5. **Start the application:**
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

6. **Open in browser:**
   * **Employee Portal:** [http://localhost:8000](http://localhost:8000)
   * **L1 Console:** [http://localhost:8000/console](http://localhost:8000/console)

---

## 7. Project Structure

```
screenfix/
├── .agents/
│   └── skills/
│       └── vpn-error-809/
│           └── SKILL.md            # Google Agent Skill for VPN Error 809
├── static/
│   ├── employee.html               # Employee portal (mic capture + window share)
│   └── console.html                # L1 engineer approval & audit dashboard
├── Dockerfile                      # Cloud Run container definition
├── requirements.txt                # Python dependencies
├── skills.py                       # Agent Skill parser & loader
├── tools.py                        # Tool declarations, Firestore ops, and safety checks
├── live.py                         # Bidirectional Gemini Live WebSocket bridge
├── main.py                         # FastAPI web endpoints and router
└── README.md                       # Documentation
```
