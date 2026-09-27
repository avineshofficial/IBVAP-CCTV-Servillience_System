# IBVAP — Phase 2 Development Plan
**Status check + wiring/hardening pass, following the original architecture doc**

This picks up where `IBVAP-Architecture.md` left off. Phase 1 (initial build) is
substantially done — this document records what's been verified working, what
was just fixed, and what's left, so development can continue without
re-discovering any of this by trial and error.

---

## 1. Verified working (tested end-to-end, not just reviewed)

| Component | Verified by |
|---|---|
| Edge detection + tracking (YOLO + ByteTrack) | Ran `edge.main` with real weights against the sample video — real bounding boxes, real track IDs, not simulation mode |
| Virtual fence breach detection | Same run produced real fence-breach alerts from real detections |
| Face detection (SCRFD) | `insightface` installed and initialized successfully in a live run |
| ANPR (YOLO + PaddleOCR) | `paddlepaddle`/`paddleocr` installed and initialized successfully |
| Local buffer + sync agent | `SyncAgent.sync_batch()` run directly against a live core instance — event + alert synced successfully |
| Core platform (FastAPI) | Boots cleanly, seeds 4 cameras + 4 users, all routes registered |
| Audit hash-chain | Synced alert's chain verified via `/api/v1/audit/verify-all` → `verified: true` |
| Core REST API | `/api/v1/stats`, `/cameras`, `/zones`, `/watchlist` (GET+POST), `/security/stats`, `/security/logs`, `/security/rbac-matrix`, `/security/dpdp-compliance` all hit directly and returned correct data |
| Dashboard API client | `src/lib/api.ts` (below) type-checked clean and every function verified against a live core response |

## 2. Fixed this session

1. **`requirements.txt`** — the real ML libraries (`ultralytics`, `insightface`, `paddleocr`, `torch`) were commented out under "Optional." Without them, `edge/inference/tracking.py` silently runs 4 hardcoded fake objects instead of your camera feed. Now uncommented — `pip install -r requirements.txt` gives you real detection by default.
2. **`edge/ingestion/camera.py`** — was a single synchronous read loop with no buffer cap. Fine for the demo video, but on a real RTSP stream, once detection+face+ANPR are all running per frame, OpenCV's internal buffer grows and the feed drifts behind real time. Rewritten so RTSP/webcam sources get a background thread that always exposes only the *latest* frame; file sources keep their original paced playback untouched.
3. **`web/dashboard/src/lib/api.ts` — did not exist.** Every dashboard page (`alerts`, `analytics`, `audit`, `cameras`, `security`, `watchlist`) imports from `@/lib/api`, but the file was never created — the dashboard could not have built. This was the single biggest blocker to seeing anything real in the UI. Full client built and verified against every live endpoint it calls; two real signature mismatches were caught and fixed in the process (`getSecurityLogs` was missing its `limit`/`severity` params; `addWatchlistEntry`'s type was stricter than the form component that calls it).

## 3. Known gaps — prioritized

### 3.1 Zones exist on the edge but never reach the core (do this before your next demo)
Core seeds 4 cameras and 4 users on startup, but **no zones** — `/api/v1/zones` returns `[]` until something POSTs to it. The edge pipeline evaluates fence rules against its own local zone config, but the core platform (and therefore the dashboard's camera/zone view) has no idea those zones exist. Fix: either (a) have `edge/main.py` POST its configured zones to `/api/v1/zones` once at startup, or (b) make zone definitions live in core and have the edge pipeline pull them down instead of hardcoding demo zones locally. (b) is the architecturally cleaner option since core is meant to be the source of truth an operator configures from the dashboard.

### 3.2 Watchlist hashing uses plain SHA-256, not HMAC
`core/main.py`'s `add_watchlist_entry` does `hashlib.sha256(entry.reference_data.encode())` with no secret key. For a value with a constrained format — a license plate especially — a plain hash is reversible via a precomputed dictionary/rainbow-table attack (a fixed format means an attacker can just hash every possible plate and match). The architecture doc's security section (§12.9) specced salted HMAC-SHA256 for exactly this reason. Fix: add a `WATCHLIST_HASH_SECRET` to core config/`.env`, and switch to `hmac.new(secret, entry.reference_data.encode(), hashlib.sha256).hexdigest()`.

### 3.3 Connect a real camera + calibrate real zones
Everything above has only been exercised against the bundled sample video. Next concrete step: point `CAMERA_SOURCE` at your actual RTSP URL, and re-define zones in `edge/config.py` (or via 3.1's fix, through the dashboard) to match your camera's actual field of view instead of the demo coordinates.

### 3.4 Minor / cosmetic
- `edge/config.py` defaults to `yolo11n.pt`; the architecture doc specs `yolo26n.pt`. Both work — only matters if you want the pitch deck and running code to match exactly.
- `edge/main.py`'s face-detector init logs "Face detector loaded" even on the path where `insightface` fails to import and it silently falls back — the pipeline handles this correctly either way, but the log line is misleading during debugging.
- The dashboard has not been through a full `npm install && npm run build` in this environment (disk-constrained sandbox) — `api.ts` is verified correct by type-check + live-endpoint cross-check, but a real build pass is worth running once to catch anything a static check can't (unused imports treated as errors under Next's strict mode, etc.).

## 4. Suggested order of work from here
1. Fix 3.1 (zones) and 3.2 (HMAC) — both are small, contained changes.
2. Run `npm install && npm run dev` for real and click through all 6 dashboard pages against a live core instance; fix anything a real browser catches that static checking couldn't.
3. Connect your real camera (3.3), re-calibrate zones for its actual view.
4. Only then: activity-detection tuning, cross-camera re-ID, and the rest of the Phase 3 items already listed in `IBVAP-Architecture.md` §17.

---
*This file, `IBVAP-Architecture.md`, and the two fixed files from earlier in this session are the full current spec — hand all of them to Antigravity together so it has the complete picture rather than just the newest piece.*
