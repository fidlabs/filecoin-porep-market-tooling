#!/bin/bash

readonly PROVIDER_ID=""
readonly ONBOARD_DATA_OUTPUT_DIR=""
readonly CLAIM_ALLOCATIONS_SOFTWARE="curio"
# readonly CLAIM_ALLOCATIONS_SOFTWARE="boost"


readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly CLI_PATH="${SCRIPT_DIR}/../porep_tooling_cli.py"

set -euo pipefail

mapfile -t completed_deals < <(python3 "${CLI_PATH}" sp get-deals --provider-id "$PROVIDER_ID" completed | jq -r '.[].deal_id')
echo "Completed deals: ${completed_deals[*]}"

for deal_id in "${completed_deals[@]}"; do
    echo "Processing deal id ${deal_id}..."

    echo "Downloading data for deal id ${deal_id}..."
    python3 "${CLI_PATH}" sp onboard-data "${deal_id}" --output-dir "${ONBOARD_DATA_OUTPUT_DIR}" < <(yes)

    echo "Claiming allocations for deal id ${deal_id}..."
    python3 "${CLI_PATH}" sp claim-allocations "${CLAIM_ALLOCATIONS_SOFTWARE}" "${deal_id}" --cars-dir "${ONBOARD_DATA_OUTPUT_DIR}" < <(yes)
done
