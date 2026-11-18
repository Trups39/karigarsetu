# Changes in this version (18 Nov 2026)

## How it works now
1. **When the tables are created** (first start or `python -m app.seed --reset`), the SQL scripts load:
   - `db/retailers.sql` – 7 sample shops
   - `db/seed.sql` – 2 sample suppliers (Shinde Footwear, Patil Chappal Udyog): makers, designs, stock, and approved supplier accounts **without a website login**
   - `db/demo_orders.sql` – their past orders
2. **Your own maker is not preset.** Sign up on the website (*Become a supplier*) with your WhatsApp number. Status: pending.
3. **Approve:** open `/admin`, log in with `ADMIN_EMAIL` + `ADMIN_PASSWORD` (the only login you set), click **Approve**. Your maker is added and you get a WhatsApp message.
4. **Log in** with email + password, add your designs (**Products → Add a design**) and ready pairs (**Stock**).
5. Shops' WhatsApp orders now work for your maker too. Your sign-up WhatsApp number is the one the Operations Agent recognises.

`--reset` reloads the sample data and **keeps your login** (your maker is added back; add your designs and stock again).

## Session rules
bcrypt passwords · 5 wrong passwords → 15-minute lock · login lasts 14 days on that device, in every tab, until Log out · logout in one tab logs out the others · rejected accounts logged out at once · one login (supplier or admin) per browser · `/docs` admin-only once `ADMIN_PASSWORD` is set.

## Also included
The 17 Nov fixes (built from an older upload): WhatsApp formatting, no visible reasoning, agents recover from errors, the "thinking block" maker crash fix with separate `sales:` / `ops:` memory, `DEMO_RETAILER_PHONE` after every reset.

## Update your laptop (E:\karigarsetu)
1. Keep your `backend\.env`. Copy everything else from this zip over your folder.
2. `pip install -r backend\requirements.txt` (adds bcrypt).
3. In `backend\.env`: add `ADMIN_EMAIL=admin@karigarsetu.co.in` and `ADMIN_PASSWORD=choose-a-password`, keep `DEMO_RETAILER_PHONE=13158865652`, **delete the `DEMO_MAKER_PHONE` line** (no longer used).
4. Stop the server, `python -m app.seed --reset`, start the server.
5. Website → Become a supplier (7030317109) → `/admin` → Approve → Log in → add designs and stock.
6. Tests: `python -m pytest -q` → 51 passed.

On the VPS also set `COOKIE_SECURE=true` and a long `ADMIN_PASSWORD`.
