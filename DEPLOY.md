# Deploy KarigarSetu on the GoDaddy VPS

Three containers run on the VPS: **app** (FastAPI + the website), **db** (PostgreSQL 16) and **caddy**
(HTTPS for karigarsetu.co.in, certificate obtained and renewed automatically).

```
Internet ──► Caddy :443 (HTTPS) ──► app :8000 ──► PostgreSQL
```

The steps below are for Ubuntu 22.04 / 24.04. Run them over SSH: `ssh root@<VPS-IP>`.

## 1. Point the domain at the VPS (GoDaddy → My Products → DNS for karigarsetu.co.in)

| Type | Name | Value      |
|------|------|------------|
| A    | @    | `<VPS-IP>` |
| A    | www  | `<VPS-IP>` |

Delete any other A record for `@` (for example GoDaddy's "Parked"). **Don't change the MX/TXT records:
Titan email needs them.** Check:  `nslookup karigarsetu.co.in`  should show the VPS IP.

## 2. Install Docker and open the firewall

```bash
curl -fsSL https://get.docker.com | sh
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

## 3. Get the code

The repo is private, so GitHub asks for a username and a **personal access token** as the password
(GitHub → Settings → Developer settings → Fine-grained tokens → read access to this repo).

```bash
git clone https://github.com/Trups39/karigarsetu.git /opt/karigarsetu
cd /opt/karigarsetu
```

## 4. Create the settings file (never commit it)

```bash
cp backend/.env.example backend/.env
nano backend/.env
chmod 600 backend/.env
```

Fill in at least these values:

| Setting | Value |
|---|---|
| `POSTGRES_PASSWORD` | a long random password (`openssl rand -hex 24`) |
| `DATABASE_URL` | `postgresql+psycopg://karigarsetu:<POSTGRES_PASSWORD>@db:5432/karigarsetu` |
| `ANTHROPIC_API_KEY` | your Claude API key |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | admin login for /admin (use a strong password) |
| `INTERNAL_API_KEY` | new random value (`openssl rand -hex 24`) |
| `PUBLIC_URL` | `https://karigarsetu.co.in` |
| `COOKIE_SECURE` | `true` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `CONTACT_TO` | Titan mailbox (`smtp.titan.email`, `465`) |
| `META_WHATSAPP_TOKEN` / `META_PHONE_NUMBER_ID` / `META_APP_SECRET` | from the Meta app |
| `META_VERIFY_TOKEN` | new random value; type the same one in Meta (step 6) |
| `BOT_WHATSAPP_NUMBER` | `15551567876` |
| `SAMPLE_MAKERS` | `true` (keeps the two sample makers) |
| `DEMO_MODE` | `false` for the live site |

## 5. Start

```bash
docker compose up -d --build
docker compose ps                 # all three "running"; app "healthy" after ~20 s
docker compose logs -f app        # look for: Email: on …  and  WhatsApp: meta
```

Open https://karigarsetu.co.in. The first visit can take a minute while Caddy gets the certificate.
If it doesn't load: `docker compose logs caddy` (usually DNS not pointing at the VPS yet).

## 6. Connect WhatsApp (Meta developer console → WhatsApp → Configuration)

- Callback URL: `https://karigarsetu.co.in/webhooks/meta`
- Verify token: the `META_VERIFY_TOKEN` from `backend/.env`
- Subscribe to the **messages** field.

## 7. Check before submitting

- [ ] https://karigarsetu.co.in loads with the padlock; http:// and www. redirect to it
- [ ] Contact form → email arrives in the Titan mailbox
- [ ] Sign up as a supplier → approve at https://karigarsetu.co.in/admin → log in → dashboard
- [ ] WhatsApp message to the bot gets a reply
- [ ] https://karigarsetu.co.in/docs asks for the admin login

## Everyday commands (in /opt/karigarsetu)

| What | Command |
|---|---|
| Update to the latest code | `git pull && docker compose up -d --build` |
| Logs | `docker compose logs -f app` |
| Restart after changing `.env` | `docker compose up -d` |
| Back up the database | `docker compose exec db pg_dump -U karigarsetu karigarsetu > backup-$(date +%F).sql` |
| Restore a backup | `docker compose exec -T db psql -U karigarsetu karigarsetu < backup-YYYY-MM-DD.sql` |
| Stop | `docker compose down` (data is kept; `down -v` **deletes** the database) |
