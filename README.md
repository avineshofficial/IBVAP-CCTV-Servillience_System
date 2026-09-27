# IBVAP-CCTV-Servillience_System

## Intelligent Border Video Analytics Platform (IBVAP)

> **SIH 2026 · Problem Statement 26187 · Ministry of Home Affairs — Sashastra Seema Bal (SSB)**

AI-powered surveillance platform that transforms existing IP-based CCTV at Border Out Posts (BOPs) into an intelligent detection and alerting network — no dedicated smart-camera hardware required.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- npm

### 1. Install Python Dependencies
```bash
cd ibvap
pip install -r requirements.txt
```

### 2. Setup Models & Sample Data
```bash
python scripts/download_models.py
```

### 3. Start the Core Backend
```bash
python -m core.main
```
The API will be available at `http://localhost:8000` with docs at `http://localhost:8000/docs`.

### 4. Start the Dashboard
```bash
cd web/dashboard
npm install
npm run dev
```
Dashboard at `http://localhost:3000`.

### 5. Run the Edge Pipeline
```bash
# In a new terminal
python -m edge.main --source sample
```

### One-Click Demo
```bash
bash scripts/run_demo.sh
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────┐
│              EDGE LAYER (Per BOP)               │
│  Camera → Detection → Tracking → Fence → Alert │
│  YOLO26   ByteTrack    Homography   Rules       │
│         → Face (SCRFD+ArcFace)                  │
│         → ANPR (PaddleOCR)                      │
│         → Night Enhancement (CLAHE)             │
│         → Activity Detection (Rules)            │
│  [SQLite Buffer] ──→ [Sync Agent]               │
└───────────────────────┬─────────────────────────┘
                        │ mTLS, metadata first
┌───────────────────────▼─────────────────────────┐
│              CORE PLATFORM (HQ)                 │
│  Ingestion API → Alert Engine → Dashboard API   │
│  Watchlist Matching   Audit Hash-Chain           │
│  [PostgreSQL/SQLite]  [WebSocket Alerts]         │
└───────────────────────┬─────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────┐
│              WEB DASHBOARD                      │
│  Next.js + TypeScript + Tailwind CSS            │
│  Live Feed │ Alert List │ Map │ Audit Viewer    │
└─────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
ibvap/
├── edge/                  # Edge inference engine
│   ├── ingestion/         # Camera capture (RTSP/file/webcam)
│   ├── inference/         # AI models
│   │   ├── detection.py   # YOLO26 human + vehicle
│   │   ├── tracking.py    # ByteTrack MOT
│   │   ├── face.py        # InsightFace (SCRFD + ArcFace)
│   │   ├── anpr.py        # PaddleOCR + Indian plate validation
│   │   ├── night_enhance  # CLAHE low-light enhancement
│   │   └── activity.py    # Suspicious behavior rules
│   ├── fence/             # Virtual fence engine
│   ├── buffer/            # Local SQLite buffer
│   └── sync_agent/        # Edge-to-core sync
├── core/                  # Central platform (FastAPI)
│   ├── alert_engine/      # Confidence gating + dedup
│   ├── audit_chain/       # SHA-256 hash-chain ledger
│   ├── watchlist_service/ # Face/plate matching
│   ├── dashboard_api/     # REST + WebSocket
│   └── auth/              # JWT + RBAC
├── web/dashboard/         # Next.js dashboard
├── ml/                    # Models & datasets
└── scripts/               # Setup & demo scripts
```

---

## 🎯 8 Capability Pipelines

| # | Capability | Status | Model/Approach |
|---|---|---|---|
| 1 | Human Detection & Tracking | ✅ | YOLO26n + ByteTrack |
| 2 | Vehicle Detection & Classification | ✅ | YOLO26n (car/truck/bus/motorcycle) |
| 3 | Face Detection & Recognition | ✅ | InsightFace (SCRFD + ArcFace) |
| 4 | ANPR | ✅ | PaddleOCR + Indian plate regex validation |
| 5 | Virtual Fence Intrusion | ✅ | Homography + polygon/line-cross/dwell rules |
| 6 | Suspicious Activity | ✅ | Rule-based (loiter/crawl/sprint/group) |
| 7 | Night-time Enhancement | ✅ | CLAHE + gamma correction + denoising |
| 8 | Real-time Alerts & Audit Trail | ✅ | SHA-256 hash-chain + WebSocket |

---

## 🔐 Tamper-Evident Audit Trail

Every alert is SHA-256 hashed and chained — altering any past record breaks every hash after it.

**Live Demo:**
1. Create alerts through the system
2. View the audit chain at `GET /api/v1/audit/chain`
3. Verify chain integrity: `GET /api/v1/audit/verify-all` → ✅ PASS
4. Tamper with a record: `POST /api/v1/audit/demo-tamper/{id}`
5. Re-verify: `GET /api/v1/audit/verify-all` → ❌ CHAIN BROKEN

---

## 👥 Demo Credentials

| Username | Password | Role |
|---|---|---|
| admin | admin123 | Admin |
| commander | commander123 | Post Commander |
| analyst | analyst123 | HQ Analyst |
| officer | officer123 | Field Officer |

---

## 📊 API Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/edge/sync` | Edge → Core event sync |
| GET | `/api/v1/cameras` | List cameras |
| GET | `/api/v1/alerts` | Filter alerts |
| PATCH | `/api/v1/alerts/{id}` | Acknowledge/resolve |
| GET | `/api/v1/audit/verify-all` | Verify hash chain |
| POST | `/api/v1/watchlist` | Add watchlist entry |
| GET/POST | `/api/v1/zones` | Virtual fence management |
| WS | `/ws/alerts` | Live alert stream |

Full API docs at `http://localhost:8000/docs`

---

## 📜 License

Prototype for SIH 2026. See architecture document for licensing notes on dependencies (Ultralytics AGPL-3.0, InsightFace model restrictions).
