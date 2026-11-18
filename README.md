# KarigarSetu

AI-powered B2B ordering for Kolhapuri chappal makers: retailers order on WhatsApp, the Claude Sales Agent drafts the order, the backend checks stock and production capacity, and the maker approves it from WhatsApp or the dashboard.

**Rule:** Claude only reads messages and calls tools. Stock, dates, prices, order status and permissions are plain Python in `backend/app/services/`.

## Two agents

| | Sales Agent | Operations Agent |
|---|---|---|
| Who talks to it | Retailers (shops) | Makers |
| Where | WhatsApp | WhatsApp |
| What it does | Understands orders in Marathi, Hindi or English, asks for missing sizes or shop details, checks stock and delivery date, sends the order to the maker | Answers "what's pending?", updates stock ("Size 8 Classic 10 jodi add kar"), approves or changes orders ("KS-1042 approve kar, pan delivery 5 December"), sets capacity, price and buffer days |
| Code | `app/agent.py` | `app/ops_agent.py` |

Both are Claude using tools (tool calling), sharing one loop (`run_agent_loop`) and per-phone conversation memory. Their tools call the same services as the dashboard, so they **can't** break the rules: a maker's agent only sees that maker's orders, stock can't go negative, a delivery date can't be in the past, and a price change must go to the retailer as a counter-offer. Every change the Operations Agent makes is logged as `agent.action` (and refusals as `agent.failed`) next to the normal audit entry.

Makers' quick replies `1`, `2` and `3` skip the AI entirely, so approvals work even if Claude is unavailable.

## Languages

- **Claude's replies** (both agents) are written in whatever language the person uses: Marathi, Hindi, English or a mix.
- **Fixed messages** (approval requests, confirmations, counter-offers, status updates, help text) come in Marathi, Hindi and English, from `backend/app/i18n.py`:
  - **Makers** get their `language` setting (Marathi by default; set in `db/seed.sql`, by `PATCH /api/me`, or by telling the Operations Agent "messages English madhe pathav").
  - **Retailers** get the language the Sales Agent detected when they ordered (saved on the order and the shop).
  - **Unknown numbers** get a guess from the words they used.
- Dates and sizes are localized too (24 नोव्हेंबर 2026 / 24 नवंबर 2026 / 24 Nov 2026).
- To change any wording, edit `app/i18n.py` and keep the `{placeholders}` the same in all three languages (a test checks this).

## Folder structure

```
karigarsetu/
├── README.md
├── CHANGES.md                    what changed in the latest version
├── .gitignore
├── frontend/                     website + maker dashboard
│   ├── index.html                Home, About, Contact, Supplier sign-up + login, Dashboard
│   ├── admin.html                Admin: approve or reject new suppliers (/admin)
│   └── assets/images/            photos used on Home and About
└── backend/                      FastAPI server (also serves the frontend)
    ├── requirements.txt
    ├── .env.example              settings: database, Claude key, Meta WhatsApp, admin login, demo options
    ├── db/
    │   ├── retailers.sql         sample shops (SQLite + PostgreSQL)
    │   ├── seed.sql              sample suppliers: makers, designs, stock, supplier accounts
    │   ├── demo_orders.sql       past orders and audit history for the sample suppliers
    │   ├── schema.sqlite.sql     CREATE TABLE statements (reference; generated)
    │   └── schema.postgres.sql   same for PostgreSQL
    ├── app/
    │   ├── main.py               API routes, WhatsApp webhook, serves frontend at /
    │   ├── models.py             database tables
    │   ├── config.py             reads settings from environment variables
    │   ├── db.py                 database connection
    │   ├── auth.py               maker sessions (Bearer token), internal key
    │   ├── accounts.py           supplier sign-up, email + password login, admin approval
    │   ├── agent.py              Sales Agent (retailers) + shared agent loop
    │   ├── ops_agent.py          Operations Agent (makers)
    │   ├── whatsapp.py           routes incoming messages (maker, retailer, agents)
    │   ├── meta_webhook.py       Meta WhatsApp: signature check, message parsing
    │   ├── i18n.py               fixed messages in Marathi, Hindi, English
    │   ├── seed.py               loads db/*.sql (python -m app.seed --reset)
    │   └── services/
    │       ├── feasibility.py    ready vs to-make, delivery date
    │       ├── orders.py         order statuses, audit entries, messages
    │       ├── inventory.py      stock, capacity, price, buffer days
    │       ├── notify.py         outgoing WhatsApp (Meta Cloud API, or stored only)
    │       └── audit.py
    ├── tests/                    unit tests (python -m pytest -q)
    │   ├── conftest.py           test settings
    │   ├── test_flow.py          end-to-end tests
    │   └── test_accounts.py      sign-up, login, sessions, admin approval
    └── agent_eval/               agent tests with the real Claude (python -m agent_eval.run)
        ├── cases.json            scenarios: Sales Agent, Operations Agent, fallbacks
        └── run.py                runs them on a temporary database and writes a report
```

## Run it

**Windows (PowerShell)**
```powershell
cd karigarsetu\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

**Mac / Linux**
```bash
cd karigarsetu/backend
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

For a repeatable demo date, put `DEMO_TODAY=2026-11-16` in `backend/.env`.

- **Website and dashboard:** http://localhost:8000/
  Sample suppliers (Kolhapur Chappal Kendra, Patil Chappal Udyog) and sample shops are loaded with the tables. **Your own maker is not preset:** **Become a supplier** with your WhatsApp number, approve yourself at `/admin`, log in with your email and password, then add your designs (Products) and ready pairs (Stock). "Simulate new WhatsApp order" then creates a sample order from Pune Footwear House.
- **Admin (approve new suppliers):** http://localhost:8000/admin with `ADMIN_EMAIL` + `ADMIN_PASSWORD` from `backend/.env`
- **API docs:** http://localhost:8000/docs (once `ADMIN_PASSWORD` is set, log in at `/admin` first)
- **Unit tests:** `python -m pytest -q` (run from `backend/`)
- **Agent tests with the real Claude:** `python -m agent_eval.run` (see `backend/agent_eval/README.md`)

## Mock data

Mock data lives in SQL files, not in the code:

All loaded automatically when the tables are created (first start, or `python -m app.seed --reset`):

- `backend/db/retailers.sql`: 7 sample retailers (shops)
- `backend/db/seed.sql`: 2 sample suppliers (makers, 6 designs, stock by size, and approved supplier accounts with **no website login**). Turn off with `SAMPLE_MAKERS=false`.
- `backend/db/demo_orders.sql`: 4 past orders for the sample suppliers (`SEED_DEMO_ORDERS=false` to skip)

Your own maker is never in these files: sign up on the website and approve it at `/admin`.

The server loads them automatically the first time it starts with an empty database. To start again from a clean state, for example before a demo:

```
python -m app.seed --reset
```

**Tables** are created automatically from `app/models.py` (by the server on start, or by `--reset`), so you never have to run `CREATE TABLE` yourself. For reading or creating them by hand (e.g. in pgAdmin), `db/schema.sqlite.sql` and `db/schema.postgres.sql` contain the full `CREATE TABLE` statements. After changing `app/models.py`, regenerate them with `python -m app.schema_dump`.

Set `SEED_DEMO_ORDERS=false` in `backend/.env` to skip the past orders. To add a maker, product or shop, edit the SQL file and run `--reset`. Rows are linked by phone number and product code, so you never need to write ids.

The past orders never use Kolhapuri Classic, so the live demo order (Pune, Classic, 50 pairs) always gives 20 ready, 30 to make, 24 Nov.

`frontend/index.html` also works when opened on its own (as a file or the published prototype). Without the server, it uses built-in sample data.

## Use PostgreSQL instead of SQLite

SQLite is the default and needs no setup. To use PostgreSQL on your machine:

1. **Install PostgreSQL** from https://www.postgresql.org/download/ (on Windows, use the EDB installer and remember the password you set for the `postgres` user). pgAdmin comes with it, so you can browse the data.
2. **Create the database.** In pgAdmin: right-click Databases → Create → Database → name it `karigarsetu`. Or in a terminal:
   ```
   psql -U postgres -c "CREATE DATABASE karigarsetu;"
   ```
3. **Point the app at it.** In `backend/.env`:
   ```
   DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/karigarsetu
   ```
   If the password has special characters such as `@`, `#` or `/`, URL-encode them (`@` → `%40`, `#` → `%23`, `/` → `%2F`).
4. **Install the driver and load the data** (from `backend/`):
   ```
   python -m pip install -r requirements.txt
   python -m app.seed --reset
   python -m uvicorn app.main:app --reload
   ```

The same `seed.sql` and `demo_orders.sql` work on both databases. If the app can't connect, it prints which address it tried and what to check.

To run the tests on PostgreSQL, create a second empty database, e.g. `karigarsetu_test` (the tests wipe it), and run:
```
# PowerShell
$env:TEST_DATABASE_URL="postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/karigarsetu_test"; python -m pytest -q
```

## How an order moves

```
retailer WhatsApp ──> /webhooks/meta ──> Sales Agent (Claude + tools)
                                                 │ check_feasibility, create_order
                                                 ▼
                        awaiting_maker ──(maker replies 1 / dashboard)──> approved ──> in_production ──> ready ──> delivered
                              │  └─(3 = change)──> counter_offered ──(retailer YES)──> approved
                              │                          └─(retailer NO)──> rejected
                              └─(2)──> rejected
```

Each step writes to the audit log and sends a WhatsApp message (stored in the `message` table, and sent through Meta when it's set up).

## Feasibility (backend/app/services/feasibility.py)

For each size: `ready = min(stock, ordered)`, `to_make = ordered - ready`.
`days = ceil((pairs already booked + to_make) / pairs_per_day) + buffer_days` (or 1 day if everything is in stock).

The Pune example (Classic, sizes 7:15, 8:20, 9:15) gives 20 ready, 30 to make, ready by 24 Nov 2026.

## Supplier accounts and login

1. A maker opens **Become a supplier** (`/#signup`, also linked from Login and Contact) and enters name, business, craft, town, WhatsApp number, email and password. The account is **pending**.
2. Logging in while pending shows *"Your account is under review"*.
3. The KarigarSetu team opens **/admin**, logs in with `ADMIN_EMAIL` + `ADMIN_PASSWORD` and clicks **Approve**. This creates the maker (or links the existing maker with the same WhatsApp number) and sends them a WhatsApp message. **Reject** blocks the login and logs them out.
4. The maker logs in with email + password and sees only their own orders, stock and audit log. Their WhatsApp number is the one the Operations Agent recognises.
5. `python -m app.seed --reset` wipes the data but **keeps supplier logins**, and links them again to the maker with the same WhatsApp number. Sign up once; no need to sign up again after a reset.

Rules: passwords are hashed with bcrypt; 5 wrong passwords lock the account for 15 minutes; errors don't reveal which emails exist; the login lasts 14 days (`SUPPLIER_SESSION_DAYS`) on that device, in every tab, until **Log out**; only one login (supplier or admin) per browser at a time; `/docs` is admin-only once `ADMIN_PASSWORD` is set. WhatsApp webhooks and `/internal/*` (key-protected) are unchanged.

## Main endpoints

| Who | Endpoint | What it does |
|---|---|---|
| Public | `GET /public/makers` | Makers, designs and WhatsApp links |
| Public | `POST /auth/signup` | Supplier sign-up (name, business, craft, town, WhatsApp number, email, password); account starts **pending** |
| Maker | `POST /auth/login`, `POST /auth/logout` | Email + password login (only once approved), returns a token |
| Admin | `GET /admin`, `POST /api/admin/login`, `GET /api/admin/accounts`, `POST /api/admin/accounts/{id}/approve`, `/reject` | Approve or reject new suppliers (admin cookie) |
| Maker | `GET /api/overview` | Dashboard numbers and recent activity |
| Maker | `GET /api/orders`, `GET /api/orders/{code}` | Orders; detail includes live feasibility, audit log and messages |
| Maker | `POST /api/orders/{code}/approve`, `/reject`, `/counter`, `/advance` | Decisions and status updates |
| Maker | `POST /api/products` | Add a design (name, price per pair, pairs per day, sizes); stock starts at 0 |
| Maker | `GET/PUT /api/stock`, `GET/PATCH /api/products/{code}`, `PATCH /api/me` | Stock, price, pairs per day, buffer days |
| Maker | `GET /api/retailers` | Shops that have ordered from this maker, with order counts |
| Maker | `GET /api/audit`, `GET /api/messages` | Audit log and WhatsApp messages |
| Demo | `POST /api/demo/simulate-order`, `POST /api/demo/orders/{code}/retailer-reply` | Dashboard demo buttons (turn off with `DEMO_MODE=false`) |
| Internal | `POST /internal/feasibility`, `POST /internal/orders`, `POST /internal/simulate-message` | Used by the agent and for testing (header `X-Internal-Key`) |
| Meta | `GET/POST /webhooks/meta` | Incoming WhatsApp messages (Meta Cloud API) |

Maker endpoints need `Authorization: Bearer <token>`.

## WhatsApp replies understood

- **Maker, quick replies (no AI):** `1` approve, `2` reject, `3` change. Add the order code to pick one: `1 KS-1042`. Propose directly: `3 KS-1042 2026-12-01 600`.
- **Maker, anything else** goes to the Operations Agent, for example:
  - `आज किती ऑर्डर बाकी आहेत?` (how many orders are pending today?)
  - `Size 8 Classic 10 jodi add kar` (add 10 pairs of size 8 Classic)
  - `KS-1042 approve kar, pan delivery 5 December` (approve KS-1042 with delivery on 5 December)
  - `Paytan ka rate 500 kar do` (set Paytan's price to ₹500)
- **Retailer with a counter-offer:** YES / NO, also हो, नाही, हां, नहीं.
- **Everything else from a retailer** goes to the Sales Agent.

## Connect WhatsApp (Meta WhatsApp Cloud API)

Meta gives a free **test number** (the KarigarSetu bot) that can message up to 5 phones.

**How a message travels:** phone → Meta test number → Meta calls your webhook (`/webhooks/meta`) → backend + Claude → backend asks Meta to send the reply → phone.

1. **Meta app (done once):** developers.facebook.com → My Apps → your app → WhatsApp → **API Setup**.
2. **Add your phones:** in "To" → *Manage phone number list* → add each phone (up to 5) and enter the code it receives. Then send **"hi"** from each phone to the test number (this opens WhatsApp's 24-hour window, needed for the bot's replies).
3. **Fill in `backend/.env`** (never commit this file):
   ```
   WHATSAPP_PROVIDER=meta
   META_WHATSAPP_TOKEN=          # API Setup → Generate access token
   META_PHONE_NUMBER_ID=         # API Setup → "Phone number ID" (not the phone number)
   META_VERIFY_TOKEN=            # a secret word you choose; type the same word in Meta's webhook form
   META_APP_SECRET=              # App settings → Basic → App secret
   ANTHROPIC_API_KEY=
   ```
4. **Makers:** a maker's WhatsApp number is the one they used to sign up on the website (approved at `/admin`).
5. **Give Meta the webhook address:** WhatsApp → **Configuration** → Webhook → Edit:
   - Callback URL: `https://<your-domain>/webhooks/meta` (the server must be reachable over HTTPS)
   - Verify token: the same word as `META_VERIFY_TOKEN`
   - Click **Verify and save** (the backend must be running), then under *Webhook fields* subscribe to **messages**.
6. **Test:** send "hello" from a phone. The server log shows `POST /webhooks/meta` and a reply arrives.

**Good to know**
- The temporary access token expires after about 24 hours: generate a new one and restart the backend (sending fails with a 401 in the log until you do).
- The bot can only send its own text to a phone that messaged it in the last 24 hours. Before a demo, send "hi" from every phone.
- Every incoming message is checked with HMAC-SHA256 using the App secret, and repeats are ignored (Meta sometimes delivers a message twice).
- Voice notes and photos get a polite "please type your message" reply.

## Before going live

- Meta: use a permanent System User token, and your own verified number (Meta Steps 2 and 3).
- Set a long `ADMIN_PASSWORD` and `COOKIE_SECURE=true`.
- Set `DEMO_MODE=false` and change `INTERNAL_API_KEY`.
- Use PostgreSQL (above) rather than SQLite once real makers use it.
