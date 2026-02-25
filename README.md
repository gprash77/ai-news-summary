# AI News Summary Aggregator

A free, local automation that aggregates AI news from multiple sources, generates TLDR summaries using Gemini, and sends a daily morning email.

## Features

- **Multiple Sources**: Twitter/X, YouTube, Email Newsletters, RSS feeds
- **AI Summaries**: Gemini-powered TLDR summaries
- **Daily Email**: Beautiful HTML digest to you and friends
- **Local Archive**: Markdown files for historical reference
- **100% Free**: Uses free tiers of all APIs

## Quick Start

### 1. Set Up Python Environment

```bash
cd ~/ai-news-summary
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure API Keys

Create a `.env` file or export environment variables:

```bash
export GEMINI_API_KEY="your-gemini-api-key"
export YOUTUBE_API_KEY="your-youtube-api-key"  # Optional
```

**Get API Keys:**
- **Gemini**: https://aistudio.google.com/app/apikey (free)
- **YouTube**: https://console.cloud.google.com (optional, free tier)

### 3. Set Up Gmail API (for newsletters + sending)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or use existing)
3. Enable the **Gmail API**
4. Go to **Credentials** → Create **OAuth 2.0 Client ID**
   - Application type: Desktop app
5. Download the JSON file
6. Save as `credentials/gmail_credentials.json`

First run will open a browser for OAuth consent.

### 4. Configure Sources

Edit `config.yaml`:

```yaml
sources:
  twitter:
    accounts: [sama, ylecun, karpathy]

  youtube:
    channels:
      - "UCbfYPyITQ-7l4upoX8nvctg"  # Two Minute Papers

  rss:
    feeds:
      - https://techcrunch.com/tag/artificial-intelligence/feed/

  newsletters:
    gmail_label: "AI-News"  # Create this label in Gmail

email:
  from: "your-email@gmail.com"
  subscribers:
    - "your-email@gmail.com"
    - "friend@example.com"
```

### 5. Test Run

```bash
# Activate venv
source venv/bin/activate

# Test collection (no email/archive)
python src/main.py --dry-run

# Full run without email
python src/main.py --skip-email

# Full run
python src/main.py
```

### 6. Schedule Daily Execution (GitHub Actions)

The pipeline runs daily via `.github/workflows/daily-digest.yml` (cron: 15:00 UTC = 7 AM PST).

**Required GitHub Secrets** (Settings → Secrets → Actions):

| Secret | How to get it |
|--------|--------------|
| `GMAIL_TOKEN` | Contents of `credentials/gmail_token.json` after local OAuth |
| `GMAIL_CREDENTIALS` | Contents of `credentials/gmail_credentials.json` from Google Cloud Console |
| `GEMINI_API_KEY` | https://aistudio.google.com/app/apikey |
| `YOUTUBE_API_KEY` | https://console.cloud.google.com |

**Re-authorizing OAuth (when scopes change):**

1. Delete local token: `rm credentials/gmail_token.json`
2. Trigger OAuth locally: `python src/main.py --dry-run` (browser opens, sign in and approve)
3. New token written to `credentials/gmail_token.json`
4. Update the `GMAIL_TOKEN` GitHub secret with the new file contents

**Manual trigger:** Go to Actions → Daily AI News Digest → Run workflow

## Usage

```bash
# Full run
python src/main.py

# Options
python src/main.py --dry-run       # Test without processing
python src/main.py --skip-email    # Don't send email
python src/main.py --skip-archive  # Don't save to archive
python src/main.py -c custom.yaml  # Use custom config
python src/main.py -v              # Verbose logging
```

## Project Structure

```
ai-news-summary/
├── config.yaml           # Configuration
├── credentials/          # OAuth tokens (gitignored)
├── src/
│   ├── main.py           # Entry point
│   ├── collectors/       # Data source collectors
│   ├── summarizer.py     # Gemini integration
│   ├── emailer.py        # Email sending
│   └── archiver.py       # Local storage
├── archive/              # Daily summaries
└── requirements.txt
```

## Adding Friends

Edit `config.yaml`:

```yaml
email:
  subscribers:
    - "your-email@gmail.com"
    - "friend1@example.com"
    - "friend2@example.com"
```

Friends are added to BCC for privacy.

## Gmail Label Setup

For newsletters collection:

1. In Gmail, create a label called "AI-News"
2. Create filters to auto-label AI newsletters
3. The script will read unread emails from this label

## Troubleshooting

**No tweets collected:**
- Nitter instances may be down. Try different instances in config.
- Some accounts may have restricted access.

**Gmail OAuth error:**
- Delete `credentials/gmail_token.json` and re-authenticate

**No YouTube videos:**
- Ensure `YOUTUBE_API_KEY` is set
- Check channel IDs are correct (use channel ID, not username)

**Gemini errors:**
- Check API key is valid
- Free tier has 15 req/min limit - the script handles this gracefully

## Free Tier Limits

| Service | Limit | Usage |
|---------|-------|-------|
| Gemini | 15 req/min, 1M tokens/day | ~50 summaries/day easily |
| Gmail | Unlimited | Personal use |
| YouTube | 10,000 units/day | ~100 video lookups |
| Nitter/RSS | Unlimited | Standard feeds |

## License

MIT
