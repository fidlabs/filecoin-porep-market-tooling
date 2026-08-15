#!/usr/bin/env bash
# Generate this repo's .env for the Curio / FEVM stack created by ../FCSS-devnet,
# and ensure a local Python venv with requirements.txt installed.
#
# Reads deployment + Curio contract artifacts from FCSS-devnet (no Lotus wallet
# creation, no on-chain registration). Prefer SP_* from an existing local .env,
# else from FCSS-devnet's tooling .env if present.
#
# Prerequisites: jq, python3; FCSS-devnet with Curio contracts bootstrapped and
# porep-market deployed (`just porep-market deploy` / `just porep-market up`).
#
# Usage (from repo root or anywhere):
#   ./tools/setup-fcss-devnet-env.sh
#   ./tools/setup-fcss-devnet-env.sh --fcss-dir /path/to/FCSS-devnet --force
#
# Compatible with macOS /bin/bash 3.2.

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

FCSS_DIR="${FCSS_DEVNET_DIR:-${REPO_ROOT}/../FCSS-devnet}"
OUT_FILE="${ENV_FILE:-${REPO_ROOT}/.env}"
VENV_DIR="${VENV_DIR:-${REPO_ROOT}/.venv}"
REQUIREMENTS_FILE="${REPO_ROOT}/requirements.txt"
FORCE=false
SKIP_VENV="${SKIP_VENV:-0}"
RPC_URL="${RPC_URL:-http://127.0.0.1:2234/rpc/v1}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Write a porep-market-tooling .env that targets an FCSS-devnet Curio stack,
create .venv if needed, and pip-install requirements.txt.

Options:
  --fcss-dir DIR   Path to FCSS-devnet (default: ../FCSS-devnet or FCSS_DEVNET_DIR)
  --out FILE       Output .env path (default: <repo>/.env or ENV_FILE)
  --rpc-url URL    Lotus FEVM RPC (default: http://127.0.0.1:2234/rpc/v1 or RPC_URL)
  --force          Overwrite existing output without backup
  --skip-venv      Skip creating/updating the Python venv
  -h, --help       Show this help

Environment:
  FCSS_DEVNET_DIR  Same as --fcss-dir
  ENV_FILE         Same as --out
  RPC_URL          Same as --rpc-url
  VENV_DIR         Python venv path (default: <repo>/.venv)
  SKIP_VENV=1      Same as --skip-venv
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '==> %s\n' "$*" >&2
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

require_file() {
  [[ -f "$1" ]] || die "missing required file: $1"
}

is_addr() {
  [[ "$1" =~ ^0x[0-9a-fA-F]{40}$ ]]
}

is_key() {
  [[ "$1" =~ ^0x[0-9a-fA-F]{64}$ ]]
}

# Usage: env_get FILE KEY
env_get() {
  local file="$1" key="$2" line val
  [[ -f "$file" ]] || return 1
  line="$(grep -E "^${key}=" "$file" 2>/dev/null | tail -n1 || true)"
  [[ -n "$line" ]] || return 1
  val="${line#*=}"
  if [[ "$val" =~ ^\".*\"$ ]]; then
    val="${val:1:${#val}-2}"
  elif [[ "$val" =~ ^\'.*\'$ ]]; then
    val="${val:1:${#val}-2}"
  fi
  val="${val%$'\r'}"
  val="${val#"${val%%[![:space:]]*}"}"
  val="${val%"${val##*[![:space:]]}"}"
  printf '%s\n' "$val"
}

# Resolve ACTIVE record → latest.json (same layout as FCSS-devnet deployment.sh).
active_latest_json() {
  local deployments_dir="$1"
  local active_file="${deployments_dir}/ACTIVE"
  local records_dir="${deployments_dir}/records"
  local latest="${deployments_dir}/latest.json"
  local name record

  if [[ -f "$active_file" ]]; then
    name="$(tr -d '[:space:]' <"$active_file")"
    if [[ -n "$name" ]]; then
      record="${records_dir}/${name}/latest.json"
      if [[ -f "$record" ]]; then
        printf '%s\n' "$record"
        return 0
      fi
    fi
  fi
  if [[ -f "$latest" ]]; then
    printf '%s\n' "$latest"
    return 0
  fi
  return 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fcss-dir)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      FCSS_DIR="$2"
      shift 2
      ;;
    --out)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      OUT_FILE="$2"
      shift 2
      ;;
    --rpc-url)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      RPC_URL="$2"
      shift 2
      ;;
    --force)
      FORCE=true
      shift
      ;;
    --skip-venv)
      SKIP_VENV=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'error: unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

require_cmd jq
require_cmd python3
require_file "$REQUIREMENTS_FILE"

FCSS_DIR="$(cd "$FCSS_DIR" && pwd)" || die "FCSS-devnet dir not found: ${FCSS_DIR}"
[[ -d "$FCSS_DIR" ]] || die "FCSS-devnet dir not found: ${FCSS_DIR}"

POREP_MARKET_DIR="${POREP_MARKET_DIR:-${FCSS_DIR}/extern/porep-market}"
CURIO_DIR="${CURIO_DIR:-${FCSS_DIR}/extern/curio}"
CONTRACTS_DIR="${CURIO_CONTRACTS_DIR:-${CURIO_DIR}/docker/data/contracts}"
CURIO_CLI="${FCSS_DIR}/scripts/curio/cli.sh"
FCSS_TOOLING_ENV="${FCSS_DIR}/extern/filecoin-porep-market-tooling/.env"

DEPLOYMENTS_DIR="${POREP_MARKET_DIR}/deployments/devnet"
DEPLOYMENT_JSON="$(active_latest_json "$DEPLOYMENTS_DIR")" \
  || die "no porep-market deployment at ${DEPLOYMENTS_DIR} (run: cd FCSS-devnet && just porep-market deploy)"

DEPLOYER_KEY_FILE="${CONTRACTS_DIR}/deployer.private-key"
CONTRACT_ADDRESSES_JSON="${CONTRACTS_DIR}/contract_addresses.json"
DEVNET_INFO_JSON="${CONTRACTS_DIR}/devnet-info.json"

require_file "$DEPLOYMENT_JSON"
require_file "$DEPLOYER_KEY_FILE"
require_file "$CONTRACT_ADDRESSES_JSON"
require_file "$DEVNET_INFO_JSON"
require_file "$CURIO_CLI"

jq_addr() {
  local expr="$1"
  jq -r "$expr // empty" "$DEPLOYMENT_JSON" | tr -d '[:space:]'
}

POREP_MARKET="$(jq_addr '.contracts.PoRepMarket.proxy')"
POREP_MARKET_VIEW_HELPER="$(jq_addr '.contracts.PoRepMarketViewHelper.address // .contracts.PoRepMarketViewHelper.proxy')"
FILECOIN_PAY="$(jq_addr '.externalDependencies.FilecoinPay // .contracts.FilecoinPay.proxy // .contracts.FilecoinPay.address')"
USDC_TOKEN="$(jq -r '.contracts.usdfc // empty' "$CONTRACT_ADDRESSES_JSON" | tr -d '[:space:]')"
ADMIN_PRIVATE_KEY="$(tr -d '[:space:]' <"$DEPLOYER_KEY_FILE")"
CLIENT_PRIVATE_KEY="$(jq -r '.info.users[0].private_key_hex // empty' "$DEVNET_INFO_JSON" | tr -d '[:space:]')"
CLIENT_ADDRESS="$(jq -r '.info.users[0].evm_addr // empty' "$DEVNET_INFO_JSON" | tr -d '[:space:]')"

is_addr "$POREP_MARKET" || die "invalid/missing PoRepMarket.proxy in ${DEPLOYMENT_JSON}"
is_addr "$POREP_MARKET_VIEW_HELPER" || die "invalid/missing PoRepMarketViewHelper in ${DEPLOYMENT_JSON}"
is_addr "$FILECOIN_PAY" || die "invalid/missing FilecoinPay in ${DEPLOYMENT_JSON}"
is_addr "$USDC_TOKEN" || die "invalid/missing contracts.usdfc in ${CONTRACT_ADDRESSES_JSON}"
is_key "$ADMIN_PRIVATE_KEY" || die "invalid deployer private key in ${DEPLOYER_KEY_FILE}"
is_key "$CLIENT_PRIVATE_KEY" || die "USER_1 private key missing from ${DEVNET_INFO_JSON}"
is_addr "$CLIENT_ADDRESS" || die "USER_1 evm_addr missing from ${DEVNET_INFO_JSON}"

# SP org: prefer existing local .env, then FCSS tooling .env.
SP_PRIVATE_KEY=""
SP_ORGANIZATION=""
CURIO_MINER_ID=""
SP_SOURCE=""

if [[ -f "$OUT_FILE" ]]; then
  SP_PRIVATE_KEY="$(env_get "$OUT_FILE" SP_PRIVATE_KEY || true)"
  SP_ORGANIZATION="$(env_get "$OUT_FILE" SP_ORGANIZATION || true)"
  CURIO_MINER_ID="$(env_get "$OUT_FILE" CURIO_MINER_ID || true)"
  if is_key "${SP_PRIVATE_KEY:-}" && is_addr "${SP_ORGANIZATION:-}"; then
    SP_SOURCE="existing ${OUT_FILE}"
  else
    SP_PRIVATE_KEY=""
    SP_ORGANIZATION=""
  fi
fi

if [[ -z "$SP_PRIVATE_KEY" && -f "$FCSS_TOOLING_ENV" ]]; then
  SP_PRIVATE_KEY="$(env_get "$FCSS_TOOLING_ENV" SP_PRIVATE_KEY || true)"
  SP_ORGANIZATION="$(env_get "$FCSS_TOOLING_ENV" SP_ORGANIZATION || true)"
  [[ -n "${CURIO_MINER_ID:-}" ]] || CURIO_MINER_ID="$(env_get "$FCSS_TOOLING_ENV" CURIO_MINER_ID || true)"
  if is_key "${SP_PRIVATE_KEY:-}" && is_addr "${SP_ORGANIZATION:-}"; then
    SP_SOURCE="FCSS tooling ${FCSS_TOOLING_ENV}"
  else
    SP_PRIVATE_KEY=""
    SP_ORGANIZATION=""
  fi
fi

ARIA2C_PATH=""
if command -v aria2c >/dev/null 2>&1; then
  ARIA2C_PATH="$(command -v aria2c)"
fi

if [[ -e "$OUT_FILE" && "$FORCE" != true ]]; then
  backup="${OUT_FILE}.bak.$(date +%Y%m%d%H%M%S)"
  cp -p "$OUT_FILE" "$backup"
  log "backed up existing .env to ${backup}"
fi

umask 077
cat >"$OUT_FILE" <<EOF
DEBUG=false

# Needed for sp onboard-data command, path for aria2c binary, leave empty to use PATH lookup
ARIA2C_PATH=${ARIA2C_PATH}

# Needed for sp claim-allocations curio command.
# Default: docker wrapper (Curio runs in container on FCSS-devnet).
CURIO_PATH=${CURIO_CLI}

# Needed for sp claim-allocations boost command, path for boostd binary, leave empty to use PATH lookup
BOOSTD_PATH=

# Enables dry-run mode, which only simulates transactions without broadcasting them to the network
DRY_RUN=false

# SPRegistry database connection string used for admin operations
SP_REGISTRY_DATABASE_URL=

# Local Curio Devnet Lotus RPC (FCSS-devnet host port; chain id 31415926)
RPC_URL=${RPC_URL}

# Funded USER_1 from curio/docker/data/contracts/devnet-info.json
CLIENT_PRIVATE_KEY=${CLIENT_PRIVATE_KEY}
CLIENT_LOTUS_WALLET=
CLIENT_LOTUS_TOKEN=
CLIENT_ADDRESS=${CLIENT_ADDRESS}

# Deployer from curio/docker/data/contracts/deployer.private-key
ADMIN_PRIVATE_KEY=${ADMIN_PRIVATE_KEY}
ADMIN_LOTUS_WALLET=
ADMIN_LOTUS_TOKEN=

# SP organization (from ${SP_SOURCE:-unset — run: cd FCSS-devnet && just porep-market up})
SP_PRIVATE_KEY=${SP_PRIVATE_KEY}
SP_LOTUS_WALLET=
SP_LOTUS_TOKEN=
SP_ORGANIZATION=${SP_ORGANIZATION}

# From porep-market/deployments/devnet (ACTIVE/latest.json)
POREP_MARKET=${POREP_MARKET}
POREP_MARKET_VIEW_HELPER=${POREP_MARKET_VIEW_HELPER}
FILECOIN_PAY=${FILECOIN_PAY}

# USDFC from curio/docker/data/contracts/contract_addresses.json
USDC_TOKEN=${USDC_TOKEN}
EOF

if [[ -n "${CURIO_MINER_ID:-}" ]]; then
  printf 'CURIO_MINER_ID=%s\n' "$CURIO_MINER_ID" >>"$OUT_FILE"
fi

chmod 600 "$OUT_FILE"

log "wrote ${OUT_FILE}"
log "  FCSS_DIR=${FCSS_DIR}"
log "  deployment=${DEPLOYMENT_JSON}"
log "  RPC_URL=${RPC_URL}"
log "  POREP_MARKET=${POREP_MARKET}"
log "  POREP_MARKET_VIEW_HELPER=${POREP_MARKET_VIEW_HELPER}"
log "  FILECOIN_PAY=${FILECOIN_PAY}"
log "  USDC_TOKEN=${USDC_TOKEN}"
log "  CLIENT_ADDRESS=${CLIENT_ADDRESS}"
if [[ -n "$SP_ORGANIZATION" ]]; then
  log "  SP_ORGANIZATION=${SP_ORGANIZATION} (${SP_SOURCE})"
else
  log "  SP_ORGANIZATION unset — run: cd ${FCSS_DIR} && just porep-market up"
fi
[[ -n "${CURIO_MINER_ID:-}" ]] && log "  CURIO_MINER_ID=${CURIO_MINER_ID}"
log "  CURIO_PATH=${CURIO_CLI}"

if [[ "$SKIP_VENV" == "1" || "$SKIP_VENV" == true ]]; then
  log "SKIP_VENV=1 — not creating/updating Python venv"
else
  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    log "creating Python venv at ${VENV_DIR}"
    python3 -m venv "$VENV_DIR"
  else
    log "Python venv already present at ${VENV_DIR}"
  fi
  require_file "${VENV_DIR}/bin/pip"
  log "pip install -r ${REQUIREMENTS_FILE#"$REPO_ROOT"/}"
  "${VENV_DIR}/bin/pip" install -r "$REQUIREMENTS_FILE"
  log "venv ready — activate with: source ${VENV_DIR}/bin/activate"
fi
