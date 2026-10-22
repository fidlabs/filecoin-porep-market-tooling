#!/bin/bash

readonly PROVIDER_ID=""
readonly ONBOARD_DATA_OUTPUT_DIR=""
readonly CLAIM_ALLOCATIONS_SOFTWARE="curio"
# readonly CLAIM_ALLOCATIONS_SOFTWARE="boost"

# Downloader for the data: "auto" (aria2 when the manifest host serves the pieces for free, else lpr), "aria2" (free
# HTTP piece server) or "lpr" (retrieval through a large-paid-retrievals sp-proxy, e.g. FCSS repair from a healthy SP;
# requires retrieval-client).
readonly ONBOARD_DATA_DOWNLOADER="auto"
# readonly ONBOARD_DATA_DOWNLOADER="aria2"
# readonly ONBOARD_DATA_DOWNLOADER="lpr"

# Port of the piece server at the manifest URL host. Not used with lpr, when the healthy SP is found automatically.
readonly ONBOARD_DATA_PORT="7777"

# For paid lpr downloads: file with the private key of the SP payee address (the client funds its FileCoinPay account
# with `client pay-repair-retrieval`). Leave empty to use SP_PAYEE_KEY_FILE or the FILPAY_PRIVATE_KEY env var.
readonly PAYEE_KEY_FILE=""


readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly CLI_PATH="${SCRIPT_DIR}/../porep_tooling_cli.py"

set -euo pipefail

onboard_data_args=(--output-dir "${ONBOARD_DATA_OUTPUT_DIR}" --downloader "${ONBOARD_DATA_DOWNLOADER}" --port "${ONBOARD_DATA_PORT}")
if [[ -n "${PAYEE_KEY_FILE}" ]]; then
    onboard_data_args+=(--payee-key-file "${PAYEE_KEY_FILE}")
fi

mapfile -t completed_deals < <(python3 "${CLI_PATH}" sp get-deals --provider-id "$PROVIDER_ID" completed | jq -r '.[].deal_id')
echo "Completed deals: ${completed_deals[*]}"

for deal_id in "${completed_deals[@]}"; do
    echo "Processing deal id ${deal_id}..."

    echo "Downloading data for deal id ${deal_id} using ${ONBOARD_DATA_DOWNLOADER}..."
    # e.g. a repair still waiting for client funding: skip the deal; the next run retries it
    if ! python3 "${CLI_PATH}" sp onboard-data "${deal_id}" "${onboard_data_args[@]}" < <(yes); then
        echo "Skipping deal id ${deal_id}: onboard-data failed (see above)"
        continue
    fi

    echo "Claiming allocations for deal id ${deal_id}..."
    python3 "${CLI_PATH}" sp claim-allocations "${CLAIM_ALLOCATIONS_SOFTWARE}" "${deal_id}" --cars-dir "${ONBOARD_DATA_OUTPUT_DIR}" < <(yes)
done
