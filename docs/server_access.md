# Server Access Guide

**Server:** Hetzner CX23 — `116.203.255.222`
**Domain:** `incomingscience.xyz`

---

## SSH into the server

```bash
ssh root@116.203.255.222
```

Once in, activate the Python environment:

```bash
cd /opt/arxiv-grader
source venv/bin/activate
```

---

## Key locations

| What | Where |
|------|-------|
| Project code | `/opt/arxiv-grader/` |
| User data | `/opt/arxiv-grader/users/yuval/` |
| Daily digests | `/opt/arxiv-grader/users/yuval/data/YYYY-MM-DD/` |
| Ratings | `/opt/arxiv-grader/users/yuval/data/YYYY-MM-DD/ratings.json` |
| Archive | `/opt/arxiv-grader/users/yuval/archive.json` |
| Taste profile | `/opt/arxiv-grader/users/yuval/taste_profile.json` |
| Root `.env` | `/opt/arxiv-grader/.env` |
| Daily log | `/var/log/arxiv-grader/daily.log` |
| Server log | `/var/log/arxiv-grader/server.log` |
| Refiner log | `/var/log/arxiv-grader/refiner.log` |

---

## Common tasks

### Check the daily pipeline log
```bash
tail -100 /var/log/arxiv-grader/daily.log
```
Look for lines like `[yuval] DONE` (success) or `[yuval] FAILED` (error).
To see the full log: `cat /var/log/arxiv-grader/daily.log`

### Check the monthly profile refiner log
```bash
cat /var/log/arxiv-grader/refiner.log
```
Runs on the 1st of each month. Look for `Profile saved` (success) or `FAILED` (error).
To verify the profile was actually updated, check the modification timestamp:
```bash
ls -l /opt/arxiv-grader/users/yuval/taste_profile.json
```

### Run the pipeline manually
```bash
cd /opt/arxiv-grader && source venv/bin/activate
python run_all_users.py
```

### Run without sending email
```bash
python run_all_users.py --no-email
```

### Check the rating server is running
```bash
systemctl status arxiv-grader
curl http://127.0.0.1:5000/health
```

### Restart the rating server
```bash
systemctl restart arxiv-grader
```

### Check cron jobs
```bash
crontab -l
```

### Deploy updated code from local machine
```bash
# From your local machine (Git Bash)
scp /z/arxiv_grader/server.py root@116.203.255.222:/opt/arxiv-grader/server.py
systemctl restart arxiv-grader
```

### Add a new user
```bash
cd /opt/arxiv-grader && source venv/bin/activate
python create_profile.py --user-dir users/<name>
```

---

## Onboarding a new user

**What you need from them:** the filled `incoming_science_onboarding.docx` form.

### Step 1 — Prepare their `.env` on the server
SSH in and create the user directory:
```bash
mkdir -p /opt/arxiv-grader/users/<name>
```
Create their `.env` file (replace the values before running):
```bash
cat > /opt/arxiv-grader/users/<name>/.env << 'EOF'
ANTHROPIC_API_KEY=<their key>
EMAIL_TO=<their email>
EOF
```
Verify it was written correctly:
```bash
cat /opt/arxiv-grader/users/<name>/.env
```
They need their own Anthropic API key — create one for them at https://console.anthropic.com/ (all keys bill to your account).

### Step 2 — Run `create_profile.py` interactively
```bash
cd /opt/arxiv-grader && source venv/bin/activate
python create_profile.py --user-dir users/<name>
```
The script will run a 4-part interview — answer using the filled form:
1. **arXiv categories** — copy from Part 1 of the form (comma-separated)
2. **Research interests** — paste the free text from Part 2
3. **Researchers to follow** — enter names from Part 3 one per line, blank line to finish
4. **Excel file of papers** — you'll need to convert the URLs from Part 4 of the form into an Excel file first (one URL per row, column A), save it somewhere on the server, and provide the path

### Step 2b — Prepare the Excel file from the form
On your local machine, copy the URLs from the Word table into an Excel file (one per row, no header), save it, then upload it to the server:
```bash
scp /path/to/papers.xlsx root@116.203.255.222:/opt/arxiv-grader/users/<name>/papers.xlsx
```
Then when `create_profile.py` asks for the Excel path, enter:
```
/opt/arxiv-grader/users/<name>/papers.xlsx
```

### Step 3 — Review and save the profile
The script will show a draft profile. Review it, adjust grades/rankings if needed, then accept. This saves `taste_profile.json` to the user's directory.

### Step 4 — Test a manual run for the new user
```bash
python run_all_users.py --user <name> --no-email
```
Check that `users/<name>/data/YYYY-MM-DD/digest.pdf` was created, then send with email:
```bash
python run_all_users.py --user <name> --skip-dedup --skip-archive
```

### Step 5 — Configure delivery preferences

Edit the user's `taste_profile.json` to set their delivery mode. The defaults (if fields are absent) are `daily_digest: true` and `weekly_digest: false`, so a standard daily user needs no changes.

**Daily only (default):** no changes needed — the profile created by `create_profile.py` works as-is.

**Weekly only** (gets one email per week with papers scored ≥ 8, no daily emails):
```bash
# Add to taste_profile.json:
"daily_digest": false,
"weekly_digest": true,
"weekly_day": "friday"   # lowercase weekday name, defaults to friday
```
And add to their `.env`:
```bash
cat >> /opt/arxiv-grader/users/<name>/.env << 'EOF'
EMAIL_TO_WEEKLY=<their email>
EOF
```

**Both daily and weekly** (daily email every day + weekly highlights email on their chosen day):
```bash
# Add to taste_profile.json:
"daily_digest": true,
"weekly_digest": true,
"weekly_day": "friday"
```
And add both lists to their `.env`:
```bash
cat >> /opt/arxiv-grader/users/<name>/.env << 'EOF'
EMAIL_TO_DAILY=<daily recipients, comma-separated>
EMAIL_TO_WEEKLY=<weekly recipients, comma-separated>
EOF
```

**Notes:**
- `EMAIL_TO_DAILY` falls back to `EMAIL_TO` if not set — existing users with only `EMAIL_TO` are unaffected.
- `EMAIL_TO_WEEKLY` falls back to `EMAIL_TO` if not set.
- The weekly email is sent at the end of the normal daily cron run on the chosen weekday — no separate cron entry needed.
- The weekly PDF contains only papers scored 8 or above from the past 7 days, with the title "weekly digest".

### Step 6 — Done
The new user is picked up automatically by the daily cron — no restart or config change needed.

---

## Services

| Service | What it does |
|---------|-------------|
| `arxiv-grader` | Gunicorn serving `server.py` (rating endpoint + landing page) |
| `caddy` | Reverse proxy, handles HTTPS via Let's Encrypt |

Both are enabled and start automatically on reboot.
