# Human Pages for Omi

Hire real humans for tasks — directly from your [Omi](https://omi.me) wearable. Powered by [humanpages.ai](https://humanpages.ai).

## What it does

- **Auto-detect**: When your conversation mentions needing a service ("I need a photographer for Saturday"), the plugin detects it and suggests matching providers from Human Pages.
- **Search**: Ask Omi to search for service providers by skill, location, or budget.
- **Post listings**: Create job listings that real humans can apply to.
- **Hire directly**: Send a job offer to a specific provider you found.

## Setup

### 1. Get a Human Pages API key

Register your agent at [humanpages.ai](https://humanpages.ai) or use the [MCP server](https://www.npmjs.com/package/humanpages):

```bash
npx humanpages register
```

### 2. Deploy

```bash
# Clone
git clone https://github.com/human-pages-ai/omi-humanpages.git
cd omi-humanpages

# Configure
cp .env.example .env
# Edit .env with your HP_AGENT_KEY and OPENAI_API_KEY

# Run locally
pip install -r requirements.txt
uvicorn main:app --reload

# Or with Docker
docker build -t omi-humanpages .
docker run -p 8000:8000 --env-file .env omi-humanpages
```

### 3. Deploy to production

Deploy to Railway, Render, Fly.io, or any host. Set environment variables from `.env.example`.

### 4. Install in Omi

1. Open the Omi app
2. Go to Explore → search "Human Pages"
3. Enable the plugin

## Chat commands

Once installed, talk to Omi naturally:

- *"Find me a photographer in San Francisco"*
- *"I need a web designer, budget around $500"*
- *"Post a job listing for a plumber, $100, need someone this week"*
- *"Hire that first person from the search results"*

## API endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /webhook` | Omi memory_creation trigger — auto-detects service needs |
| `GET /.well-known/omi-tools.json` | Chat tools manifest |
| `POST /tools/search` | Search Human Pages for providers |
| `POST /tools/listing` | Create a job listing |
| `POST /tools/hire` | Send a direct job offer |
| `GET /setup_check` | Verify plugin configuration |

## How it works

```
You wear Omi → Conversation recorded → Transcript analyzed
    ↓
"I need a photographer" detected
    ↓
Human Pages searched → Matching providers shown
    ↓
You say "hire them" → Job offer sent → Human notified
    ↓
Work done → Payment via crypto or fiat
```

## License

MIT
