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

### 6. Schedule Daily Execution

```bash
# Copy plist to LaunchAgents
cp com.user.ai-news-summary.plist ~/Library/LaunchAgents/

# Edit the plist to add your API keys (or use env file)
# Then load it:
launchctl load ~/Library/LaunchAgents/com.user.ai-news-summary.plist

# Check status
launchctl list | grep ai-news

# To unload:
launchctl unload ~/Library/LaunchAgents/com.user.ai-news-summary.plist
```

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
