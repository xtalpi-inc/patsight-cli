# patsight-cli

patsight-cli  is a command-line tool used to submit and query PatSight patent PDF extraction tasks. Users can perform operations such as logging in, task submission, status query, result retrieval, and report generation through the terminal. Tasks submitted via patsight-cli  will be synchronously added to PatSight's task list and consume the corresponding Credits points according to the rules.After the task is completed, users can either directly obtain the results via the CLI and continue with subsequent processing, or log in to the PatSight page for viewing and verification. 

 Applicable scenarios include:

- Submit patent PDFs individually or in batches
- Obtain CSV results for subsequent analysis 
- Generate HTML reports that are easy to read and share
 
## Requirements

- **Python** 3.11 or newer
- Network access to the configured PatSight and OPS hosts (when using the `patsight` client)

---

## Installation

### Install the CLI and library (recommended)

After installation, both the `patsight-cli` command and `import patsight_cli` are available in that environment.

**From GitHub**:

```bash
pip install "git+https://github.com/xtalpi-inc/patsight-cli.git"
```

**Editable install** (contributors or local development):

```bash
git clone https://github.com/xtalpi-inc/patsight-cli.git
cd patsight-cli
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
```

**Using [uv](https://github.com/astral-sh/uv)** (optional):

```bash
cd patsight-cli
uv venv && source .venv/bin/activate
uv sync                 # editable install
uv sync --extra dev     # includes pytest
```

### Verify the installation

```bash
patsight-cli --help
python -c "import patsight_cli; print(patsight_cli.__version__)"
```

If you see `ModuleNotFoundError: No module named 'patsight_cli'`, activate the same virtual environment where you installed the package, or use `python -m pip install ...` with that interpreter.

---

## Configuration and environment variables

Configure credentials and optional paths **before** using the PatSight client (CLI or library). You can use a `.env` file in the working directory, export variables in the shell, or pass arguments in code / CLI flags.

### Summary: required vs optional

| Name | Required | Notes |
|------|----------|--------|
| **PatSight authentication** | | |
| `PATSIGHT_OPS_ACCOUNT` or `PATSIGHT_ACCOUNT` | **Conditional** | Required for login **unless** you use a valid `PATSIGHT_TOKEN` or pass `--account` / constructor `account=`. |
| `PATSIGHT_OPS_PASSWORD` or `PATSIGHT_PASSWORD` | **Conditional** | Required for login **unless** you use a valid `PATSIGHT_TOKEN` or pass `--password` / constructor `password=`. |
| `PATSIGHT_TOKEN` | Optional | If set and still valid, OPS password login can be skipped. |
| **API hosts (PatSight client)** | | |
| `PATSIGHT_URL` | Optional | PatSight site origin; patent API base is `{PATSIGHT_URL}/patent/api`. Default: `https://patent.xinsight-ai.com` |
| `OPS_URL` | Optional | OPS origin; token and verify URLs are derived under `/api/...`. Default: `https://xops.xtalpi.com` |
| **Local storage (patsight-cli)** | | |
| `PATSIGHT_CLI_CLIENT_DB` | Optional | SQLite database for cached tokens and job metadata. Default: `~/.local/share/patsight-cli/tasks.db`. Legacy aliases: `XCLI_CLIENT_DB`, `PATSIGHT_CLIENT_DB`. |
| `PATSIGHT_CLI_WORKDIR` | Optional | Directory for downloaded exports (e.g. CSV). Default: `~/.local/share/patsight-cli/output`. Legacy aliases: `XCLI_WORKDIR`, `PATSIGHT_WORKDIR`. |

**Not** required for `patsight-cli clients` (lists registered client types only).

Copy `.env.example` to `.env` and fill in values for your environment.

### Loading `.env` in different contexts

- **CLI (`patsight-cli ...`)**: loads `.env` automatically from the current directory tree (via `python-dotenv`).
- **Library (`import patsight_cli`)**: does **not** load `.env` automatically. Call `load_dotenv()` yourself if you use a `.env` file:

  ```python
  from dotenv import find_dotenv, load_dotenv
  load_dotenv(find_dotenv())
  ```

Optional YAML profiles are documented in `docs/examples/profile.yaml` (`--config` / `--profile` on the CLI).

---

## Command-line usage

### Global options

| Option | Description |
|--------|-------------|
| `--config PATH` | YAML file with named profiles (optional). |
| `--profile NAME` | Profile name inside `--config`. |
| `--verbose` | Enable debug logging. |

### Subcommands

| Command | Purpose |
|---------|---------|
| `clients` | List registered client type names. |
| `login` | Verify credentials and cache token (PatSight). |
| `submit` | Submit a job (PatSight: PDF path and `--job-type`). |
| `status` | Query job status by `--job-id`. |
| `result` | Fetch finished result and export CSV under workdir. |
| `report` | Generate HTML summary from live API or `--from-json`. |

PatSight-related flags include `--account`, `--password`, `--token`, `--folder-id`, `--patsight-url`, `--ops-url`, and URL overrides; see `patsight-cli <command> --help`.

### Which backend does a command use?

- **`--client` selects the client type.** The default is **`patsight`**, so if you omit `--client`, every command uses the PatSight client (until you add more backends and change the default in code).
- To be explicit, pass **`--client patsight`** on each command.
- Run **`patsight-cli clients`** to print the registered client names (JSON). If you only see `patsight`, that is the only backend available.

This design is intentional: one default client keeps short commands simple, while `--client` and YAML profiles keep multi-backend setups explicit.

### Authentication and token persistence

- **There is no interactive “logged-in shell”.** Each `patsight-cli` run is a **new process**. Nothing is stored in your terminal session after the command exits.
- **OPS tokens can expire** (policy is enforced by the server). The PatSight client **verifies** the token on each run; if it is invalid, it **refreshes** using account and password when those are available (environment, `.env`, or flags).
- **`patsight-cli login` is optional for daily use.** Commands such as `submit`, `status`, and `result` call **`login()` internally** anyway. Use `login` when you want to **check credentials** or **warm the token cache** without doing other work.
- **Where the token is remembered between runs:**
  - **`PATSIGHT_TOKEN`** in the environment or `.env` (CLI loads `.env` automatically).
  - **SQLite** at `PATSIGHT_CLI_CLIENT_DB` (default `~/.local/share/patsight-cli/tasks.db`), keyed by client instance name (`--name`, default `default`).

So you **do not** need to run `login` before every other command: configure account/password once (or rely on a token in `.env`), then run `submit` / `status` / `result` as needed. If the token expires and password is still configured, the next command refreshes it automatically.

### CLI examples

```bash
# List registered client types (see what --client can be)
patsight-cli clients

# Optional: verify credentials and cache token for later runs
patsight-cli login --client patsight \
  --account "$PATSIGHT_OPS_ACCOUNT" \
  --password "$PATSIGHT_OPS_PASSWORD"

# Same as --client patsight; omitted here because patsight is the default
patsight-cli submit --pdf-path /path/to/patent.pdf --job-type structureAndActivity

# Explicit client (equivalent when only patsight exists)
patsight-cli status --client patsight --job-id "<job_id>"
patsight-cli result --client patsight --job-id "<job_id>"

patsight-cli report --job-id "<job_id>" -o report.html
patsight-cli report --from-json saved_result.json -o report.html
```

---

## Python library usage

### Install

Use the same installation as above (`pip install ...`). The library is imported as `patsight_cli`.

### Basic example (PatSight)

```python
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())  # optional: mirrors CLI .env behaviour

from patsight_cli import PatSightClient

client = PatSightClient()
# Or pass credentials explicitly:
# client = PatSightClient(account="...", password="...")

info = client.submit_job(
    {"pdf_path": "/path/to/patent.pdf", "job_type": "structureAndActivity"}
)
status = client.query_status(info["job_id"])
result = client.fetch_result(info["job_id"])
```

`import patsight_cli` registers built-in clients (including `patsight`). If you only import submodules, ensure `import patsight_cli.clients` (or `import patsight_cli`) runs before `ClientRegistry.create("patsight", ...)`.

### Register a custom client

```python
from patsight_cli.base import RemoteJobClient
from patsight_cli.registry import ClientRegistry
from patsight_cli.models import JobResult, JobStatus

@ClientRegistry.register("acme")
class AcmeClient(RemoteJobClient):
    def login(self) -> None: ...
    def submit_job(self, payload): ...
    def query_status(self, job_id: str, job_type: str = "") -> JobStatus: ...
    def fetch_result(self, job_id: str, **kwargs) -> JobResult: ...
```

Import your module before calling `ClientRegistry.create("acme", ...)`.

---

## License

MIT License. Copyright (c) 2026 Xtalpi — see [`LICENSE`](LICENSE) for the full text.
