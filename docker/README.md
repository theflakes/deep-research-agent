# Deep Research Agent Environment (Interactive TUI Deployment)

This stack orchestrates an isolated research environment featuring a containerized custom Python agent running an interactive Terminal User Interface (TUI). All workspace data, session maps, and report artifacts are persistently stored in your local host home directory (`~/.deep-research-agent`).

## Setup and Run Guide
```
[ Host Machine / Local Subnet ]
                │
  ┌─────────────▼────────────────────────────────────────┐
  │ Docker Bridge Network ("research-net")               │
  │                                                      │
  │  ┌────────────────┐       ┌──────────────┐           │
  │  │ research-agent │ ───►  │ tor-searxng  │           │
  │  └────────────────┘       └──────┬───────┘           │
  │                                  │                   │
  │                                  ▼ (SOCKS5h Proxy)   │
  │                           ┌──────────────┐           │
  │                           │  tor-proxy   │           │
  │                           └──────┬───────┘           │
  └──────────────────────────────────┼───────────────────┘
                                     │
                                     ▼ [ Docker NAT / Host Gateway ]
                                     │
                        ┌────────────┴────────────┐
                        │ Public Tor Network      │
                        │ (Entry ──► Mid ──► Exit)│
                        └────────────┬────────────┘
                                     │
                                     ▼
                        ┌─────────────────────────┐
                        │  Clear Web or .onion    │
                        │  (Google, DDG, Ahmia)   │
                        └─────────────────────────┘
```
### 1. Initialize Configuration Directory
Because the application writes its workspaces to `~/.{APP_NAME}/workspace`, we map the container's root home folder directly to your local drive. 

Create the storage directory and save your exact configuration file inside it:
```bash
mkdir -p ~/.deep-research-agent
nano ~/.deep-research-agent/config.yaml

```

*(Paste your config block with your `local-model` base URL, search providers, quotas, and workspace settings exactly as provided here).*

### 2. Boot Up Back-end Utilities

Bring up the background network infrastructure, Redis caching tier, and the SearXNG search engine container in detached mode:

```bash
docker compose up -d tor-proxy searxng-redis tor-searxng

```

### 3. Run the Interactive TUI Research Agent

To execute the application and use the interactive keyboard/terminal UI interface natively on your host shell without manual container entry, run:

```bash
docker compose run --rm research-agent python main.py

```

---

## Environment Lifecycle Management

Use these commands to manage the system state, clean up data, or rebuild components.

### Stop and Take Down the Environment

To stop the running infrastructure containers (`tor-proxy`, `searxng-redis`, `tor-searxng`) without losing cached data or volume allocations:

```bash
docker compose stop

```

### Destroy and Delete Containers

To completely stop and remove all containers and network interfaces created by this stack:

```bash
docker compose down

```

### Reset / Purge the Entire Environment (Hard Reset)

To stop the environment, delete all containers, tear down networks, and **completely erase the underlying Redis data caches**:

```bash
docker compose down -v

```

*Note: This cleans up Docker cache bloat but preserves your generated research markdown files inside `~/.deep-research-agent/workspace/` on your host machine.*

### Rebuild the Python Agent Image

If the upstream repository (`theflakes/deep-research-agent`) receives updates and you want to pull the latest codebase and rebuild the container from scratch:

```bash
docker compose build --no-cache research-agent

```

---

## Monitoring & Troubleshooting

### View Infrastructure Logs

If SearXNG is timing out or you suspect Tor isn't routing properly, stream the real-time background logs:

```bash
# View logs for all background services
docker compose logs -f tor-proxy tor-searxng

# View logs for a specific service (e.g., Tor only)
docker compose logs -f tor-proxy

```

### Verify Container Status

To see which components of the research stack are currently active, their uptime, and their exposed ports:

```bash
docker compose ps

```

### Data Handling and Persistence

* **TUI Execution:** The `--rm` flag appended to the `docker compose run` command automatically deletes the transient interactive container container instance when you exit the TUI, keeping your Docker system footprint completely clean.
* **Persistent Artifacts:** Because of the host volume mount (`~/.deep-research-agent`), all markdown reports, timestamped session isolation blocks, and generated research data are preserved on your physical machine inside `~/.deep-research-agent/workspace/`.
