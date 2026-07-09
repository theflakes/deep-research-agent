# Deep Research Agent

A hierarchical deep research agent built with the **Microsoft Agent Framework** and **Textual** TUI. Uses a strict 3-tier delegation chain: **Orchestrator → Searcher → Analyzer** to perform web-based research and document analysis while keeping context windows lean for local LLMs.

The project is designed to work with local/OpenAI-compatible models and can be deployed in a privacy-preserving network layout using a local **SearXNG** instance plus a dedicated **Tor SOCKS5h proxy** for URL retrieval and outbound search traffic.

## Architecture

```text
+-----------------------------------+
|    Orchestrator (Planner)         |
|-----------------------------------|
| Tools: write_workspace_file,      |
|        list_workspace_files,      |
|        write_todos, read_todos,   |
|        think_tool, delegate_tasks |
| No web or file reading tools.     |
+-----------------+-----------------+
                  | delegates to
                  v
       +--------------------+
       |   Searcher         |
       |--------------------|
       | Tools: web_search, |
       |        fetch_url,  |
       |        think_tool, |
       |        delegate    |
       | No file reading.   |
       +--------+-----------+
                | delegates to
                v
       +--------------------+
       |   Analyzer (Leaf)  |
       |--------------------|
       | Tools: read_file,  |
       |        grep_file,  |
       |        think_tool  |
       | No web, no delegate.|
       +--------------------+
```

### Delegation Chain & Tool Separation

- **Orchestrator**: Plans research, dispatches Searchers, synthesizes `final_report.md`. Has NO web tools and NO file reading tools. Delegates ONLY to the Searcher.
- **Searcher**: Searches the web, fetches URLs to the workspace. Has NO file reading tools — forced to delegate to the Analyzer. Delegates ONLY to the Analyzer.
- **Analyzer**: Reads and extracts data from downloaded files. Has NO web tools and NO delegation capability. Leaf node.

This separation prevents any single agent from bloating its context window with raw web content.

### Proportional Search Depth

The Orchestrator assesses query complexity before planning:

- **Simple factual queries**: Dispatch a single Searcher. One authoritative source is sufficient.
- **Multi-fact queries**: A single Searcher is still sufficient.
- **Comparative/synthesis queries**: Dispatch one Searcher per independent angle, concurrently.
- **Deep research**: Full multi-phase approach with multiple delegations.

### Source Quality Awareness

The Searcher evaluates source authority:

- **Authoritative** (official docs, spec sheets): One source is sufficient.
- **Semi-authoritative** (established publications): One is usually enough, a second is welcome.
- **Informal** (forums, blogs): Corroborate with at least one additional source.

### Session Isolation

Each run gets a timestamped isolated folder, for example:

```text
run_1748192400/
```

File tools automatically map all operations into this folder. Agents are unaware of the run folder and read/write files directly.

---

## Privacy & Network Architecture

The recommended privacy-preserving deployment separates search, URL retrieval, and LLM inference.

```text
+--------------------------+
|  Deep Research Agent     |
|--------------------------|
| Local/OpenAI-compatible  |
| model endpoint           |
+-----------+--------------+
            |
            | HTTP JSON search
            v
+--------------------------+
|  SearXNG LXC             |
|--------------------------|
| Listens on :8888         |
| JSON enabled             |
| Outgoing via Tor SOCKS5h |
+-----------+--------------+
            |
            | socks5h://TOR_LXC_IP:9050
            v
+--------------------------+
|  Tor SOCKS5h LXC         |
|--------------------------|
| Listens on 0.0.0.0:9050  |
| Local subnet allowed     |
| All other clients denied |
+-----------+--------------+
            |
            v
        Internet
```

For URL fetching, the agent also uses the Tor SOCKS5h proxy directly:

```text
Deep Research Agent ──► Tor SOCKS5h LXC ──► Target URLs
```

### Privacy Safeguards Added

- **SearXNG-only search path**: `web_search` uses a local SearXNG instance instead of direct public search clients.
- **No hard-coded engine forcing**: SearXNG can use its configured healthy engines unless explicitly configured otherwise.
- **Second onion search**: when enabled, each search performs a second darknet/onion search using `!ahmia !torch`.
- **Tor-only URL retrieval**: `fetch_url_to_workspace` uses the configured Tor SOCKS5h proxy.
- **Remote DNS through Tor**: `socks5h://` is used so DNS resolution is performed through Tor.
- **No clearnet fallback**: if Tor fails or a site blocks Tor, the fetch returns a privacy-preserving error instead of retrying directly.
- **Graceful blocked-site handling**: HTTP `401`, `403`, `429`, and `451` are treated as expected blocked responses.
- **Configurable browser profiles**: request headers are managed in `config.yaml`, allowing coherent browser-like profiles without editing Python code.
- **Stable browser identity by default**: one browser profile is selected per process unless rotation is explicitly enabled.
- **Session-isolated workspace**: each run writes to an isolated workspace folder.
- **Quota enforcement**: tool quotas reduce runaway requests.
- **No shell execution tool**: no arbitrary shell execution is exposed to agents.

---

## Setup Instructions

### 1. Create the Environment & Install

```bash
cd /home/kyuz0/video/deep-research
python -m venv venv
source venv/bin/activate
pip install -e .
```

**System-Wide Installation (Optional):**

```bash
pipx install .
```

### 2. Configure Endpoints

By default, the application uses an OpenAI-compatible API on `localhost:8080`, such as `llama.cpp`. Create a `.env` file:

```env
OPENAI_API_BASE=http://localhost:8080/v1
OPENAI_API_KEY=dummy
OPENAI_MODEL=local-model
```

### 3. Configure the Agent

On first run, the config is auto-created at:

```text
~/.deep-research-agent/config.yaml
```

from:

```text
src/config_template.yaml
```

Key settings:

```yaml
settings:
  concurrency:
    max_concurrent_tasks: 3

  quotas:
    web_search: 15
    fetch_url_to_workspace: 10
    delegate_tasks: 10
    read_workspace_file:
      limit: 60
      rules:
        max_lines: 400

  workspace:
    type: disk
    session_isolation: true
```

### 4. Run the TUI

```bash
python src/app.py
```

### 5. Headless Mode

```bash
python src/app.py --prompt "Compare the AI research strategies of OpenAI, Google DeepMind, and Anthropic in 2024." --auto-approve
```

**Useful Flags:**

- `--prompt "..."`: Run headlessly with a specific query.
- `--auto-approve`: Bypass Human-in-the-Loop tool approvals. Required for headless mode.
- `--list-sessions`: List saved session histories.
- `--resume <session_id>`: Restore a previous session.
- `/toggle_thinking`: Toggle LLM reasoning traces in the TUI.
- `/files`: Browse workspace files in the TUI.

---

## Configuration Reference

The recommended privacy-aware `config.yaml` looks like this:

```yaml
settings:
  search:
    provider: searxng
    searxng:
      base_url: http://tor-searxng:8888
      enable_onion_search: true

      # Optional. Leave unset unless you intentionally want to force engines.
      # standard_engines: google,duckduckgo,bing,brave,wikipedia

  proxy:
    tor_proxy_url: socks5h://tor-proxy:9050

  fetch:
    rotate_browser_profile: false

    browser_profiles:
      chrome_windows:
        User-Agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        Accept-Language: "en-US,en;q=0.9"
        Accept-Encoding: "gzip, deflate, br"
        Cache-Control: "max-age=0"
        Upgrade-Insecure-Requests: "1"

      chrome_linux:
        User-Agent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        Accept-Language: "en-US,en;q=0.9"
        Accept-Encoding: "gzip, deflate, br"
        Cache-Control: "max-age=0"
        Upgrade-Insecure-Requests: "1"

      firefox_windows:
        User-Agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0"
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        Accept-Language: "en-US,en;q=0.9"
        Accept-Encoding: "gzip, deflate, br"
        DNT: "1"
        Upgrade-Insecure-Requests: "1"

  concurrency:
    max_concurrent_tasks: 3

  quotas:
    web_search: 15
    fetch_url_to_workspace: 10
    delegate_tasks: 10
    read_workspace_file:
      limit: 60
      rules:
        max_lines: 400

  workspace:
    type: disk
    session_isolation: true
```

### `settings.search`

Controls the web search backend.

```yaml
settings:
  search:
    provider: searxng
    searxng:
      base_url: http://tor-searxng:8888
      enable_onion_search: true
```

| Setting | Description |
|---|---|
| `provider` | Search provider. Recommended: `searxng`. |
| `base_url` | URL of the local SearXNG instance used by the agent. |
| `enable_onion_search` | Runs a second search using `!ahmia !torch <query>`. |
| `standard_engines` | Optional. If unset, SearXNG chooses its configured engines. |

### `settings.proxy`

Controls Tor-backed URL retrieval.

```yaml
settings:
  proxy:
    tor_proxy_url: socks5h://tor-proxy:9050
```

Use `socks5h://`, not `socks5://`.

The `h` means hostname resolution is performed by the SOCKS proxy, so DNS lookups occur through Tor.

### `settings.fetch`

Controls HTTP request headers for URL fetching.

```yaml
settings:
  fetch:
    rotate_browser_profile: false
    browser_profiles:
      chrome_windows:
        User-Agent: "..."
        Accept: "..."
```

| Setting | Description |
|---|---|
| `rotate_browser_profile` | If `false`, choose one profile per process. If `true`, choose a new profile for each request. |
| `browser_profiles` | Named header profiles used by `fetch_url_to_workspace`. |

Recommended setting:

```yaml
rotate_browser_profile: false
```

A stable profile is usually more coherent than changing browser identity on every request.

### `settings.workspace`

```yaml
settings:
  workspace:
    type: disk
    session_isolation: true
```

| Setting | Description |
|---|---|
| `type` | `disk` or `memory`. |
| `session_isolation` | Creates a timestamped folder for each run. |

### `settings.quotas`

Tool-call limits.

```yaml
settings:
  quotas:
    web_search: 15
    fetch_url_to_workspace: 10
    delegate_tasks: 10
```

Quotas help prevent loops and excessive network access.

### `settings.concurrency`

```yaml
settings:
  concurrency:
    max_concurrent_tasks: 3
```

Controls the number of parallel delegated tasks.

---

## Privacy Infrastructure: Ubuntu Tor SOCKS5h LXC

This section describes a dedicated Ubuntu LXC that provides a Tor SOCKS5h proxy to the local subnet.

Example assumptions:

| Item | Example |
|---|---|
| Tor LXC IP | `192.168.1.20` |
| Local subnet allowed | `192.168.1.0/24` |
| SOCKS port | `9050` |

Replace the example IPs and subnets with your own.

### Install Tor

Inside the Ubuntu Tor LXC:

```bash
sudo apt update
sudo apt install tor ufw -y
```

### Configure Tor to Listen on `0.0.0.0`

Edit:

```bash
sudo nano /etc/tor/torrc
```

Add or update:

```text
RunAsDaemon 1

SocksPort 0.0.0.0:9050

ClientOnly 1
SafeSocks 1
TestSocks 1

Log notice file /var/log/tor/notices.log
```

Restart and enable Tor:

```bash
sudo systemctl restart tor
sudo systemctl enable tor
```

Verify that Tor is listening:

```bash
ss -lnt | grep 9050
```

Expected:

```text
LISTEN 0 4096 0.0.0.0:9050 0.0.0.0:*
```

### Restrict Access to the Local Subnet

Tor does not provide a full subnet allow/deny ACL for the SOCKS listener. Use the LXC firewall instead.

With UFW, allow only your local subnet and deny everything else:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing

sudo ufw allow from 192.168.1.0/24 to any port 9050 proto tcp

sudo ufw enable
sudo ufw status verbose
```

If you manage firewalling on the Proxmox host instead of inside the LXC, apply equivalent rules there.

### Optional nftables Rules

If you prefer `nftables`:

```bash
sudo apt install nftables -y
sudo systemctl enable --now nftables
```

Example `/etc/nftables.conf`:

```nft
#!/usr/sbin/nft -f

flush ruleset

table inet filter {
  chain input {
    type filter hook input priority 0;

    policy drop;

    iif "lo" accept
    ct state established,related accept

    ip saddr 192.168.1.0/24 tcp dport 9050 accept

    tcp dport 22 accept

    counter drop
  }

  chain forward {
    type filter hook forward priority 0;
    policy drop;
  }

  chain output {
    type filter hook output priority 0;
    policy accept;
  }
}
```

Apply:

```bash
sudo nft -f /etc/nftables.conf
```

### Test the Tor SOCKS Proxy

From another machine on the allowed subnet:

```bash
python3 - <<'PY'
import socket

host = "192.168.1.20"
port = 9050

s = socket.create_connection((host, port), timeout=5)
s.sendall(b"\x05\x01\x00")
print(s.recv(2))
s.close()
PY
```

Expected:

```python
b'\x05\x00'
```

Then test outbound Tor:

```bash
curl --socks5-hostname 192.168.1.20:9050 https://check.torproject.org/api/ip
```

---

## Privacy Infrastructure: Ubuntu SearXNG LXC

This section describes a dedicated SearXNG LXC that:

1. Accepts local HTTP search requests.
2. Allows JSON responses.
3. Sends all outbound search-engine traffic through the Tor LXC.

Example assumptions:

| Item | Example |
|---|---|
| SearXNG LXC IP | `192.168.1.21` |
| Tor LXC IP | `192.168.1.20` |
| SearXNG port | `8888` |
| Tor SOCKS port | `9050` |

### Install Docker and SearXNG

Inside the Ubuntu SearXNG LXC:

```bash
sudo apt update
sudo apt install docker.io docker-compose-plugin git curl -y
sudo systemctl enable --now docker
```

Clone SearXNG Docker:

```bash
git clone https://github.com/searxng/searxng-docker.git
cd searxng-docker
cp .env.example .env
```

Start once to generate files:

```bash
sudo docker compose up -d
```

### Configure SearXNG Port

Depending on your `searxng-docker` version, the exposed port may be configured in `.env` or `docker-compose.yaml`.

Set SearXNG to listen on port `8888`.

Example `.env` style:

```env
SEARXNG_HOSTNAME=192.168.1.21
SEARXNG_PORT=8888
```

If the compose file maps ports directly, use:

```yaml
ports:
  - "8888:8080"
```

### Enable JSON Responses

Edit:

```bash
sudo nano searxng/settings.yml
```

Ensure JSON is enabled:

```yaml
search:
  formats:
    - html
    - json
```

Without `json`, the agent's SearXNG API calls will fail or return HTML instead of JSON.

### Configure SearXNG to Use the Tor LXC

In `searxng/settings.yml`, configure outbound proxying:

```yaml
outgoing:
  request_timeout: 20.0
  proxies:
    all://:
      - socks5h://192.168.1.20:9050
```

Use the IP address of the Tor LXC.

Use `socks5h://`, not `socks5://`, so SearXNG sends DNS resolution through Tor.

### Bind SearXNG for LAN Access

In `searxng/settings.yml`:

```yaml
server:
  bind_address: "0.0.0.0"
  port: 8080
```

If Docker maps host `8888` to container `8080`, keep the internal SearXNG port as `8080` and expose `8888` at Docker level.

### Restart SearXNG

```bash
sudo docker compose restart
```

### Verify JSON Output

From the agent host or another allowed machine:

```bash
curl "http://192.168.1.21:8888/search?q=openai&format=json"
```

Expected: JSON output containing a `results` array.

### Verify SearXNG Uses Tor

Exec into the SearXNG container:

```bash
sudo docker compose exec searxng sh
```

Then test the configured proxy:

```bash
python3 - <<'PY'
import httpx

proxy = "socks5h://192.168.1.20:9050"

with httpx.Client(proxy=proxy, timeout=30) as client:
    r = client.get("https://check.torproject.org/api/ip")
    print(r.text)
PY
```

You should see a Tor exit IP.

### Restrict SearXNG Access

Restrict SearXNG to your local subnet. On the SearXNG LXC:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing

sudo ufw allow from 192.168.1.0/24 to any port 8888 proto tcp

sudo ufw enable
sudo ufw status verbose
```

---

## Agent Configuration for LXC Deployment

If using separate LXCs, configure the agent like this:

```yaml
settings:
  search:
    provider: searxng
    searxng:
      base_url: http://192.168.1.21:8888
      enable_onion_search: true

  proxy:
    tor_proxy_url: socks5h://192.168.1.20:9050
```

If all services are in the same Docker Compose network, service names may be used instead:

```yaml
settings:
  search:
    provider: searxng
    searxng:
      base_url: http://tor-searxng:8888
      enable_onion_search: true

  proxy:
    tor_proxy_url: socks5h://tor-proxy:9050
```

Verify that service names resolve to Docker/container IPs, not Tailscale MagicDNS or unrelated hosts:

```bash
getent hosts tor-proxy
getent hosts tor-searxng
```

Docker service names should generally resolve to internal container addresses, not `100.x.x.x` Tailscale addresses.

---

## Testing Fetch and Search Privacy

### Test Tor SOCKS Handshake

```bash
python3 - <<'PY'
import socket

s = socket.create_connection(("192.168.1.20", 9050), timeout=5)
s.sendall(b"\x05\x01\x00")
print(s.recv(2))
s.close()
PY
```

Expected:

```python
b'\x05\x00'
```

### Test Tor Fetch IP

```bash
curl --socks5-hostname 192.168.1.20:9050 https://check.torproject.org/api/ip
```

### Test SearXNG JSON

```bash
curl "http://192.168.1.21:8888/search?q=test&format=json"
```

### Test Agent Fetch Path

Use `fetch_url_to_workspace` against:

```text
https://check.torproject.org/api/ip
```

The saved result should show Tor usage.

### Test Blocked Sites

Some sites block Tor or non-browser clients. For example:

```text
https://www.reuters.com/
```

The expected behavior is a privacy-preserving blocked message, not a clearnet retry.

---

## Included Tools

| Tool | Description |
|------|-------------|
| `web_search` | SearXNG search. Performs a standard search and, when enabled, a second `!ahmia !torch` onion search. |
| `fetch_url_to_workspace` | Fetch URLs through Tor SOCKS5h, parse to Markdown when possible, and save to workspace. |
| `read_workspace_file` | Read files with line-range chunking. |
| `grep_workspace_file` | Regex search within workspace files. |
| `write_workspace_file` | Write files to workspace. |
| `list_workspace_files` | List all workspace files. |
| `write_todos` / `read_todos` | Markdown checkbox task tracking. |
| `think_tool` | Forced reflection pause for structured reasoning. |
| `delegate_tasks` | Auto-injected for agents with children. |

---

## Security

- **No shell execution**: The `run_shell_command` tool is removed from this agent.
- **Quota enforcement**: Every tool has a global call limit to prevent infinite loops.
- **Session isolation**: Each run is sandboxed into its own timestamped folder.
- **Anti-looping directives**: Baked into all agent system prompts to prevent infinite retry cycles.
- **Tor-only URL retrieval**: URL fetching uses the configured Tor SOCKS5h proxy.
- **No clearnet fallback**: Fetch failures do not retry over direct networking.
- **Remote DNS via SOCKS5h**: Use `socks5h://` so hostname resolution happens through Tor.
- **Local SearXNG**: Search traffic goes to a controlled SearXNG instance.
- **SearXNG outbound proxying**: SearXNG should be configured to use the Tor LXC for all outgoing search requests.
- **Firewall-restricted Tor SOCKS listener**: Tor listens on `0.0.0.0:9050`, but only the local subnet should be allowed to connect.
- **Firewall-restricted SearXNG listener**: SearXNG should only accept requests from trusted local hosts/subnets.
- **Configurable browser profiles**: Fetch request headers are controlled through `config.yaml`.

---

## Troubleshooting

### `Connection reset by peer` on SOCKS test

A proper SOCKS5 listener replies:

```python
b'\x05\x00'
```

If the connection resets, the host/port is probably not a SOCKS5 proxy, Tor is not listening, or a firewall is interfering.

Check:

```bash
ss -lnt | grep 9050
sudo systemctl status tor
sudo journalctl -u tor --no-pager -n 100
```

### `401`, `403`, `429`, or `451` while fetching

This usually means the target site blocks Tor, datacenter IPs, or non-browser clients.

The expected privacy-preserving behavior is to return a blocked message and not retry over clearnet.

### SearXNG returns HTML instead of JSON

Enable JSON in `searxng/settings.yml`:

```yaml
search:
  formats:
    - html
    - json
```

Then restart SearXNG.

### SearXNG search fails for specific engines

Avoid forcing fragile engine lists unless needed. Let SearXNG use its configured engines.

### Hostname resolves to Tailscale instead of Docker

Check:

```bash
getent hosts tor-proxy
```

If it resolves to `100.x.x.x`, that is a Tailscale address, not a Docker service. Use a unique service name, an explicit LXC IP, or correct the Docker network/DNS configuration.

---

## Notes on Anonymity

This setup improves privacy, but it is not a guarantee of perfect anonymity.

Important limitations:

- `httpx` does not have the same TLS fingerprint as a real browser.
- Changing `User-Agent` does not make requests indistinguishable from Chrome or Firefox.
- Sites may still block Tor exits.
- Cookies, JavaScript challenges, CAPTCHAs, and bot defenses may prevent access.
- Network-level firewall rules are stronger than relying on application code alone.

For stronger enforcement, firewall the agent so it can only connect to:

- the local LLM endpoint,
- the SearXNG LXC,
- the Tor SOCKS LXC.

This prevents accidental direct outbound traffic even if a code path is misconfigured.
