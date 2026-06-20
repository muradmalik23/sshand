# SSHand — Integrations Guide

This guide covers how to connect SSHand to **Claude.ai** and **ChatGPT** through their native extensions/integrations UI — no config files to edit, no IDE required.

For IDE-based clients (Claude Desktop, Cursor, VS Code) see the [README](README.md).

---

## How the transports work

SSHand supports two transports:

| Transport | Used for |
|-----------|----------|
| `stdio` | Claude Desktop, Cursor, VS Code — the client spawns the process locally |
| `http` | Claude.ai web, ChatGPT Desktop, OpenAI Agents SDK — the client connects over HTTP to a running server |

For Claude.ai and ChatGPT web you need the **HTTP transport**, and the server must be reachable at a URL the browser (or Anthropic/OpenAI servers) can reach.

---

## Part 1 — Start the HTTP server

### Local machine (fastest to test)

```bash
# After pip install sshand
sshand --transport http --port 8000

# Or with uvx (no install needed)
uvx sshand --transport http --port 8000
```

The server starts at `http://127.0.0.1:8000/mcp`.

> **Note:** `127.0.0.1` (localhost) is only reachable from your own machine.
> For Claude.ai web or ChatGPT web to connect, you need a public URL — see Part 2.

### Keep it running persistently

On Linux/macOS, use a simple systemd unit or a tmux session.
On Windows, start it in a terminal you leave open, or use Task Scheduler.

---

## Part 2 — Expose the server publicly (for web clients)

Claude.ai and ChatGPT web run in the cloud, so `localhost` is not reachable.
You need to tunnel your local server to a public URL.

### Option A — ngrok (easiest)

```bash
# Install: https://ngrok.com/download
ngrok http 8000
```

ngrok prints a URL like `https://abc123.ngrok-free.app`.
Your MCP endpoint becomes: `https://abc123.ngrok-free.app/mcp`

> Free ngrok tunnels expire after a few hours. For permanent use, sign up for a free ngrok account to get a stable subdomain.

### Option B — Cloudflare Tunnel (free, persistent)

```bash
# Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
cloudflared tunnel --url http://localhost:8000
```

Cloudflare prints a permanent `*.trycloudflare.com` URL.
Your MCP endpoint: `https://<your-tunnel>.trycloudflare.com/mcp`

### Option C — Deploy to a VPS (production)

Run `sshand --transport http --host 0.0.0.0 --port 8000` on a VPS,
then put nginx or Caddy in front with TLS:

```nginx
server {
    listen 443 ssl;
    server_name sshand.yourdomain.com;

    location /mcp {
        proxy_pass http://127.0.0.1:8000/mcp;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Your MCP endpoint: `https://sshand.yourdomain.com/mcp`

> **Security:** Never expose port 8000 directly on a public interface without TLS and auth.
> Anyone who can reach the endpoint has SSH access to your registered servers.

---

## Part 3 — Claude.ai (native Integrations)

Claude.ai has a built-in **Integrations** panel that connects to any MCP server over HTTP.

### Steps

1. Open [claude.ai](https://claude.ai) and sign in.
2. Click your profile icon → **Settings** → **Integrations**.
3. Click **Add integration** (or **Connect more tools**, depending on your plan).
4. Fill in the form:
   - **Name:** `SSHand SSH`
   - **URL:** your MCP endpoint, e.g. `https://abc123.ngrok-free.app/mcp`
5. Click **Save** / **Connect**.
6. Claude will probe the endpoint and list the available tools. You should see all 11 `ssh_*` tools.
7. In any conversation, click the **Tools** (⚙) icon and enable **SSHand SSH**.

### Using it

Once connected, just describe what you want:

> *"What servers do you have access to?"*  
> *"Check disk usage on webserver"*  
> *"Tail the last 50 lines of the nginx error log on devbox"*  
> *"Deploy this config file to the production server"*

Claude will call the appropriate `ssh_*` tools automatically.

### Notes

- The Integrations feature is available on **Claude Pro and above**. Free-tier users may not see it.
- Claude.ai connects from Anthropic's servers, so your endpoint must be publicly reachable (Part 2).
- Each conversation turn is independent — the connection is stateless from Claude's perspective, but SSHand maintains a connection cache for efficiency.

---

## Part 4 — ChatGPT (Desktop app)

ChatGPT Desktop for macOS and Windows has native MCP support.

### Steps

1. Open **ChatGPT Desktop**.
2. Click the **Settings** gear icon → **Integrations** (or **MCP Servers**).
3. Click **Add MCP server**.
4. Enter:
   - **Name:** `SSHand SSH`
   - **URL:** `http://localhost:8000/mcp` (if running locally)
     or your public ngrok/Cloudflare URL for remote access
5. Click **Save**.
6. ChatGPT will discover the tools and make them available in your conversations.

### Using it

> *"What SSH hosts are configured?"*  
> *"Run df -h on the webserver"*  
> *"Read /etc/nginx/nginx.conf from the production box"*

### Notes

- ChatGPT Desktop connects from your local machine, so `http://localhost:8000/mcp` works fine without a tunnel.
- Requires **ChatGPT Plus or higher** to use custom integrations.

---

## Part 5 — ChatGPT web (Custom GPT Actions)

The ChatGPT web app doesn't natively speak MCP, but you can expose SSHand as a **Custom GPT Action** using an OpenAPI wrapper. This requires slightly more setup.

### Overview

You create a tiny FastAPI wrapper that translates OpenAPI calls → SSHand SSH tool calls. Then you register it as a GPT Action.

### 1. Create the OpenAPI wrapper

```python
# openapi_wrapper.py  (minimal example)
from fastapi import FastAPI
from pydantic import BaseModel
import httpx

SSHAND_URL = "http://localhost:8000/mcp"  # or your public URL
app = FastAPI(title="SSHand SSH", version="0.1.0")

class CommandRequest(BaseModel):
    alias: str
    command: str

@app.post("/run_command")
async def run_command(req: CommandRequest):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{SSHAND_URL}/tools/ssh_run_command",
                                 json={"alias": req.alias, "command": req.command})
    return resp.json()

# Add more endpoints as needed...
```

```bash
pip install fastapi uvicorn httpx
uvicorn openapi_wrapper:app --port 9000
```

Then expose it publicly (ngrok, etc.) and get the OpenAPI spec:
`https://your-wrapper.ngrok.io/openapi.json`

### 2. Register as a GPT Action

1. Go to [chat.openai.com](https://chat.openai.com) → **Explore GPTs** → **Create**.
2. In the GPT editor, click **Configure** → **Add action**.
3. Paste your OpenAPI spec URL or import the JSON.
4. Set authentication if desired (API key header).
5. Save the GPT and test it.

> **Tip:** For most users, ChatGPT Desktop (Part 4) is much simpler and provides the same result without the wrapper.

---

## Troubleshooting

### Claude.ai says "Could not connect to integration"
- Confirm the server is running: `curl https://your-url.ngrok.io/mcp` should return JSON.
- Check that the URL ends in `/mcp` exactly.
- Restart the server and re-save the integration.

### ChatGPT Desktop shows "Connection failed"
- If using localhost: confirm `sshand --transport http` is running.
- Check for firewall rules blocking port 8000.
- Try `curl http://localhost:8000/mcp` to verify the server responds.

### Tools show up but calls fail
- Run `sshand setup` and use `ssh_test_connection` to verify credentials.
- Check the server terminal output — connection errors from paramiko appear there.
- The SSH user must have permissions for the operation (read, write, sudo, etc.).

### ngrok tunnel disconnects
- Free ngrok tunnels have a session limit. Use a free ngrok account to get a longer-lived tunnel, or switch to Cloudflare Tunnel for a permanent URL.
