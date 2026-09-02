# LECTIO — Complete Setup & Run Guide
## AI Course Curation Platform

---

## Table of Contents

1. [System Requirements](#1-system-requirements)
2. [Pre-Installation Checklist](#2-pre-installation-checklist)
3. [Get Your Free API Keys](#3-get-your-free-api-keys)
4. [Project Structure Overview](#4-project-structure-overview)
5. [Step-by-Step Installation](#5-step-by-step-installation)
6. [Environment Configuration](#6-environment-configuration)
7. [Running the Application](#7-running-the-application)
8. [First Login & Setup](#8-first-login--setup)
9. [Using LECTIO — Full Workflow](#9-using-lectio--full-workflow)
10. [Running Tests](#10-running-tests)
11. [Troubleshooting](#11-troubleshooting)
12. [Development Mode (Without Docker)](#12-development-mode-without-docker)
13. [Service Reference](#13-service-reference)
14. [Architecture Quick Reference](#14-architecture-quick-reference)

---

## 1. System Requirements

### Minimum
| Requirement | Minimum | Recommended |
|---|---|---|
| OS | Windows 10 / macOS 12 / Ubuntu 20.04 | Ubuntu 22.04 / macOS 14 |
| RAM | 8 GB | 16 GB |
| Disk | 10 GB free | 20 GB free |
| CPU | 4 cores | 8 cores |
| Docker | 24.0+ | Latest |
| Docker Compose | v2.20+ | Latest |
| Python (dev only) | 3.11+ | 3.11 |

### Network
- Internet access for initial setup (downloading Docker images and the BGE embedding model)
- After setup: runs 100% locally except for LLM API calls to Groq

---

## 2. Pre-Installation Checklist

Before starting, verify these are installed:

```bash
# Check Docker
docker --version
# Expected: Docker version 24.x.x or higher

# Check Docker Compose (v2 — note: no hyphen)
docker compose version
# Expected: Docker Compose version v2.x.x

# Check available disk space
df -h .
# Need at least 10 GB free

# Check available RAM
free -h          # Linux
vm_stat          # macOS
```

**Install Docker if not present:**
- **Windows/Mac:** https://www.docker.com/products/docker-desktop
- **Ubuntu:** `sudo apt-get install docker.io docker-compose-plugin`

---

## 3. Get Your Free API Keys

LECTIO requires two API keys. Both are **free**.

### 3.1 Groq API Key (LLM — Required)
Groq provides free access to Llama 3.3 70B — the model LECTIO uses for all agent reasoning and content generation.

**Free tier limits:** 30 requests/minute, 6,000 tokens/minute — sufficient for a university project.

Steps:
1. Go to **https://console.groq.com**
2. Click **Sign Up** (use your email or Google account)
3. Click **API Keys** in the left sidebar
4. Click **Create API Key**
5. Copy the key — it starts with `gsk_`
6. Save it — you will only see it once

### 3.2 LangSmith API Key (Monitoring — Optional but Recommended)
LangSmith traces every agent step, LLM call, and RAG retrieval. Invaluable for debugging.

Steps:
1. Go to **https://smith.langchain.com**
2. Sign up for a free account
3. Go to **Settings → API Keys**
4. Create a new API key
5. Copy the key — it starts with `ls__`

> **If you skip LangSmith:** set `LANGCHAIN_TRACING_V2=false` in your `.env` file. The application runs fine without it.

---

## 4. Project Structure Overview

```
lectio/
│
├── backend/                    ← FastAPI application (Python 3.11)
│   ├── main.py                 ← App entry point + router registration
│   ├── config.py               ← All settings (reads from .env)
│   ├── agents/                 ← LangGraph multi-agent system
│   │   ├── course_director.py  ← Supervisor / router agent
│   │   ├── metadata_content_agent.py
│   │   ├── content_assessment_agent.py
│   │   ├── alignment_agents.py
│   │   ├── content_generation_agent.py
│   │   ├── stakeholder_agent.py
│   │   └── graph/
│   │       ├── state.py        ← LangGraph state TypedDict
│   │       └── workflow.py     ← Compiled LangGraph graph
│   ├── rag/                    ← Full RAG pipeline
│   │   ├── parsers/            ← PDF, DOCX, PPTX, TXT, VTT
│   │   ├── chunking/           ← Semantic chunker
│   │   ├── embedding/          ← BGE embedder (local, free)
│   │   ├── retrieval/          ← BM25 + dense hybrid + reranker
│   │   ├── generation/         ← Grounded generator + citations
│   │   └── rag_service.py      ← Facade used by agents
│   ├── api/v1/routes/          ← All REST endpoints
│   ├── auth/                   ← JWT + bcrypt + RBAC
│   ├── db/                     ← SQLAlchemy models + repositories
│   ├── knowledge/              ← Bloom's taxonomy classifier
│   ├── services/               ← Upload, ingestion, workflow
│   └── vector_db/              ← ChromaDB client
│
├── frontend/                   ← Streamlit dashboard (Python)
│   ├── app.py                  ← Main app + navigation router
│   ├── pages/                  ← 8 dashboard pages
│   ├── components/             ← Shared UI widgets
│   ├── utils/                  ← Session management
│   └── api_client/             ← HTTP client for backend
│
├── tests/
│   ├── unit/                   ← 212 unit tests (no DB/API needed)
│   └── integration/            ← API tests (needs live DB)
│
├── docker/
│   ├── Dockerfile.backend      ← Backend container
│   └── Dockerfile.frontend     ← Frontend container
│
├── scripts/
│   └── seed_db.py              ← Creates first admin user
│
├── docker-compose.yml          ← Orchestrates all 5 services
├── requirements.txt            ← Backend Python deps
├── requirements-frontend.txt   ← Frontend Python deps
└── .env.example                ← Environment template
```

---

## 5. Step-by-Step Installation

### Step 1 — Clone / Extract the Project

```bash
# If you received a zip file:
unzip lectio.zip
cd lectio

# If from git:
git clone <your-repo-url>
cd lectio
```

### Step 2 — Create the Environment File

```bash
cp .env.example .env
```

Open `.env` in any text editor. You will fill in values in the next step.

### Step 3 — Generate Your Secret Key

```bash
# Linux / macOS:
openssl rand -hex 32

# Windows (PowerShell):
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output — it looks like:
`a3f8c2d1e4b7f9c0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4`

---

## 6. Environment Configuration

Open your `.env` file and fill in each value:

```bash
# ── Application ──────────────────────────────────────
APP_NAME=LECTIO
APP_ENV=development
DEBUG=true
LOG_LEVEL=INFO

# ── Database ─────────────────────────────────────────
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=lectio_db
POSTGRES_USER=lectio_user
POSTGRES_PASSWORD=YourStrongPassword123!      ← CHANGE THIS

DATABASE_URL=postgresql+asyncpg://lectio_user:YourStrongPassword123!@postgres:5432/lectio_db

# ── Redis ─────────────────────────────────────────────
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=YourRedisPassword456!          ← CHANGE THIS
REDIS_URL=redis://:YourRedisPassword456!@redis:6379/0

# ── ChromaDB ──────────────────────────────────────────
CHROMA_HOST=chromadb
CHROMA_PORT=8000
CHROMA_AUTH_TOKEN=YourChromaToken789!         ← CHANGE THIS

# ── Security ──────────────────────────────────────────
SECRET_KEY=<paste your openssl output here>   ← CHANGE THIS
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# ── Groq LLM (FREE) ───────────────────────────────────
GROQ_API_KEY=gsk_your_key_here               ← PASTE YOUR GROQ KEY
GROQ_MODEL=llama-3.3-70b-versatile

# ── LangSmith (Optional) ──────────────────────────────
LANGCHAIN_API_KEY=ls__your_key_here          ← PASTE IF YOU HAVE IT
LANGCHAIN_TRACING_V2=true                    ← Set false if no key
LANGCHAIN_PROJECT=lectio-dev

# ── Embeddings (local, no key needed) ─────────────────
EMBEDDING_MODEL=BAAI/bge-large-en-v1.5
EMBEDDING_DEVICE=cpu

# ── File Storage ──────────────────────────────────────
ARTIFACT_STORAGE_PATH=/app/uploads
MAX_UPLOAD_SIZE_MB=50

# ── Frontend ──────────────────────────────────────────
BACKEND_URL=http://backend:8000
```

**Rules for passwords:**
- Use at least 12 characters
- Include uppercase, lowercase, numbers, and a special character
- Do NOT use these exact example values in production

---

## 7. Running the Application

### 7.1 First-time startup (builds Docker images)

```bash
docker compose up --build
```

This command:
1. Pulls base Docker images (Python 3.11, PostgreSQL 15, Redis 7, ChromaDB)
2. Builds the backend image — **installs all dependencies + downloads the BGE embedding model** (~2 GB, takes 5–15 minutes on first run)
3. Builds the frontend image
4. Starts all 5 services
5. Runs database schema creation automatically

**You will see logs from all services scrolling. Wait until you see:**
```
lectio_backend  | INFO - LECTIO ready.
lectio_frontend | You can now view your Streamlit app in your browser.
```

### 7.2 Create the first admin user (one-time only)

Open a **new terminal window** while the services are running:

```bash
docker compose exec backend python ../scripts/seed_db.py
```

You will see:
```
Admin user created: admin@lectio.ac.za
   Password: Admin@Lectio2025!
   Change this password immediately after first login!
```

### 7.3 Open the application

| Service | URL | Notes |
|---|---|---|
| **Dashboard** | http://localhost:8501 | Main interface — open this |
| **API Docs** | http://localhost:8000/docs | Interactive Swagger UI |
| **API ReDoc** | http://localhost:8000/redoc | Alternative API docs |
| **ChromaDB** | http://localhost:8002 | Vector database |
| **PostgreSQL** | localhost:5432 | Use any Postgres client |

### 7.4 Subsequent startups (no rebuild needed)

```bash
# Start all services
docker compose up

# Start in background (detached mode)
docker compose up -d

# Stop all services
docker compose down

# Stop and delete all data (full reset)
docker compose down -v
```

### 7.5 View logs

```bash
# All services
docker compose logs -f

# Single service
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f postgres
```

---

## 8. First Login & Setup

### Step 1 — Login
1. Open http://localhost:8501
2. Email: `admin@lectio.ac.za`
3. Password: `Admin@Lectio2025!`

### Step 2 — Create your first Lecturer user
1. Click **Admin Panel** in the sidebar
2. Click **Users** tab
3. Click **Create New User**
4. Fill in:
   - Email: `lecturer@youruniversity.ac.za`
   - Full Name: `Dr Jane Smith`
   - Password: (choose a strong one)
   - Role: `lecturer`
5. Click **Create User**

### Step 3 — Create a Course
1. Click **Upload Course** in the sidebar
2. Click **New Course**
3. Fill in:
   - Code: `CS301`
   - Title: `Data Structures and Algorithms`
   - Level: `undergraduate`
   - Year: `2025`
   - Semester: `S1`
   - Credits: `16`
4. Click **Create Course**

### Step 4 — Add CLOs to the Course
1. Go to **API Docs** at http://localhost:8000/docs
2. Click **Authorize** → enter `Bearer <your_token>`
3. Call `POST /api/v1/courses/{id}/modules` to add a module
4. Call `POST /api/v1/courses/{id}/modules/{id}/clos` to add CLOs

Or use the course upload page to add modules and CLOs through the UI.

---

## 9. Using LECTIO — Full Workflow

### The Complete 5-Step Process

---

#### Step 1: Upload Course Artefacts

1. Navigate to **Upload Course**
2. Select your course from the dropdown
3. For each document:
   - Choose the **Artefact Type** (syllabus, slides, assignment, transcript, module_manual)
   - Click **Choose File** and select your file (PDF, DOCX, PPTX, TXT, or VTT)
   - Click **Upload & Process**
4. Watch the **processing status** indicator — it polls automatically
5. When you see `Processing complete — N chunks indexed`, the document is ready

**Supported file types:**

| Extension | Use for |
|---|---|
| `.pdf` | Module manuals, syllabi, assignments |
| `.docx` | Word documents — lecture notes, rubrics |
| `.pptx` | PowerPoint lecture slides |
| `.txt` | Plain text syllabi, reading lists |
| `.vtt` | Lecture video transcripts (from Zoom/Teams/YouTube) |

**Best practice — upload in this order:**
1. `module_manual` or `syllabus` first (defines CLOs and structure)
2. `slides` (lecture delivery)
3. `assignment` or `exam` papers
4. `transcript` if available

---

#### Step 2: Run Alignment Audit

1. Navigate to **Upload Course** -> **Run Audit** tab
2. Select your course
3. Click **Start Audit**
4. The status will cycle through:
   - `running` → agents are executing
   - `waiting_for_human` → audit complete, review needed
   - `completed` → no content generated (all gaps already addressed)

**What the audit checks:**
- **Metadata ↔ Content:** Every CLO in your syllabus is covered in your lecture slides/transcripts
- **Content ↔ Assessment:** What you teach is what you assess
- **Metadata ↔ Assessment:** Every CLO has at least one assessment question
- **Content ↔ Delivery:** Every topic is delivered in lectures in the right sequence

The audit typically takes **2–5 minutes** depending on the number of documents.

---

#### Step 3: Review Alignment Reports

1. Navigate to **Alignment Reports**
2. Select your course and the latest audit run
3. You will see:
   - **4 score cards** — one per alignment dimension (Pass / Warning / Fail)
   - **Radar chart** — visual overview of all dimensions
   - **Detailed tabs** — drill into each check
   - **Gap table** — every identified gap with severity and recommendation

**Score interpretation:**

| Score | Status | Action |
|---|---|---|
| >= 75% | Pass | No action needed |
| 55-74% | Warning | Review and consider improvements |
| < 55% | Fail | Significant gaps — address before teaching |

4. Click **Mark as Resolved** on individual gaps once you have addressed them manually

---

#### Step 4: Review Generated Content

1. Navigate to **Approval Center**
2. You will see AI-generated items waiting for your review:
   - **CLOs** — new or revised Course Learning Objectives
   - **Quiz questions** — multiple-choice questions at the correct Bloom's level
   - **Exercises** — practical activities for undelivered topics
   - **Assessment suggestions** — formal assessment questions for unassessed CLOs
3. For each item:

**Option A — Approve:**
Click Approve -> add an optional comment -> Confirm Approval

**Option B — Edit and Approve:**
Click Edit & Approve -> modify the content inline -> Submit Revision
Your edits are stored and influence future generations for your account.

**Option C — Reject:**
Click Reject -> provide a reason (required) -> Confirm Rejection
The reason is stored in episodic memory and future generations will avoid similar patterns.

---

#### Step 5: View Analytics

1. Navigate to **Analytics**
2. See:
   - Alignment scores across all your courses
   - Approval decision breakdown (how much was approved vs revised vs rejected)
   - Course artefact counts

---

### Knowledge Graph

Navigate to **Knowledge Graph** to see an interactive network visualisation of your course:
- **Purple nodes** = Course
- **Blue nodes** = Modules
- **Green nodes** = CLOs
- **Purple nodes** = Assessments

Use the checkboxes to show/hide CLOs and assessments. Use the depth slider to control how many topics are shown.

---

## 10. Running Tests

### Unit Tests (no database or API needed)

```bash
# From the project root:
cd lectio

# Install test dependencies
pip install pytest pytest-asyncio pytest-cov bcrypt python-jose[cryptography] pydantic-settings aiofiles rank-bm25 numpy

# Run all unit tests
cd backend && \
  SECRET_KEY=test_key_32chars_xxxxxxxxxxxxxxxxx \
  GROQ_API_KEY=dummy \
  POSTGRES_PASSWORD=dummy \
  REDIS_URL=redis://localhost \
  REDIS_PASSWORD=dummy \
  CHROMA_AUTH_TOKEN=dummy \
  DATABASE_URL=postgresql+asyncpg://x:x@localhost/x \
  python -m pytest ../tests/unit/ -v

# Expected: 212 passed, 0 failed
```

### Run a specific test file

```bash
python -m pytest ../tests/unit/test_auth.py -v
python -m pytest ../tests/unit/test_phase2.py -v
python -m pytest ../tests/unit/test_phase3.py -v
```

### Run tests with coverage report

```bash
python -m pytest ../tests/unit/ --cov=. --cov-report=html
# Open htmlcov/index.html in your browser
```

### Integration Tests (requires running services)

```bash
# With services running via docker compose:
docker compose exec backend python -m pytest ../tests/integration/ -v
```

---

## 11. Troubleshooting

### Problem: Docker build fails / takes too long
```bash
# The BGE model download (~1.3 GB) can time out on slow connections
# Solution: increase Docker timeout
DOCKER_BUILDKIT=1 docker compose build --no-cache backend
```

### Problem: `docker compose` command not found
```bash
# You may have the older docker-compose (with hyphen)
docker-compose up --build
# Or install Docker Desktop which includes Compose v2
```

### Problem: Port already in use
```bash
# Check what is using the port
lsof -i :8000    # backend
lsof -i :8501    # frontend
lsof -i :5432    # postgres

# Kill the process or change ports in docker-compose.yml
```

### Problem: Cannot connect to backend from frontend
```bash
# Check backend health
curl http://localhost:8000/health

# Check backend logs
docker compose logs backend --tail=50

# Most common cause: .env BACKEND_URL is wrong
# Inside Docker network it MUST be: http://backend:8000
# From your browser it is:          http://localhost:8000
```

### Problem: "No module named X" in backend
```bash
docker compose exec backend pip install <module_name>
# Or add to requirements.txt and rebuild:
docker compose build backend
```

### Problem: ChromaDB authentication error
```bash
# Check CHROMA_AUTH_TOKEN matches in .env
# The token must be the same value in both:
#   CHROMA_AUTH_TOKEN=...
#   (used by both backend and chromadb service)
docker compose restart chromadb backend
```

### Problem: Groq API rate limit (429 error)
```bash
# Free tier: 30 requests/minute
# The audit workflow makes ~10-15 LLM calls total
# If you hit limits, wait 1 minute and retry
# Or upgrade your Groq plan at console.groq.com
```

### Problem: Database migration errors
```bash
# Reset the database completely
docker compose down -v
docker compose up --build

# Re-seed
docker compose exec backend python ../scripts/seed_db.py
```

### Problem: "Upload failed: File content does not match type"
The system validates file magic bytes for security. Ensure:
- PDF files start with `%PDF`
- DOCX/PPTX files are valid ZIP-based Office files (not corrupted)
- The file is not renamed from a different format (e.g., `.txt` renamed to `.pdf`)

### Problem: Audit runs but no reports appear
```bash
# Check if artifacts were processed
# Go to Upload Course → Uploaded Artefacts
# Status should be "done" not "pending" or "error"

# Check agent run logs
docker compose logs backend | grep "WorkflowService\|Director\|Agent"
```

### Problem: BGE embedding model not found
```bash
# The model is downloaded during Docker build
# If it failed, re-run build:
docker compose build --no-cache backend

# Or pre-download manually:
docker compose exec backend python -c \
  "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-large-en-v1.5')"
```

### Full reset (start completely fresh)
```bash
docker compose down -v          # remove containers AND volumes
docker system prune -f          # remove dangling images
docker compose up --build       # rebuild from scratch
docker compose exec backend python ../scripts/seed_db.py
```

---

## 12. Development Mode (Without Docker)

If you prefer to run services directly on your machine:

### Prerequisites
```bash
# Install PostgreSQL 15
sudo apt-get install postgresql-15    # Ubuntu
brew install postgresql@15            # macOS

# Install Redis
sudo apt-get install redis-server     # Ubuntu
brew install redis                    # macOS

# Install Tesseract OCR (for scanned PDFs)
sudo apt-get install tesseract-ocr    # Ubuntu
brew install tesseract                # macOS

# Python 3.11
python3.11 --version
```

### Backend setup
```bash
cd lectio/backend

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate    # Linux/macOS
# venv\Scripts\activate     # Windows

# Install dependencies
pip install -r ../requirements.txt

# Set environment (edit .env first)
export $(cat ../.env | grep -v '^#' | xargs)

# Override service hosts for local dev
export POSTGRES_HOST=localhost
export REDIS_HOST=localhost
export CHROMA_HOST=localhost
export DATABASE_URL=postgresql+asyncpg://lectio_user:YourPassword@localhost:5432/lectio_db
export REDIS_URL=redis://:YourRedisPassword@localhost:6379/0

# Run database migrations
psql -U postgres -c "CREATE USER lectio_user WITH PASSWORD 'YourPassword';"
psql -U postgres -c "CREATE DATABASE lectio_db OWNER lectio_user;"
psql -U lectio_user -d lectio_db -f db/migrations/versions/001_initial.sql

# Start ChromaDB (run in separate terminal)
pip install chromadb
chroma run --host 0.0.0.0 --port 8002

# Start backend (with hot reload)
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Seed admin user (run once)
python ../scripts/seed_db.py
```

### Frontend setup
```bash
cd lectio/frontend

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r ../requirements-frontend.txt

# Set backend URL
export BACKEND_URL=http://localhost:8000

# Start Streamlit
streamlit run app.py --server.port 8501
```

---

## 13. Service Reference

### Services started by `docker compose up`

| Service | Container Name | Port | Purpose |
|---|---|---|---|
| PostgreSQL 15 | lectio_postgres | 5432 | Primary relational database |
| Redis 7 | lectio_redis | 6379 | Session cache + rate limiting |
| ChromaDB | lectio_chromadb | 8002 | Vector embeddings storage |
| FastAPI | lectio_backend | 8000 | REST API + agent orchestration |
| Streamlit | lectio_frontend | 8501 | Web dashboard |

### Useful Docker commands

```bash
# Get a shell inside the backend container
docker compose exec backend bash

# Run a Python command in backend
docker compose exec backend python -c "print('hello')"

# View database directly
docker compose exec postgres psql -U lectio_user -d lectio_db

# View ChromaDB collections
curl http://localhost:8002/api/v1/collections

# Restart a single service
docker compose restart backend

# Scale backend workers (if needed)
docker compose up --scale backend=2
```

### API Endpoints Quick Reference

```
Authentication:
  POST /api/v1/auth/login          — Get tokens
  POST /api/v1/auth/refresh        — Refresh access token
  POST /api/v1/auth/logout         — Revoke refresh token
  GET  /api/v1/auth/me             — Current user profile

Courses:
  GET  /api/v1/courses             — List courses
  POST /api/v1/courses             — Create course
  GET  /api/v1/courses/{id}        — Get course
  PATCH /api/v1/courses/{id}       — Update course

Artefacts:
  POST /api/v1/courses/{id}/artifacts        — Upload file
  GET  /api/v1/courses/{id}/artifacts        — List artefacts
  GET  /api/v1/courses/{id}/artifacts/{id}/status — Processing status
  DELETE /api/v1/courses/{id}/artifacts/{id} — Delete artefact

Agent Runs:
  POST /api/v1/courses/{id}/run-audit  — Start audit
  GET  /api/v1/runs/{run_id}           — Run status
  GET  /api/v1/runs/{run_id}/steps     — Step log

Reports:
  GET  /api/v1/courses/{id}/reports    — List reports
  GET  /api/v1/reports/{id}            — Full report with gaps

Approvals:
  GET  /api/v1/approvals               — Pending items
  POST /api/v1/approvals/{id}/approve  — Approve
  POST /api/v1/approvals/{id}/revise   — Edit and approve
  POST /api/v1/approvals/{id}/reject   — Reject

Admin:
  GET  /api/v1/admin/users             — List users
  POST /api/v1/admin/users             — Create user
  POST /api/v1/admin/users/{id}/roles  — Assign role
  GET  /api/v1/admin/audit-logs        — Audit trail
  GET  /api/v1/admin/system-stats      — System metrics
```

---

## 14. Architecture Quick Reference

```
Browser
  │ HTTP
  ▼
Streamlit (port 8501)
  │ REST API calls
  ▼
FastAPI (port 8000)
  │
  ├── Auth Layer (JWT + RBAC)
  │
  ├── Upload Service
  │     └── Saves file to disk → triggers background ingestion
  │
  ├── RAG Ingestion Pipeline (background)
  │     PDF/DOCX/PPTX Parser
  │       → Semantic Chunker
  │         → BGE Embedder (local, free)
  │           → ChromaDB (vectors)
  │           → PostgreSQL (chunk metadata)
  │           → BM25 index (in-memory)
  │
  ├── LangGraph Workflow (on audit trigger)
  │     Course Director Agent (supervisor)
  │       → Metadata↔Content Agent    → alignment score
  │       → Content↔Assessment Agent  → alignment score
  │       → Metadata↔Assessment Agent → alignment score
  │       → Content↔Delivery Agent    → alignment score
  │       → Content Generation Agent  → RAG-grounded content
  │       → Stakeholder Agent         → HITL queue
  │
  └── Persistence
        PostgreSQL 15  — users, courses, reports, approvals, audit logs
        ChromaDB       — document embeddings
        Redis          — session cache
```

### Technology choices explained

| Choice | Why |
|---|---|
| **Groq + Llama 3.3 70B** | Free, fast (500 tok/s), no credit card needed |
| **BAAI/bge-large-en-v1.5** | Best free embedding model; runs locally; no API cost |
| **LangGraph** | Explicit agent graph; conditional routing; native HITL; checkpointing |
| **ChromaDB** | Zero-config vector DB; Docker-friendly; production-migratable to Pinecone |
| **FastAPI** | Async; auto OpenAPI docs; Pydantic v2 validation |
| **Streamlit** | Python-native; data viz built-in; 10× faster to build than React |
| **PostgreSQL** | JSONB for flexible agent state; pgcrypto for security |

---

## Congratulations!

You now have a fully operational AI course curation system. If you encounter any issues not covered in this guide, check the logs first:

```bash
docker compose logs backend --tail=100
```

The most common issues are:
1. Missing or incorrect `.env` values (especially `GROQ_API_KEY`)
2. Port conflicts with other applications
3. Insufficient disk space for the BGE model

---

*LECTIO v1.0 — Built with FastAPI, LangGraph, Groq (Llama 3.3 70B), BGE Embeddings, ChromaDB, and Streamlit*
