# ReRoute

**Film it. Sell it.**

Record one video of your unused stuff. Nine AI agents identify every item, compete across five sale routes, and execute the winning strategy across marketplaces — automatically. You do nothing. Nothing goes to waste.

---

## How It Works

You record a single video on your phone, talking through your items naturally — what they are, their condition, any defects. ReRoute takes it from there.

1. **Intake** — Video uploads from your phone to the command center
2. **Condition Fusion** — Gemini 3.1 Pro watches the video and reads the transcript simultaneously, extracting structured item cards with specs, defects, and category labels
3. **Route Competition** — Five specialized agents evaluate every item concurrently, each proposing a bid with estimated value, confidence, effort, and speed
4. **Route Decision** — A decider agent scores all bids (45% value, 25% confidence, 15% effort, 15% speed) and picks the winner. Low-confidence bids trigger automatic delegation back to the originating agent for re-evaluation
5. **Asset Optimization** — OpenCV scores frame sharpness, Pillow auto-crops and normalizes exposure, rembg removes backgrounds. Up to 8 listing-ready images per item
6. **Execution** — Listings go live across eBay, Mercari, Facebook Marketplace, and Depop via platform adapters
7. **Unified Inbox** — All buyer conversations across all platforms, one place

## The Five Routes

Every item gets evaluated against all five. The best route wins.

| Route | What It Does | Example |
|-------|-------------|---------|
| **Return** | Detects new/open-box items still within the return window | Unopened AirPods → full refund |
| **Trade-In** | Gets guaranteed payouts from Apple, Best Buy, Decluttr, Gazelle | iPhone 13 with cracked screen → $180 Apple Trade-In |
| **Sell As-Is** | Searches eBay sold comps, estimates fair market value, accounts for condition and fees | Used PS5 controller → $42 on eBay |
| **Repair Then Sell** | Finds replacement parts on Amazon, calculates if repair cost < extra sale value | Replace $12 screen protector → unlock $60 more value |
| **Bundle Then Sell** | Identifies items worth more together than apart | Camera + lens + bag → $340 as kit vs $280 individual |

## Architecture

```
Phone (capture) ──video──► Mac Dashboard (command center)
                              │
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
              IntakeAgent  Bureau   FastAPI + WebSocket
                    │     (uAgents)
                    ▼
          ConditionFusionAgent ──► Gemini 3.1 Pro
                    │
         ┌──────┬───┼───┬───────┬───────┐
         ▼      ▼   ▼   ▼       ▼       ▼        ← concurrent evaluation
      Return  Trade  Resale  Repair   Bundle
      Agent   Agent  Agent   Agent    Agent
         │      │     │       │        │
         └──────┴─────┴───────┴────────┘
                       │
                RouteDeciderAgent ──► delegation loop (low confidence)
                       │
              ┌────────┼────────┐
              ▼        ▼        ▼
         Asset     Execution  Unified
         Studio    System     Inbox
                       │
              ┌────────┼────────┐
              ▼        ▼        ▼
            eBay    Mercari   FB / Depop
```

All nine agents run concurrently inside a single Fetch.ai **Bureau**. The five route agents evaluate items in parallel — not sequentially. The RouteDeciderAgent waits for all bids to arrive before scoring.

## Agents on Agentverse

ReRoute is built on [Fetch.ai's uAgents framework](https://fetch.ai/docs/guides/agents/getting-started-with-uagents). Every agent runs on the **testnet** with its own wallet address and communicates via typed Protocol messages.

| Component | How We Use It |
|-----------|---------------|
| **uAgents** | All 9 agents built with `uagents.Agent`, each with typed Protocols |
| **Bureau** | Single Bureau manages the full agent cluster, concurrent execution |
| **Mailbox** | ConciergeAgent registers with `mailbox=True` for Agentverse discovery |
| **Agentverse** | Concierge is publicly registered — anyone can find and message it |
| **ASI:One** | ConciergeAgent implements `chat_protocol_spec` for natural language interaction |
| **Delegation** | Low-confidence bids trigger `DelegationRequest` messages back to route agents |
| **Protocols** | Every inter-agent message is a typed Pydantic model — `RouteBidRequest`, `RouteDecisionResponse`, `DelegationRequest`, etc. |

The ConciergeAgent is the public face of the system. It connects to ASI:One (asi1-mini) with full context about processed items, route decisions, and bid histories — so users can ask "why did you choose trade-in for my iPhone?" and get a grounded answer.

## Technologies

| Layer | Technology | What It Does in ReRoute |
|-------|-----------|------------------------|
| **AI / Vision** | Gemini 3.1 Pro | Watches the full video + reads the transcript to extract item cards with specs, defects, and condition labels |
| **Agent Framework** | Fetch.ai uAgents + Bureau | 9 concurrent agents with typed message protocols, testnet wallets, and Agentverse registration |
| **Agent Chat** | ASI:One (asi1-mini) | Powers the ConciergeAgent's natural language interface via `chat_protocol_spec` |
| **Backend** | Python 3.10 + FastAPI + uvicorn | REST API + WebSocket for real-time job status streaming to the frontend |
| **Frontend (Dashboard)** | React 19 + Vite + Framer Motion | Animated command center with route ladders, comp galleries, and live agent status |
| **Frontend (Capture)** | Vanilla HTML + WebSocket | Minimal phone interface — tap to record, swipe to send |
| **Video Processing** | ffmpeg | Frame extraction from uploaded videos |
| **Image Intelligence** | OpenCV + NumPy | Sharpness scoring (Laplacian variance), duplicate frame rejection, quality ranking |
| **Image Optimization** | Pillow (PIL) | Auto-crop, exposure normalization, enhancement filters |
| **Background Removal** | rembg | Clean product cutouts for marketplace listings |
| **Marketplace APIs** | eBay Browse + Sell APIs | Comp search (sold listings), live listing creation, order management |
| **Parts Discovery** | Amazon PA-API | Finds replacement parts for repair-then-sell ROI calculation |
| **Trade-In Quotes** | Apple Trade-In API | Guaranteed device payout quotes |
| **Data Models** | Pydantic v2 | Typed models for items, bids, decisions, listings — shared across agents and API |
| **Configuration** | pydantic-settings | Environment-based config with `.env` support |
| **Storage** | In-memory + JSON persistence | Fast reads during processing, durable across restarts |

## Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+
- ffmpeg (`brew install ffmpeg` on macOS)

### Setup

```bash
cd ReRoute

# Automated setup
bash scripts/setup.sh

# Configure API keys
cp .env.example .env
nano .env   # Add at minimum: GEMINI_API_KEY

# Start everything (Bureau + API server)
python run.py
```

### Access

| Surface | URL |
|---------|-----|
| Mac Dashboard | `http://localhost:8080` |
| Phone Capture | `http://localhost:8080/phone/` |
| API Docs | `http://localhost:8080/docs` |

### Demo Mode

Set `DEMO_MODE=true` in `.env` to run with realistic mock data — no API keys needed.

## Environment Variables

See `.env.example` for a full template.

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes | Google AI Studio API key |
| `ASI_ONE_API_KEY` | For ASI:One | Fetch.ai ASI:One API key |
| `EBAY_APP_ID` | For live eBay | eBay developer app ID |
| `EBAY_CERT_ID` | For live eBay | eBay developer cert ID |
| `EBAY_DEV_ID` | For live eBay | eBay developer dev ID |
| `EBAY_OAUTH_TOKEN` | For live eBay | eBay OAuth token |
| `EBAY_SANDBOX` | No | `true` to use eBay sandbox (default) |
| `AMAZON_ACCESS_KEY` | For parts search | Amazon PA-API access key |
| `AMAZON_SECRET_KEY` | For parts search | Amazon PA-API secret key |
| `AMAZON_PARTNER_TAG` | For parts search | Amazon Associates partner tag |
| `API_PORT` | No | API server port (default `8080`) |
| `BUREAU_PORT` | No | uAgents Bureau port (default `8000`) |
| `DEMO_MODE` | No | `true` for mock data (default) |

Each agent requires a unique seed phrase — see `*_AGENT_SEED` entries in `.env.example`.

## Project Structure

```
ReRoute/
├── run.py                    # Entry point — starts Bureau + API server
├── backend/
│   ├── config.py             # Settings (pydantic-settings)
│   ├── server.py             # FastAPI + WebSocket
│   ├── models/               # Pydantic data models (items, bids, decisions, listings)
│   ├── protocols/            # uAgents message types (typed inter-agent communication)
│   ├── agents/               # 9 uAgents + Bureau orchestration
│   ├── systems/              # Transcript extraction, asset optimization, execution, inbox, route closer
│   ├── adapters/             # Platform adapters (eBay, Mercari, Facebook, Depop)
│   ├── services/             # External API clients (Gemini, eBay, Amazon)
│   └── storage/              # In-memory store with JSON persistence
├── frontend/
│   ├── phone/                # Capture interface (vanilla HTML + WebSocket)
│   └── mac/                  # Command center (React 19 + Vite + Framer Motion)
├── data/                     # Runtime data (uploads, frames, jobs)
└── scripts/
    └── setup.sh              # Automated environment setup
```

## Built for the Fetch.ai AI Agent Hackathon

ReRoute demonstrates what becomes possible when autonomous agents collaborate on a real-world problem. Nine agents. Five competing routes. One video. Zero effort.
