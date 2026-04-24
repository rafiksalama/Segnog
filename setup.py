#!/usr/bin/env python3
"""
Segnog Setup Wizard — Interactive configuration and deployment.

Usage:
    python setup.py              Interactive setup wizard
    python setup.py --quick      Non-interactive (use existing config)
    python setup.py --skip-pull  Skip Docker image pull
    python setup.py --stop       Stop containers
    python setup.py --status     Show container status
"""

import argparse
import getpass
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

# ── Constants ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
DOCKER_IMAGE = "rafiksalama/segnog:latest"
SETTINGS_FILE = PROJECT_ROOT / "settings.toml"
SECRETS_FILE = PROJECT_ROOT / ".secrets.toml"
ENV_FILE = PROJECT_ROOT / ".env"
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"

DEFAULT_LLM_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = ""
DEFAULT_EMBED_URL = "https://api.openai.com/v1"
DEFAULT_EMBED_MODEL = ""
DEFAULT_REST_PORT = 9000
DEFAULT_GRPC_PORT = 50051
DEFAULT_EMBED_BACKEND = "remote"
DEFAULT_LOCAL_EMBED_MODEL = "google/embeddinggemma-300m"


# ── ANSI Colors ──────────────────────────────────────────────────────────────
class C:
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def bold(t):
    return f"{C.BOLD}{t}{C.RESET}"


def green(t):
    return f"{C.GREEN}{t}{C.RESET}"


def yellow(t):
    return f"{C.YELLOW}{t}{C.RESET}"


def red(t):
    return f"{C.RED}{t}{C.RESET}"


def cyan(t):
    return f"{C.CYAN}{t}{C.RESET}"


def dim(t):
    return f"{C.DIM}{t}{C.RESET}"


# ── TOML Serializer (stdlib-only, handles flat sections with scalar values) ─
def toml_val(v):
    """Serialize a Python value to TOML."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return str(v)


def dict_to_toml(data, prefix=""):
    """Serialize a nested dict to TOML string. Only handles [section] key=val."""
    lines = []
    # Collect top-level keys that are dicts (sections)
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            lines.append(f"\n[{full_key}]")
            for k, v in value.items():
                if isinstance(v, dict):
                    # Nested sub-section
                    sub_key = f"{full_key}.{k}"
                    lines.append(f"\n[{sub_key}]")
                    for sk, sv in v.items():
                        lines.append(f"{sk} = {toml_val(sv)}")
                else:
                    lines.append(f"{k} = {toml_val(v)}")
    return "\n".join(lines) + "\n"


# ── Pre-flight Checks ───────────────────────────────────────────────────────
def check_docker():
    """Check if Docker daemon is running."""
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def port_in_use(port):
    """Check if a port is already bound on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def find_free_port(start):
    """Find the next available port starting from `start`."""
    port = start
    while port < start + 100:
        if not port_in_use(port):
            return port
        port += 1
    return None


# ── Input Helpers ────────────────────────────────────────────────────────────
def prompt(text, default="", secret=False):
    """Prompt user for input. Returns default on empty input."""
    suffix = f" [{cyan(default)}]" if default else ""
    if secret:
        val = getpass.getpass(f"  {text}{suffix}: ")
    else:
        val = input(f"  {text}{suffix}: ")
    return val.strip() or default


def prompt_yes_no(text, default=True):
    """Yes/no prompt."""
    hint = "[Y/n]" if default else "[y/N]"
    val = input(f"  {text} {hint}: ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes")


# ── Config I/O ──────────────────────────────────────────────────────────────
def load_existing_settings():
    """Load existing settings.toml, preserving all sections."""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "rb") as f:
                return tomllib.load(f)
        except Exception:
            pass
    return {}


def load_existing_secrets():
    """Load existing .secrets.toml for default values."""
    if SECRETS_FILE.exists():
        try:
            with open(SECRETS_FILE, "rb") as f:
                return tomllib.load(f)
        except Exception:
            pass
    return {}


def load_existing_env():
    """Load existing .env as dict."""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def backup_file(path):
    """Create a timestamped backup of an existing file."""
    if path.exists() and path.stat().st_size > 0:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = path.parent / f"{path.stem}.{ts}.bak"
        shutil.copy2(path, backup)
        print(f"  {dim(f'Backed up {path.name} → {backup.name}')}")


def write_settings_toml(config, existing):
    """Write settings.toml preserving all non-modified sections."""
    # Deep merge: start with existing, overlay with user config
    merged = existing.copy()

    for section in ("default",):
        if section not in merged:
            merged[section] = {}
        for key in ("llm", "embeddings", "rest", "grpc"):
            if key not in merged[section]:
                merged[section][key] = {}
            if key in config and isinstance(config[key], dict):
                merged[section][key].update(config[key])

    backup_file(SETTINGS_FILE)
    SETTINGS_FILE.write_text(dict_to_toml(merged))
    print(f"  {green(f'{SETTINGS_FILE.name} written')}")


def write_secrets_toml(llm_key, embed_key):
    """Write .secrets.toml with API keys."""
    content = (
        "dynaconf_merge = true\n"
        "\n"
        "[default.embeddings]\n"
        f'api_key = "{embed_key}"\n'
        "\n"
        "[default.llm]\n"
        f'api_key = "{llm_key}"\n'
    )
    backup_file(SECRETS_FILE)
    SECRETS_FILE.write_text(content)
    os.chmod(SECRETS_FILE, 0o600)
    print(f"  {green(f'{SECRETS_FILE.name} written')}")


def write_env_file(llm_key, embed_key, rest_port, grpc_port, hf_token=""):
    """Write .env for docker-compose interpolation."""
    content = f"LLM_API_KEY={llm_key}\nEMBEDDINGS_API_KEY={embed_key}\n"
    if hf_token:
        content += f"HF_TOKEN={hf_token}\n"
    content += f"PORT={rest_port}\nGRPC_PORT={grpc_port}\n"
    backup_file(ENV_FILE)
    ENV_FILE.write_text(content)
    os.chmod(ENV_FILE, 0o600)
    print(f"  {green(f'{ENV_FILE.name} written')}")


def write_docker_compose(
    rest_port, grpc_port, local_embed=False, mount_host="", mount_container="/app/data"
):
    """Generate docker-compose.yml with generic env var names."""
    env_lines = (
        "      - MEMORY_SERVICE_REST__HOST=0.0.0.0\n"
        f"      - MEMORY_SERVICE_REST__PORT={rest_port}\n"
        "      - MEMORY_SERVICE_EMBEDDINGS__API_KEY=${EMBEDDINGS_API_KEY}\n"
        "      - MEMORY_SERVICE_LLM__API_KEY=${LLM_API_KEY}\n"
    )
    if local_embed:
        env_lines += "      - HF_TOKEN=${HF_TOKEN}\n"

    vol_lines = (
        "    volumes:\n"
        "      - dragonfly_data:/data/dragonfly\n"
        "      - falkordb_data:/data/falkordb\n"
        "      - nats_data:/data/nats\n"
        "      - ./settings.toml:/app/settings.toml:ro\n"
    )
    if mount_host:
        vol_lines += f"      - {mount_host}:{mount_container}\n"

    content = (
        "services:\n"
        "  segnog:\n"
        f"    image: {DOCKER_IMAGE}\n"
        "    ports:\n"
        f'      - "${{GRPC_PORT:-{grpc_port}}}:{grpc_port}"\n'
        f'      - "${{PORT:-{rest_port}}}:{rest_port}"\n'
        "    environment:\n"
        f"{env_lines}"
        f"{vol_lines}"
        "    restart: unless-stopped\n"
        "\n"
        "volumes:\n"
        "  dragonfly_data:\n"
        "  falkordb_data:\n"
        "  nats_data:\n"
    )
    backup_file(COMPOSE_FILE)
    COMPOSE_FILE.write_text(content)
    print(f"  {green(f'{COMPOSE_FILE.name} written')}")


# ── Docker Operations ───────────────────────────────────────────────────────
def run_command(cmd, description=""):
    """Run a command with real-time output. Returns exit code."""
    if description:
        print(f"  {dim(description)}...")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            print(f"    {line.rstrip()}")
        proc.wait()
        return proc.returncode
    except KeyboardInterrupt:
        proc.kill()
        print(f"\n  {yellow('Cancelled.')}")
        return 1


def compose_cmd():
    """Return the docker compose command (v2 or v1)."""
    # Try docker compose (v2, plugin)
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return ["docker", "compose"]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # Fallback to docker-compose (v1)
    return ["docker-compose"]


def pull_image(skip=False):
    """Pull the Segnog Docker image."""
    if skip:
        print(f"  {dim('Skipping image pull (--skip-pull)')}")
        return True
    rc = run_command(
        ["docker", "pull", DOCKER_IMAGE],
        f"Pulling {DOCKER_IMAGE}",
    )
    if rc != 0:
        print(f"  {yellow('Image pull failed. Trying with local image...')}")
        # Check if image exists locally
        result = subprocess.run(
            ["docker", "image", "inspect", DOCKER_IMAGE],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    return True


def start_containers():
    """Start containers with docker compose."""
    cmd = compose_cmd() + ["up", "-d"]
    rc = run_command(cmd, "Starting Segnog")
    return rc == 0


def stop_containers():
    """Stop and remove containers."""
    cmd = compose_cmd() + ["down"]
    print(f"  {dim('Stopping Segnog containers...')}")
    rc = subprocess.run(cmd, capture_output=True, text=True)
    if rc.returncode == 0:
        print(f"  {green('Containers stopped.')}")
    else:
        print(f"  {yellow('No containers running or error stopping.')}")
        if rc.stderr:
            print(f"  {dim(rc.stderr.strip())}")


def show_status():
    """Show container status and health."""
    # Container status
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            "name=segnog",
            "--format",
            "table {{.Names}}\t{{.Status}}\t{{.Ports}}",
        ],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        print(f"\n  {bold('Container Status:')}")
        for line in result.stdout.strip().splitlines():
            print(f"  {line}")
    else:
        print(f"\n  {yellow('No Segnog containers running.')}")

    # Try health check on default port
    for port in [9000, 9001, 9002, 8080]:
        try:
            req = Request(f"http://localhost:{port}/health")
            with urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                status = data.get("status", "unknown")
                color = green if status == "ok" else yellow
                print(f"\n  {bold(f'Health Check (:{port}):')} {color(status)}")
                break
        except Exception:
            continue


# ── Health Check ────────────────────────────────────────────────────────────
def wait_for_health(port, timeout=90):
    """Poll /health until 200 or timeout."""
    url = f"http://localhost:{port}/health"
    start = time.time()
    print(f"\n  {dim('Waiting for service to become healthy...')}")
    while time.time() - start < timeout:
        try:
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                status = data.get("status", "")
                if status in ("ok", "degraded"):
                    return True
        except Exception:
            pass
        elapsed = int(time.time() - start)
        print(f"\r  {dim(f'Waiting... {elapsed}s')}", end="", flush=True)
        time.sleep(2)
    print()  # newline after spinner
    return False


# ── Post-Deploy Validation ────────────────────────────────────────────────
def run_post_deploy_checks(port):
    """Run validation checks after service is healthy."""
    base = f"http://localhost:{port}"
    passed = 0
    failed = 0

    print(f"\n  {bold('Running post-deployment checks...')}")

    # 1. Health endpoint
    try:
        req = Request(f"{base}/health")
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            status = data.get("status", "")
            if status in ("ok", "degraded"):
                print(f"  {green('[PASS]')} Health check — {status}")
                passed += 1
            else:
                print(f"  {red('[FAIL]')} Health check — unexpected status: {status}")
                failed += 1
    except Exception as e:
        print(f"  {red('[FAIL]')} Health check — {e}")
        failed += 1

    # 2. UI stats
    try:
        req = Request(f"{base}/api/v1/memory/ui/stats")
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            ep = data.get("episodes", "?")
            kn = data.get("knowledge_nodes", "?")
            onto = data.get("ontology_entities", "?")
            causal = data.get("causal_claims", "?")
            print(
                f"  {green('[PASS]')} UI stats — episodes={ep}, knowledge={kn}, ontology={onto}, causal={causal}"
            )
            passed += 1
    except Exception as e:
        print(f"  {yellow('[WARN]')} UI stats — {e}")
        failed += 1

    # 3. Search endpoint (validates embedding backend is working)
    try:
        payload = json.dumps({"query": "test", "top_k": 1, "group_id": "default"}).encode()
        req = Request(
            f"{base}/api/v1/memory/episodes/search",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            print(f"  {green('[PASS]')} Episode search — embedding backend working")
            passed += 1
    except Exception as e:
        print(f"  {yellow('[WARN]')} Episode search — {e}")
        failed += 1

    # 4. UI serving
    try:
        req = Request(f"{base}/")
        with urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                print(f"  {green('[PASS]')} Web UI — serving at /")
                passed += 1
            else:
                print(f"  {yellow('[WARN]')} Web UI — status {resp.status}")
                failed += 1
    except Exception as e:
        print(f"  {yellow('[WARN]')} Web UI — {e}")
        failed += 1

    print(f"\n  {bold('Results:')} {green(f'{passed} passed')}, {red(f'{failed} failed')}")
    return failed == 0


# ── Interactive Wizard ─────────────────────────────────────────────────────
def run_interactive(skip_pull=False):
    """Run the full interactive setup wizard."""
    print(f"\n{bold('========================================')}")
    print(f"{bold('  Segnog Setup Wizard')}")
    print(f"{bold('  Agent Memory Service Configuration')}")
    print(f"{bold('========================================')}\n")

    # ── Pre-flight ──
    print(f"{bold('Checking prerequisites...')}")
    if not check_docker():
        print(f"  {red('Docker is not running.')}")
        print(f"  {dim('Please start Docker Desktop (macOS) or the Docker daemon (Linux).')}")
        sys.exit(1)
    print(f"  {green('Docker')} — OK")

    # Port checks
    rest_port = DEFAULT_REST_PORT
    grpc_port = DEFAULT_GRPC_PORT

    if port_in_use(rest_port):
        free = find_free_port(rest_port)
        if free:
            print(f"  {yellow(f'Port {rest_port} is in use. Next free: {free}')}")
            rest_port = free
        else:
            print(f"  {red(f'Cannot find free port near {rest_port}!')}")
            sys.exit(1)
    else:
        print(f"  {green('REST port')} :{rest_port} — available")

    if port_in_use(grpc_port):
        free = find_free_port(grpc_port)
        if free:
            print(f"  {yellow(f'Port {grpc_port} is in use. Next free: {free}')}")
            grpc_port = free
        else:
            print(f"  {red(f'Cannot find free port near {grpc_port}!')}")
            sys.exit(1)
    else:
        print(f"  {green('gRPC port')} :{grpc_port} — available")

    # ── Load existing config for defaults ──
    existing = load_existing_settings()
    secrets = load_existing_secrets()

    def defaults(section, key, fallback=""):
        return existing.get("default", {}).get(section, {}).get(key) or fallback

    def secret_default(section, key):
        return secrets.get("default", {}).get(section, {}).get(key) or ""

    # ── Step 1: LLM ──
    print(f"\n{bold('Step 1: LLM Provider')}")
    print(f"{dim('Configure the LLM used for knowledge extraction, entity recognition, etc.')}")

    llm_url = prompt("LLM base URL", defaults("llm", "base_url", DEFAULT_LLM_URL))
    llm_key = prompt("LLM API key", secret_default("llm", "api_key"), secret=True)
    llm_model = prompt("LLM model name", defaults("llm", "flash_model", DEFAULT_LLM_MODEL))

    while not llm_key:
        print(f"  {red('API key is required.')}")
        llm_key = prompt("LLM API key", "", secret=True)

    # ── Step 2: Embeddings ──
    print(f"\n{bold('Step 2: Embedding Provider')}")
    print(f"{dim('Configure the embedding model used for semantic search.')}")

    print("  Embedding backend options:")
    print("    1. remote — OpenAI-compatible API (recommended for production)")
    print("    2. local  — sentence-transformers on CPU (fast, no API needed)")
    backend_choice = prompt("Choose embedding backend [1/2]", "1")
    if backend_choice.strip() == "2":
        embed_backend = "local"
    else:
        embed_backend = "remote"

    hf_token = ""
    if embed_backend == "local":
        print(f"\n  {cyan('Local embedding mode selected.')}")
        print(f"  {dim('The model will be downloaded inside the container on first start.')}")
        embed_model = prompt(
            "Embedding model name", defaults("embeddings", "model", DEFAULT_LOCAL_EMBED_MODEL)
        )
        hf_token = prompt("HuggingFace token (required for gated models)", "", secret=True)
        while not hf_token:
            print(f"  {red('HuggingFace token is required for downloading models.')}")
            hf_token = prompt("HuggingFace token", "", secret=True)
        embed_url = ""
        embed_key = ""
    else:
        print(f"\n  {cyan('Remote embedding mode selected.')}")
        embed_url = prompt(
            "Embedding base URL", defaults("embeddings", "base_url", DEFAULT_EMBED_URL)
        )
        embed_key = prompt(
            "Embedding API key (Enter to use LLM key)",
            secret_default("embeddings", "api_key"),
            secret=True,
        )
        if not embed_key:
            embed_key = llm_key
        embed_model = prompt(
            "Embedding model name", defaults("embeddings", "model", DEFAULT_EMBED_MODEL)
        )

    # ── Step 3: Ports ──
    print(f"\n{bold('Step 3: Network Ports')}")
    print(f"{dim('Host ports mapped to the container. Leave default unless you have conflicts.')}")

    rest_input = prompt("REST port", str(rest_port))
    try:
        rest_port = int(rest_input)
    except ValueError:
        print(f"  {yellow(f'Invalid port, using {rest_port}')}")

    grpc_input = prompt("gRPC port", str(grpc_port))
    try:
        grpc_port = int(grpc_input)
    except ValueError:
        print(f"  {yellow(f'Invalid port, using {grpc_port}')}")

    # ── Step 4: Mount folder ──
    print(f"\n{bold('Step 4: Data Mount')}")
    print(
        f"{dim('Mount a local folder into the container for persistent data (e.g. HuggingFace cache).')}"
    )

    mount_host = prompt("Host folder path (Enter to skip)", "")
    mount_container = "/app/data"
    if mount_host:
        mount_host = os.path.abspath(mount_host)
        if not os.path.isdir(mount_host):
            if prompt_yes_no(f"Folder {mount_host} does not exist. Create it?", default=True):
                os.makedirs(mount_host, exist_ok=True)
                print(f"  {green(f'Created {mount_host}')}")
            else:
                print(f"  {yellow('Skipping mount — folder not created.')}")
                mount_host = ""
        mount_container = prompt("Container mount path", "/app/data")

    # ── Review ──
    embed_label = f"{embed_model} ({embed_backend})"
    if embed_backend == "local":
        embed_label = f"{embed_model} (local CPU)"
    print(f"\n{bold('========================================')}")
    print(f"  {bold('LLM:')}       {llm_model}")
    print(f"  {bold('LLM URL:')}   {llm_url}")
    print(f"  {bold('Embed:')}     {embed_label}")
    if embed_backend == "remote":
        print(f"  {bold('Embed URL:')} {embed_url}")
    print(f"  {bold('REST:')}      :{rest_port}")
    print(f"  {bold('gRPC:')}      :{grpc_port}")
    if mount_host:
        print(f"  {bold('Mount:')}     {mount_host} → {mount_container}")
    print(f"{bold('========================================')}\n")

    if not prompt_yes_no("Proceed with this configuration?"):
        print(f"\n  {yellow('Setup cancelled.')}")
        sys.exit(0)

    # ── Write config ──
    print(f"\n{bold('Writing configuration...')}")

    config = {
        "llm": {"base_url": llm_url, "flash_model": llm_model},
        "embeddings": {"base_url": embed_url, "model": embed_model, "backend": embed_backend},
        "rest": {"host": "0.0.0.0", "port": rest_port},
        "grpc": {"port": grpc_port},
    }
    write_settings_toml(config, existing)
    write_secrets_toml(llm_key, embed_key)
    write_env_file(llm_key, embed_key, rest_port, grpc_port, hf_token=hf_token)
    write_docker_compose(
        rest_port,
        grpc_port,
        local_embed=(embed_backend == "local"),
        mount_host=mount_host,
        mount_container=mount_container,
    )

    # ── Pull & Start ──
    print()
    if not pull_image(skip=skip_pull):
        print(f"  {red('Cannot proceed without Docker image.')}")
        sys.exit(1)

    if not start_containers():
        print(f"  {red('Failed to start containers.')}")
        sys.exit(1)

    # ── Health Check + Post-Deploy Validation ──
    health_timeout = 300 if embed_backend == "local" else 90
    print(f"\n  {dim(f'Waiting for service (timeout {health_timeout}s)...')}")
    if wait_for_health(rest_port, timeout=health_timeout):
        run_post_deploy_checks(rest_port)
        print(f"\n{bold('========================================')}")
        print(f"  {green(bold('Segnog is running!'))}")
        print(f"{bold('========================================')}")
        print(f"  REST API:  {cyan(f'http://localhost:{rest_port}')}")
        print(f"  gRPC:      {cyan(f'localhost:{grpc_port}')}")
        print(f"  UI:        {cyan(f'http://localhost:{rest_port}')}")
        print(f"  API Docs:  {cyan(f'http://localhost:{rest_port}/api/v1/memory/docs')}")
        print(f"  Health:    {cyan(f'http://localhost:{rest_port}/health')}")
        print(f"{bold('========================================')}")
        print(f"\n  {dim('To stop:  docker compose down')}")
        print(f"  {dim('To logs: docker compose logs -f')}")
        print()
    else:
        print(f"\n  {yellow('Service did not become healthy within timeout.')}")
        print(f"  {dim('Check logs: docker compose logs -f')}")


def run_quick(skip_pull=False):
    """Non-interactive setup using existing config."""
    print(f"\n  {bold('Quick setup — using existing configuration...')}")

    if not check_docker():
        print(f"  {red('Docker is not running.')}")
        sys.exit(1)

    existing = load_existing_settings()
    secrets = load_existing_secrets()

    defaults_section = existing.get("default", {})
    llm_section = defaults_section.get("llm", {})
    embed_section = defaults_section.get("embeddings", {})
    rest_section = defaults_section.get("rest", {})
    grpc_section = defaults_section.get("grpc", {})

    llm_url = llm_section.get("base_url", DEFAULT_LLM_URL)
    llm_model = llm_section.get("flash_model", DEFAULT_LLM_MODEL)
    embed_url = embed_section.get("base_url", DEFAULT_EMBED_URL)
    embed_model = embed_section.get("model", DEFAULT_EMBED_MODEL)
    embed_backend = embed_section.get("backend", DEFAULT_EMBED_BACKEND)
    rest_port = rest_section.get("port", DEFAULT_REST_PORT)
    grpc_port = grpc_section.get("port", DEFAULT_GRPC_PORT)

    # Get API keys from secrets or env
    llm_key = secrets.get("default", {}).get("llm", {}).get("api_key") or os.environ.get(
        "MEMORY_SERVICE_LLM__API_KEY", ""
    )
    embed_key = (
        secrets.get("default", {}).get("embeddings", {}).get("api_key")
        or os.environ.get("MEMORY_SERVICE_EMBEDDINGS__API_KEY", "")
        or llm_key
    )

    # Get HF token from .env for local embedding
    existing_env = load_existing_env()
    hf_token = existing_env.get("HF_TOKEN", "")

    if not llm_key:
        print(f"  {red('No LLM API key found in .secrets.toml or environment.')}")
        print(f"  {dim('Run without --quick for interactive setup.')}")
        sys.exit(1)

    local_embed = embed_backend == "local"
    config = {
        "llm": {"base_url": llm_url, "flash_model": llm_model},
        "embeddings": {"base_url": embed_url, "model": embed_model, "backend": embed_backend},
        "rest": {"host": "0.0.0.0", "port": rest_port},
        "grpc": {"port": grpc_port},
    }
    write_settings_toml(config, existing)
    write_secrets_toml(llm_key, embed_key)
    write_env_file(llm_key, embed_key, rest_port, grpc_port, hf_token=hf_token)
    write_docker_compose(rest_port, grpc_port, local_embed=local_embed)

    print()
    if not pull_image(skip=skip_pull):
        print(f"  {red('Cannot proceed without Docker image.')}")
        sys.exit(1)

    if not start_containers():
        print(f"  {red('Failed to start containers.')}")
        sys.exit(1)

    health_timeout = 300 if local_embed else 90
    if wait_for_health(rest_port, timeout=health_timeout):
        run_post_deploy_checks(rest_port)
        print(f"\n  {green(bold('Segnog is running!'))} → http://localhost:{rest_port}")
    else:
        print(f"\n  {yellow('Service did not become healthy within timeout.')}")


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    if sys.version_info < (3, 11):
        print(
            f"{red('Python 3.11+ required.')} You have {sys.version_info.major}.{sys.version_info.minor}"
        )
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Segnog Setup Wizard — configure and deploy the memory service",
    )
    parser.add_argument(
        "--quick", action="store_true", help="Non-interactive (use existing config)"
    )
    parser.add_argument("--skip-pull", action="store_true", help="Skip Docker image pull")
    parser.add_argument("--stop", action="store_true", help="Stop running containers")
    parser.add_argument("--status", action="store_true", help="Show container status")

    args = parser.parse_args()

    if args.stop:
        stop_containers()
    elif args.status:
        show_status()
    elif args.quick:
        run_quick(skip_pull=args.skip_pull)
    else:
        run_interactive(skip_pull=args.skip_pull)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {yellow('Setup cancelled.')}")
        sys.exit(0)
