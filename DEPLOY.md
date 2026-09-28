# Deploying to a server

Step-by-step, from nothing to `https://your-domain` with automatic HTTPS.
Budget about an hour the first time.

## 0. What you need

- **A server**: Ubuntu 24.04, **4 GB RAM** or more, 40 GB+ disk. Intel/AMD or ARM both work.
- **A domain name** (e.g. `transit.example.com`), or the free `sslip.io` option below.
- **An SSH key** on your Mac. Check with `ls ~/.ssh/*.pub`. If there's none, create one:
  ```bash
  ssh-keygen -t ed25519 -C "your-email@example.com"   # press Enter for the defaults; set a passphrase
  cat ~/.ssh/id_ed25519.pub                            # the PUBLIC key: this is what you give the provider
  ```
  Never share the file *without* `.pub`. That's your private key.

## 1. Create the server

In your provider's dashboard, create a server with **Ubuntu 24.04**, and paste your public key
where it asks for an SSH key. Note the **IPv4 address** it gets (e.g. `203.0.113.10`).

**On AWS Lightsail:** choose the Ubuntu 24.04 blueprint and the 4 GB plan. Lightsail gives you a
key to download (or lets you upload yours). Then:
- **Networking tab → Create static IP** and attach it (free while attached). Otherwise the IP
  changes if the instance restarts, and your DNS would point at the wrong place.
- **Networking tab → IPv4 Firewall:** add **HTTPS (443)**. SSH (22) and HTTP (80) are open by default.
- You log in as `ubuntu` instead of `root` (see step 3).

If offered, turn on the provider's **backups** (about 20% of the server price). That's your
off-site copy if the whole server is lost.

## 2. Point your domain at the server (DNS)

At your domain registrar, add two **A records**:

| Name (host)  | Type | Value (points to)  |
|--------------|------|--------------------|
| `transit`    | A    | `203.0.113.10`     |
| `grafana.transit` | A | `203.0.113.10`   |

(Use `@` and `grafana` instead if the site should live at the bare domain.)
Check it worked (can take a few minutes): `dig +short transit.example.com` should print the IP.

**No domain?** Use `203-0-113-10.sslip.io` as your domain (your IP with dashes). sslip.io is a
free service that answers any such name with the IP inside it, and Caddy can get a real
certificate for it. Grafana would be `grafana.203-0-113-10.sslip.io`.

## 3. Secure the server and install Docker

From your Mac, in the project folder:
```bash
ssh root@203.0.113.10 'bash -s' < deploy/server-setup.sh            # Hetzner, DigitalOcean
ssh ubuntu@203.0.113.10 'sudo bash -s' < deploy/server-setup.sh     # AWS Lightsail / EC2
```
(If Lightsail gave you a downloaded key, add `-i ~/Downloads/LightsailDefaultKey-us-west-2.pem`,
after `chmod 600` on that file.)
This creates the `transit` user, turns off password logins, sets up the firewall and automatic
security updates, adds swap, and installs Docker. From now on:
```bash
ssh transit@203.0.113.10
```

## 4. Get the code and create the secrets file

On the server:
```bash
git clone https://github.com/SavitP/Transit-Reliablility.git
cd Transit-Reliablility
```
Create `.env` with **fresh random passwords** (never reuse your laptop's). Change only the
`DOMAIN=` value on the first line, then paste the whole block:
```bash
DOMAIN=transit.example.com
PG=$(openssl rand -hex 16)
cat > .env <<EOF
POSTGRES_PASSWORD=$PG
DATABASE_URL=postgresql://transit:$PG@localhost:5433/transit
GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 12)
API_DB_PASSWORD=$(openssl rand -hex 16)
DOMAIN=$DOMAIN
EOF
chmod 600 .env        # only your user can read it
cat .env              # check it looks right (don't paste this anywhere)
```

## 5. Start everything

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f caddy
```
Within a minute Caddy should log `certificate obtained successfully` for both names.
Press Ctrl+C to stop watching.

To avoid typing both `-f` flags every time, add this to `~/.bashrc` on the server:
```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
```
Then plain `docker compose ps` works.

## 6. Check it

- `https://transit.example.com`: the website (empty charts at first; data builds up)
- `https://transit.example.com/api/health`: `{"status":"ok", ...}` after a few minutes
- `https://grafana.transit.example.com`: log in as `admin` with `GRAFANA_ADMIN_PASSWORD`
- `http://transit.example.com`: should redirect to `https://`

## 7. Daily backups

```bash
crontab -e
```
Add this line (runs at 3:15am server time every day):
```
15 3 * * * /home/transit/Transit-Reliablility/deploy/backup.sh >> /home/transit/backup.log 2>&1
```
Backups go to `~/backups/`, and the last 7 days are kept. They live on the same server, so also
turn on the provider's backups (step 1) or copy them off now and then:
`scp transit@203.0.113.10:backups/*.dump ~/transit-backups/`

**Restoring** a backup into an empty database (tested; TimescaleDB needs the pre/post steps):
```bash
docker compose exec -T db psql -U transit -d transit -c "SELECT timescaledb_pre_restore()"
docker compose exec -T db pg_restore -U transit -d transit --clean --if-exists < ~/backups/transit-YYYY-MM-DD.dump
docker compose exec -T db psql -U transit -d transit -c "SELECT timescaledb_post_restore()"
```

## 8. An outside check (tells you if the whole server dies)

Monitoring on the server can't warn you when the server itself is down. Sign up for a free
uptime checker (e.g. UptimeRobot or Better Stack), add an HTTPS check for
`https://transit.example.com/api/health` every 5 minutes, and have it email you.
That URL fails if the site is down *or* no new departures arrived for an hour.

## Everyday tasks

| Task | Command (on the server, in the project folder) |
|---|---|
| Deploy the newest version (after CI is green) | `./deploy/update.sh` |
| See what's running | `docker compose ps` |
| Read logs | `docker compose logs --tail 50 processor` |
| Open Prometheus (not public) | on your Mac: `ssh -L 9090:localhost:9090 transit@203.0.113.10`, then open http://localhost:9090 |
| Query the database | `docker compose exec db psql -U transit -d transit` |
| Disk space | `df -h /` and `docker system df` |
