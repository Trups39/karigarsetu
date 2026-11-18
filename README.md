# KarigarSetu

[![Tests](https://github.com/Trups39/karigarsetu/actions/workflows/ci.yml/badge.svg)](https://github.com/Trups39/karigarsetu/actions/workflows/ci.yml)

**From the maker's bench to your shop shelf.**

KarigarSetu ("bridge to the artisan") lets shops order handmade Kolhapuri chappals in bulk **directly from the artisans who make them, on WhatsApp, in Marathi, Hindi or English**. Two Claude agents take care of the conversation. Plain code takes care of stock, prices and delivery dates. The artisan always has the final say.

Built for the **Claude × GoDaddy hackathon** (agentic business solutions for small businesses), running on GoDaddy: domain `karigarsetu.co.in`, Titan email and VPS hosting.

---

## The problem

- Kolhapuri chappals are a GI-tagged craft from Kolhapur. Artisans earn about ₹100–150 a pair, while luxury brands sell designs inspired by them for many times more.
- Shops order by phone call, and the artisan works it out from memory: what's in stock by size, what has to be made, and when it can be delivered. Orders get over-promised, sizes run short, and deliveries slip.
- Artisans have no website, no ordering system and no IT team. They already live on WhatsApp.

## The solution

```
 Shop (retailer)                     KarigarSetu                              Artisan (maker)
 ───────────────                     ───────────                              ───────────────
 WhatsApp: "मला क्लासिक       ──►   Sales Agent (Claude)                     
 50 जोड्या हव्यात"                    asks sizes, which maker
                                     checks stock + capacity (code)
                                     creates order KS-1041 ──────────────►   WhatsApp: "Approve? 1 / 2 / 3"
                                                                              or the dashboard
 "Confirmed: ₹27,500,          ◄──   order approved, stock reserved    ◄──   "1"  /  "rate 520 kar"
  delivery 24 Nov"                   (or counter-offer → shop says हो)        Operations Agent (Claude)
                                                                              "Size 9 Classic 12 jodi add kar"
```

- **Shops** order on WhatsApp in their own language. They tap "Order on WhatsApp" on a maker's card, or message the bot.
- **The Sales Agent** (Claude) understands the order, asks only for what's missing (sizes, which maker, shop name), checks ready stock and production capacity, and creates the order. It never promises a price or date: the maker confirms.
- **Makers** approve with one reply (`1` approve, `2` reject, `3` change), or talk naturally to the **Operations Agent** (Claude): "what's pending today?", "add 12 pairs of size 9 Classic", "KS-1041 is in production".
- **The website** gives makers a dashboard (orders, stock, capacity, designs, audit log) and the KarigarSetu team an admin page to approve new suppliers.

**The rule that makes it safe:** Claude only reads messages and calls tools. Stock, delivery dates, prices, order status and permissions are plain Python (`backend/app/services/`). The AI can't over-promise, skip the maker's approval, or see another maker's orders.

## Features

| Area | What it does |
|---|---|
| **WhatsApp ordering** | Meta WhatsApp Cloud API, Marathi / Hindi / English, quick replies `1 2 3` and YES/NO that work even without AI |
| **Two Claude agents** | Sales Agent (shops) and Operations Agent (makers), tool calling, per-agent memory, prompt caching, polite fallback if Claude is unavailable |
| **Production-aware feasibility** | Per size: ready vs to-make; delivery date from pairs per day, orders already booked and buffer days |
| **Order flow** | Awaiting maker → approved / counter-offer / rejected → in production → ready → delivered, with an audit log of every step |
| **Supplier onboarding** | "Become a supplier" sign-up → admin approval at `/admin` → email + password login → add designs and stock |
| **Maker dashboard** | Overview, orders (approve, reject, counter-offer, move forward), stock by size, capacity, designs and prices, audit log |
| **Contact form** | Website form → `contact@karigarsetu.co.in` through the Titan mailbox; the team is also emailed when a new supplier signs up |
| **Security** | bcrypt passwords, hashed session tokens, lockout after 5 wrong passwords, admin-only `/docs`, signed WhatsApp webhooks, the same field checks on page and server, no secrets in the repo |
| **Tests** | 105 unit tests (SQLite + PostgreSQL) and 27 agent scenarios run against the real Claude |

## Tech stack

| Layer | Technology |
|---|---|
| AI | Claude (Anthropic API), tool calling, prompt caching |
| Backend | Python 3, FastAPI, SQLModel |
| Database | PostgreSQL (SQLite for local development and tests) |
| Frontend | Plain HTML, CSS and JavaScript, served by the backend |
| WhatsApp | Meta WhatsApp Cloud API (webhook with HMAC-SHA256 signature check) |
| GoDaddy | Domain `karigarsetu.co.in`, DNS, Titan email (contact form and alerts), VPS hosting |

## Architecture

```
 WhatsApp (shops, makers) ──► Meta Cloud API ──► POST /webhooks/meta ─┐
                                                                      ▼
 Browser ──► https://karigarsetu.co.in ──► FastAPI (backend/app) ──► whatsapp.py: maker or shop?
   website, dashboard, /admin                │                        ├─ quick reply 1/2/3, YES/NO → services
                                             │                        ├─ shop  → agent.py     (Sales Agent)  ─┐
                                             │                        └─ maker → ops_agent.py (Ops Agent)   ─┤ Claude API
                                             ▼                                                               │
                                  services/  feasibility · orders · inventory · notify · mailer · audit ◄────┘ (tools)
                                             │
                                             ▼
                                        PostgreSQL            Titan SMTP (contact@karigarsetu.co.in)
```

## Project structure

```
karigarsetu/
├── README.md
├── .gitignore                      keeps .env, .venv, databases and test reports out of git
├── .github/workflows/ci.yml        GitHub Actions: secret check + all tests on SQLite and PostgreSQL, on every push
│
├── frontend/                       served by the backend at /
│   ├── index.html                  public site (Home, About, Contact), supplier sign-up and login, maker dashboard
│   ├── admin.html                  /admin: approve or reject new suppliers
│   └── assets/images/              photos used on Home and About
│
└── backend/
    ├── requirements.txt
    ├── .env.example                every setting, with comments (copy to .env)
    │
    ├── app/
    │   ├── main.py                 FastAPI app: API routes, dashboard API, webhooks, serves the frontend
    │   ├── config.py               reads settings from backend/.env
    │   ├── db.py                   database connection (PostgreSQL or SQLite)
    │   ├── models.py               database tables
    │   ├── seed.py                 loads db/*.sql   (python -m app.seed --reset)
    │   ├── schema_dump.py          writes db/schema.*.sql from models.py
    │   │
    │   ├── whatsapp.py             routes each incoming message: quick replies, Sales Agent or Ops Agent
    │   ├── agent.py                Sales Agent (shops) + the shared Claude tool-use loop
    │   ├── ops_agent.py            Operations Agent (makers)
    │   ├── meta_webhook.py         Meta webhook: signature check, message parsing, duplicate protection
    │   ├── i18n.py                 fixed WhatsApp messages in Marathi, Hindi and English
    │   │
    │   ├── auth.py                 maker sessions (Bearer token), internal API key
    │   ├── accounts.py             supplier sign-up, email + password login, admin approval
    │   ├── contact.py              website contact form
    │   ├── validation.py           field rules shared by every form (the page uses the same rules)
    │   │
    │   └── services/               the business rules (no AI here)
    │       ├── feasibility.py      ready vs to-make per size, earliest delivery date
    │       ├── orders.py           order status changes, approvals, counter-offers
    │       ├── inventory.py        stock, capacity, prices, buffer days
    │       ├── notify.py           outgoing WhatsApp messages (Meta)
    │       ├── mailer.py           outgoing email (Titan SMTP)
    │       └── audit.py            audit log
    │
    ├── db/
    │   ├── retailers.sql           sample shops
    │   ├── seed.sql                sample suppliers: makers, designs, stock, supplier accounts
    │   ├── demo_orders.sql         past orders for the sample suppliers
    │   ├── schema.postgres.sql     CREATE TABLE statements (reference, generated)
    │   └── schema.sqlite.sql
    │
    ├── tests/                      unit tests:  python -m pytest -q
    │   ├── conftest.py             test settings (never sends real WhatsApp or email)
    │   ├── test_flow.py            orders, feasibility, WhatsApp routing, agents (with a fake Claude)
    │   ├── test_accounts.py        sign-up, login, sessions, admin approval, /docs lock
    │   ├── test_contact.py         contact form, alert email, home page makers
    │   └── test_validation.py      field rules
    │
    └── agent_eval/                 agent tests with the REAL Claude:  python -m agent_eval.run
        ├── cases.json              27 scenarios (Sales Agent, Operations Agent, fallbacks)
        ├── run.py                  runs them on a temporary database, writes a report
        └── README.md
```

## Run it locally

Needs Python 3.11+.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1             # Mac/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
copy .env.example .env                   # Mac/Linux: cp .env.example .env   (then fill it in)
python -m app.seed --reset
python -m uvicorn app.main:app --reload
```

- **Website:** http://localhost:8000
- **Admin:** http://localhost:8000/admin (`ADMIN_EMAIL` + `ADMIN_PASSWORD` from `.env`)
- **API docs:** http://localhost:8000/docs (log in at `/admin` first)

**First run:** open *Supplier login → Become a supplier*, sign up with your WhatsApp number, approve yourself at `/admin`, log in, then add your designs (Products) and ready pairs (Stock).

The server reads `.env` only when it starts: after changing it, stop the server (Ctrl+C) and start it again. The startup log says which `.env` it read and whether email is on.

## Configuration (`backend/.env`)

All settings are listed with comments in `.env.example`. The main ones:

| Setting | What it is |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://user:password@host:5432/karigarsetu`, or SQLite by default |
| `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` | Claude for both agents |
| `WHATSAPP_PROVIDER=meta`, `META_WHATSAPP_TOKEN`, `META_PHONE_NUMBER_ID`, `META_APP_SECRET`, `META_VERIFY_TOKEN` | Meta WhatsApp Cloud API |
| `BOT_WHATSAPP_NUMBER` | The bot's number; "Order on WhatsApp" buttons open it |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Login for `/admin` (also locks `/docs`) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `CONTACT_TO` | Titan email for the contact form and alerts |
| `PUBLIC_URL`, `COOKIE_SECURE`, `INTERNAL_API_KEY` | Public address, HTTPS-only cookies, key for internal endpoints |
| `SAMPLE_MAKERS`, `SEED_DEMO_ORDERS`, `DEMO_RETAILER_PHONE`, `DEMO_MODE`, `DEMO_TODAY` | Sample data and demo options |

`backend/.env` holds real keys and passwords. It is in `.gitignore` and must never be committed.

## Data

Tables are created automatically from `app/models.py`. Starting data is in SQL files, loaded when the tables are created (first start, or `python -m app.seed --reset`):

- `retailers.sql`: 7 sample shops (Pune Footwear House becomes `DEMO_RETAILER_PHONE` if set)
- `seed.sql`: 2 sample suppliers, **Kolhapur Chappal Kendra** and **Patil Chappal Udyog**, with designs, stock by size and approved supplier accounts (no website login). Turn off with `SAMPLE_MAKERS=false`.
- `demo_orders.sql`: their past orders (`SEED_DEMO_ORDERS=false` to skip)

Your own maker is never in these files: sign up on the website and approve it at `/admin`. `--reset` wipes the data but **keeps supplier logins** and links them back to their maker by WhatsApp number (designs and stock need adding again).

## Tests

```powershell
cd backend
python -m pytest -q          # 105 unit tests; fake Claude, no real WhatsApp or email
python -m agent_eval.run     # 27 scenarios with the real Claude on a temporary database
```

The agent scenarios cover: full Marathi order flow with counter-offer; Hindi and English orders; minimum order, unknown size or design; asking which maker; a shop pushing a lower price; another shop's order; prompt injection; maker refusals (negative stock, past dates, skipping steps, another maker's order); capacity, buffer and language changes; quick replies; and fallbacks with Claude off or a wrong key. Each checks the database (order created or not, status, price, stock), not only the reply text.

To run the unit tests on PostgreSQL, set `TEST_DATABASE_URL` to an empty test database (it gets wiped).

**CI:** every push and pull request runs `.github/workflows/ci.yml` on GitHub Actions: a check that no `.env` or API key is committed, then all unit tests on SQLite and on a real PostgreSQL. The badge at the top shows the result.

## Connect WhatsApp (Meta Cloud API)

1. developers.facebook.com → your app → WhatsApp → **API Setup**: note the test number, *Phone number ID* and a token; add up to 5 phones under "Manage phone number list".
2. Fill in the `META_*` settings and `BOT_WHATSAPP_NUMBER` in `backend/.env`.
3. WhatsApp → **Configuration** → Webhook: Callback URL `https://<your-domain>/webhooks/meta`, Verify token = `META_VERIFY_TOKEN` → **Verify and save** → subscribe to **messages**.
4. Send "hi" from each phone (WhatsApp only lets the bot reply within 24 hours of the person's last message).

The test number can only reply to the registered phones, and its temporary token expires after about 24 hours. A verified business number and a permanent token remove both limits.

## API overview

| Who | Endpoint | Purpose |
|---|---|---|
| Public | `GET /public/makers`, `GET /public/info` | Home page makers (with WhatsApp links) and contact details |
| Public | `POST /api/contact` | Contact form → Titan email |
| Public | `POST /auth/signup` | Supplier sign-up (pending until approved) |
| Maker | `POST /auth/login`, `POST /auth/logout` | Email + password login (Bearer token) |
| Maker | `GET /api/overview`, `GET /api/orders`, `GET /api/orders/{code}` | Dashboard data |
| Maker | `POST /api/orders/{code}/approve`, `/reject`, `/counter`, `/advance` | Order decisions |
| Maker | `GET/PUT /api/stock`, `GET/POST /api/products`, `PATCH /api/products/{code}`, `PATCH /api/me` | Stock, designs, prices, capacity, buffer |
| Maker | `GET /api/retailers`, `GET /api/audit`, `GET /api/messages` | Shops, audit log, WhatsApp messages |
| Admin | `GET /admin`, `POST /api/admin/login`, `GET /api/admin/accounts`, `POST /api/admin/accounts/{id}/approve`, `/reject` | Supplier approvals (admin cookie) |
| Meta | `GET/POST /webhooks/meta` | Incoming WhatsApp messages |
| Internal | `POST /internal/simulate-message`, `/internal/orders`, `/internal/feasibility` | Testing and tools (header `X-Internal-Key`) |

## Before going live

- Strong `ADMIN_PASSWORD`, a new `INTERNAL_API_KEY` and `META_VERIFY_TOKEN`, `COOKIE_SECURE=true`, `PUBLIC_URL=https://karigarsetu.co.in`.
- PostgreSQL, HTTPS on the domain, and the Meta webhook pointing at it.
- `DEMO_MODE=false` once real makers use it (hides the "Simulate" buttons).

## Roadmap

WhatsApp OTP login · supplier verification (PAN, GST/Udyam, GI district, workshop video) · retailer accounts · maker subscriptions · UPI payment links · password reset by email · per-person admin logins · cheaper model routing for simple messages.
