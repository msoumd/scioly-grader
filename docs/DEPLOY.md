# Putting the app online

The app runs as one container on **Railway** (it serves the phone app and the API over HTTPS on one address). Render works too; see the end. Its data lives in **Supabase**: Postgres for scores and a private storage bucket for photos. GitHub deploys every change to `main` after the tests pass, then checks the live site.

Nothing here costs money until you choose a paid plan. **Do the steps in order**; each takes a few minutes.

## Costs (budget: $35)

Prices checked November 2026; confirm on [railway.com/pricing](https://railway.com/pricing) and [supabase.com/pricing](https://supabase.com/pricing) before paying.

| What | Plan | Per month | Why |
|---|---|---|---|
| Railway | **Hobby** | **$5** | $5 a month that includes $5 of usage. Railway charges for what the app actually uses: about 0.2–0.3 GB of memory most of the time (≈ $2–3 at $10 per GB-month) and almost no CPU when idle. A tournament day's reading adds cents. During a burst it gets more CPU automatically, so there's no plan to switch for tournament week. |
| Supabase | **Free** | **$0** | Photos are deleted once a sheet is counted or discarded, so storage only holds sheets waiting for review: far under the free 1 GB. Scores take about 10 KB per sheet, roughly 15 MB per tournament, against the free 500 MB database. |
| GitHub Actions, Sentry, UptimeRobot | free tiers | $0 | |
| **Total** | | **≈ $5** | Check Railway's **Usage** page after the first week. If usage goes past the included $5, the extra is charged on top. |

**No custom domain is needed.** Railway gives a free `https://….up.railway.app` address with HTTPS, which is all the camera needs. A domain like `grader.yourclub.org` costs about $10–15 a year and can be added later in Railway (Settings → Networking → Custom Domain).

**Two things about Supabase's free plan:**
- **It pauses a project after a week with no activity.** The nightly backup (step 3) reads the database every day, which should keep it awake. Still, open the Supabase dashboard a few days before the tournament: if it says *Paused*, press **Restore**, which takes a few minutes.
- **It has no daily backups of its own.** The nightly encrypted backup in step 3 covers the scores.

**Photos are not kept.** A sheet's photo, straightened page and crops are deleted as soon as it is counted or discarded. The answers, score, corrections and history stay. After that, the paper sheet is the record: scan it again if anyone disputes it. (To keep photos instead, set `DELETE_PHOTOS_WHEN_DONE=false`, which needs more storage.)

Measured on containers of two sizes (Railway gives the app as much as it needs, up to the Hobby limit):

| | 1 sheet | 5 at once | Burst of 30–60 | Peak memory |
|---|---|---|---|---|
| 1 CPU, 2 GB | 0.5 s | within 2.6 s | 60 all done in 33 s | under 300 MB |
| 0.5 CPU, 512 MB | 1 s | within 7 s | 30 all done in 55 s | 384 MB of 512 |

## 1. Supabase (database and photos)

1. Sign in at [supabase.com](https://supabase.com) → **New project**.
   - Name: `scioly-grader`.
   - Region: the one closest to the tournament (e.g. *West US (Oregon)*; pick Railway's US West region to match).
   - Make a strong database password and save it in your password manager.
2. **Storage → New bucket**: name `scans`, **Public bucket: off**. It must stay private; the app hands out 10-minute links. Only photos of sheets waiting for review sit here.
3. **Project Settings → Data API**: copy the **Project URL**. That is `SUPABASE_URL`.
4. **Project Settings → API Keys**: copy the **service_role** key. That is `SUPABASE_SERVICE_ROLE_KEY`.
   - It can read and write everything, so it only ever goes into Railway's variables.
   - Never paste it anywhere else, and never use the `anon` key with this app.
5. **Connect** (top of the dashboard) → **Connection string**. Copy two of them, replacing `[YOUR-PASSWORD]`:
   - **Transaction pooler** (port 6543) is `DATABASE_URL`, for the app.
   - **Session pooler** (port 5432) is `BACKUP_DATABASE_URL`, for nightly backups.
6. Stay on the **Free** plan.

The app creates its own tables on first start. Every table has row-level security on with no policies, so Supabase's public REST API can see nothing; a test checks this.

## 2. Railway (the app)

1. In [railway.com](https://railway.com) (Hobby plan): **New Project → Deploy from GitHub repo** → choose this repository. Railway reads `railway.json` and builds the `Dockerfile`. The first build takes about 5 minutes. It will fail to start until step 2 is done, which is expected.
2. Open the service → **Variables** → **Raw Editor**, and paste (with your values):

   ```
   ENVIRONMENT=production
   STORAGE_BACKEND=supabase
   SUPABASE_BUCKET=scans
   READER_WORKERS=2
   TRUSTED_PROXY_HOPS=1
   DATABASE_URL=<Supabase transaction pooler string, step 1.5>
   SUPABASE_URL=<step 1.3>
   SUPABASE_SERVICE_ROLE_KEY=<step 1.4>
   TOURNAMENT_PIN=<what graders type: at least 6 characters>
   ADMIN_PIN=<supervisors only: at least 8 characters, different>
   SESSION_SECRET=${{secret(48)}}
   ```

   `${{secret(48)}}` makes Railway generate a random secret. **The app refuses to start** if any of these is missing, a PIN is too short, or photos would be stored on the server's own disk (lost on every deploy). **Deploy Logs** say exactly which one.
3. **Settings → Networking → Generate Domain** gives you the `https://….up.railway.app` address. Open it, then log in with the admin PIN and a name.
4. **Settings → Source**: branch `main`, and turn on **Wait for CI**, so Railway only deploys commits whose GitHub tests passed.
5. Leave **Serverless / App Sleeping** off; a sleeping app would make the first scan of the morning slow.

## 3. GitHub (automatic deploys and backups)

Repository → **Settings → Environments → New environment** `production`. Optionally add yourself as a required reviewer, so each deploy waits for your click. Then add:

| Kind | Name | Value |
|---|---|---|
| Secret | `SMOKE_PIN` | the tournament PIN |
| Variable | `APP_URL` | the `https://….up.railway.app` address |
| Secret | `BACKUP_DATABASE_URL` | Supabase session pooler string (step 1.5) |
| Secret | `BACKUP_PASSPHRASE` | a long random passphrase; **also keep it offline**, since without it the backups can't be opened |

From then on:
- **Deploying:** Railway deploys each commit on `main` once GitHub's tests pass. The **Deploy check** workflow (`.github/workflows/deploy.yml`) waits until that commit is live, then runs a smoke test: health, the app page, HTTPS headers, login, and the events list.
- **Nightly backup** (`.github/workflows/backup.yml`) makes an encrypted copy of the database, kept 14 days. Each night it also restores the copy into a scratch database to prove the backup works. Run it once by hand from the Actions tab after setting up.

Photos are not in the nightly copy; photos only exist while a sheet waits for review. If one were lost, the paper sheet can simply be scanned again.

## 4. Check on deploy day

- Open the address on an iPhone in Safari. The camera works because it's HTTPS. Then **Share → Add to Home Screen**.
- **The login limiter sees real addresses.** On the phone (Wi-Fi), type a wrong PIN 10 times: it should say to wait. On a laptop on a *different* network, logging in should still work. If the laptop is blocked too, tell the developer: `TRUSTED_PROXY_HOPS` needs changing.
- Run the phase 8 mini event (import A&P, 10 teams, 10 sheets, 10 free-response totals, CSV).

## 5. Monitoring (free, optional but recommended)

- **Uptime:** at [uptimerobot.com](https://uptimerobot.com), add an HTTP monitor for `https://…/health` every 5 minutes, with email alerts.
- **Errors:** at [sentry.io](https://sentry.io), create a Python project and paste its DSN as `SENTRY_DSN` in Railway's variables. The server reports crashes there, with no personal data.
- **Logs:** in Railway, open the service → **Deploy Logs** / **HTTP Logs**. Every request line has an ID that matches the `X-Request-ID` the app shows in error reports.

## Restoring a backup

1. Actions → *Nightly backup* → pick a run → download `database-backup`, then unzip it.
2. Make a new Supabase project (or a scratch Postgres), then:

   ```bash
   cd backend
   RESTORE_DATABASE_URL='postgresql://…' BACKUP_PASSPHRASE='…' sh scripts/restore.sh scioly-YYYYMMDD-HHMM.dump.gpg
   ```

3. Check it: run `uv run python scripts/smoke.py <address>` against an app pointed at it. Only then switch Railway's `DATABASE_URL`.

This was tested: a backup encrypted, refused a wrong passphrase, and restored twice into a fresh Postgres 17, keeping all 54 questions, accented team names and the schema version.

## Tournament week

- A day or two before, open the app on a phone and scan a test sheet, so you know it's awake and working.
- Open the Supabase dashboard and make sure the project isn't paused.
- Avoid merging to `main` during the tournament: each merge redeploys, a short blip. The phone upload queue rides it out, but there's no need.
- A phone hotspot is the backup if the venue Wi-Fi fails; uploads wait on the phone until they get through.
- Afterwards, download the results CSVs. Between tournaments, the Railway service can stay up (about $5/month) or be removed. The database stays in Supabase either way.

## Alternative: Render instead of Railway

`render.yaml` is a ready Blueprint (**New → Blueprint** in Render). Render charges per instance size, not usage:
- **Starter**: $7/month, 0.5 CPU, 512 MB. Works for setup and testing, but tight on the day.
- **Standard**: $25/month, 1 CPU, 2 GB. Use it for tournament week; billed by the second, so a week is about $6.

To use it: put the same values as step 2 in Render's environment, copy **Settings → Deploy Hook** into a GitHub secret `RENDER_DEPLOY_HOOK`, set `APP_URL` to the `….onrender.com` address, and turn Render's auto-deploy off. The Deploy check workflow then triggers each deploy itself.
