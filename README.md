# Sunsure Brand Monitor

One-file Python tool that pulls news from Google News RSS (+ optional industry feeds), filters with Claude Haiku 4.5, and emails you a ranked daily digest.

## What it does

- Builds a Google News RSS URL for every keyword in `config.yaml` and pulls matching articles
- Dedupes against a local SQLite database so you never see the same article twice
- Asks Claude to classify each article: is it really about us? competitor? sentiment? category? why it matters?
- Emails a ranked digest grouped into **About Sunsure** and **Competitors**

## Automation (GitHub Actions, free, no API key)

Two scheduled workflows in `.github/workflows/` keep everything running without your laptop:

| Workflow | When (IST) | What it does |
|---|---|---|
| `refresh.yml` | daily 06:00 | `collect_data.py` → `clean_data.py` → `classify_coverage.py`, commits the data files. Streamlit Cloud redeploys the dashboard on push. New runs are merged with the previous data, so a flaky fetch never drops coverage. |
| `digest.yml` | 08:00 and 18:00 | `digest.py` pulls the last ~36h of coverage for Sunsure and each competitor (Google News, industry RSS, GDELT, Bing), tags sentiment with VADER and Tier 1 outlets, and emails it. Already-sent articles are remembered in `digest_seen.json`. |

Both can also be run by hand from the repo's **Actions** tab (**Run workflow**).

### One-time setup for the email digest

1. Create a Gmail App Password for the sending account (needs 2-Step Verification): https://myaccount.google.com/apppasswords
2. Add three repository secrets (Settings → Secrets and variables → Actions), or from this folder:

   ```bash
   gh secret set GMAIL_USER
   gh secret set GMAIL_APP_PASSWORD
   gh secret set DIGEST_TO
   ```

   `DIGEST_TO` is a comma-separated list of recipients.
3. Optional: add a repository **variable** `DASHBOARD_URL` with the Streamlit link so the email links to it.

Preview the email locally without sending: `python digest.py --dry-run` (writes `digest_preview.html`).

Competitors and search terms live in `COMPANIES` (`collect_data.py`) and `MATCH_PATTERNS` (`clean_data.py`); the digest uses the same lists.

---

_The section below describes the original `monitor.py`, which uses the Anthropic API. The automated digest above replaces it._

## One-time setup

### 1. Install Python 3.10+

macOS ships a stub at `/usr/bin/python3` that wants Xcode Command Line Tools. Fastest fix is Homebrew:

```bash
brew install python
```

Verify:

```bash
python3 --version      # should be 3.10 or newer
```

### 2. Create a virtualenv and install deps

```bash
cd "/Users/mac/Claude Code/brand-monitor"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Get your API keys

- **Anthropic API key**: https://console.anthropic.com/ → Settings → API Keys. Starts with `sk-ant-...`.
- **Gmail App Password** (only if sending from Gmail):
  1. Enable 2-Step Verification on your Google account
  2. Go to https://myaccount.google.com/apppasswords
  3. Create a password for "Mail" — it's a 16-character string like `abcd efgh ijkl mnop`

### 4. Configure environment

```bash
cp .env.example .env
# edit .env with your keys
source .env
```

### 5. Edit `config.yaml`

- Update the `email:` block with your sender/recipient addresses and SMTP host
- Add/remove keywords and competitors as needed

## Running it

### Dry run (prints digest, doesn't email)

```bash
source .venv/bin/activate
source .env
python monitor.py --dry-run --limit 5
```

The `--limit 5` caps it at 5 classified articles so you can test cheaply. Remove when it looks right.

### Full run

```bash
python monitor.py
```

First run will process a backlog of articles from Google News (anywhere from 50–300 depending on how much you track). After that, each run only processes **new** articles.

### Schedule it

Add to `crontab -e` on macOS/Linux to run 8am and 2pm daily:

```cron
0 8,14 * * *  cd "/Users/mac/Claude Code/brand-monitor" && . .venv/bin/activate && . .env && python monitor.py >> run.log 2>&1
```

Or use `launchd` on macOS — let me know if you want that instead.

## Costs

- **Google News RSS**: free
- **Anthropic API (Haiku 4.5)**: roughly $0.30–$1.00/day depending on article volume. First run is the most expensive (processing the backlog); steady-state is cheap.
- **Gmail SMTP**: free

## Tuning tips

- **Too much noise?** Tighten `keywords` (use more specific phrases) and reduce `extra_feeds`.
- **Missing mentions?** Add variants (e.g., `"Sunsure"` alone will catch more but produces false positives that the LLM then filters out — that's fine).
- **Competitors too loud?** Remove entries from the `competitors:` list in `config.yaml`.
- **Want Slack instead of email?** Swap `send_email()` for a `requests.post()` to a Slack incoming webhook — about 10 lines.

## Resetting

Delete `seen.db` if you want to re-process everything from scratch.
