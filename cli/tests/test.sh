#!/bin/bash

# Simple tool that runs all CLI get commands that requires no user input.
# Expects process exit code and nothing more.
# This is not designed to be a comprehensive test suite.
# Hardcoded private keys and addresses are used for testing purposes only and should never be used anywhere else.

set -euo pipefail

# shellcheck disable=SC2155
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly CLI_PATH="${SCRIPT_DIR}/../../porep_tooling_cli.py"

# export all env vars from .env.test
set -a
source "${SCRIPT_DIR}/.env.test"
export DEBUG=true
set +a

(
  # misc tests
  python3 "${CLI_PATH}"             >/dev/null &&
  python3 "${CLI_PATH}" info --help >/dev/null &&

  python3 "${CLI_PATH}" client --address "0x5CF0365dA2F0a83c70Dfb4b96067c0e3cd2Ea951" info                          >/dev/null &&
  python3 "${CLI_PATH}" admin --private-key "b73163861add8c8280f62958432131b7a5e69a9276a3cfa26fcaa92ff356fadc" info >/dev/null &&
  python3 "${CLI_PATH}" sp --organization "0x5CF0365dA2F0a83c70Dfb4b96067c0e3cd2Ea951" info                         >/dev/null &&
  python3 "${CLI_PATH}" admin get-deals --help                                                                      >/dev/null &&

  # admin tests
  python3 "${CLI_PATH}" admin get-deals proposed         >/dev/null   &&
  python3 "${CLI_PATH}" admin get-devnet-sps             >/dev/null   &&
  python3 "${CLI_PATH}" admin get-registered-sps         >/dev/null   &&
  python3 "${CLI_PATH}" admin get-db-sps --help          >/dev/null   &&
  python3 "${CLI_PATH}" admin register-db-sps --help     >/dev/null   &&
  python3 "${CLI_PATH}" admin register-devnet-sps --help >/dev/null   &&
  ! (python3 "${CLI_PATH}" admin get-deal    4242 >/dev/null 2>&1)    &&

  # client tests
  python3 "${CLI_PATH}" client get-deals rejected                >/dev/null &&
  python3 "${CLI_PATH}" client get-filecoinpay-account           >/dev/null &&
  python3 "${CLI_PATH}" client init-accepted-deals --help        >/dev/null &&
  python3 "${CLI_PATH}" client deposit-for-deals --help          >/dev/null &&
  python3 "${CLI_PATH}" client propose-deal-from-manifest --help >/dev/null &&
  python3 "${CLI_PATH}" client deposit-amount --help             >/dev/null &&
  ! (python3 "${CLI_PATH}" client get-deal    4242 >/dev/null 2>&1)         &&

  # sp tests
  python3 "${CLI_PATH}" sp get-deals accepted           >/dev/null &&
  python3 "${CLI_PATH}" sp accept-deal --help           >/dev/null &&
  python3 "${CLI_PATH}" sp reject-deal --help           >/dev/null &&
  python3 "${CLI_PATH}" sp manage-proposed-deals --help >/dev/null &&
  ! (python3 "${CLI_PATH}" sp get-deal    4242 >/dev/null 2>&1)    &&
  ! (python3 "${CLI_PATH}" sp accept-deal 4242 >/dev/null 2>&1)    &&
  ! (python3 "${CLI_PATH}" sp reject-deal 4242 >/dev/null 2>&1)    &&

  # test keys

  # not matching keys but info command should work
  (CLIENT_PRIVATE_KEY="75d5bb290fb82d5b86a0a73b30e8e6dfb74d694f565a13f163d87d4370067729" \
    python3 "${CLI_PATH}" client --address "0x999999cf1046e68e36E1aA2E0E07105eDDD1f08E" info >/dev/null) &&

  python3 "${CLI_PATH}" client --address "0x999999cf1046e68e36E1aA2E0E07105eDDD1f08E" --private-key "75d5bb290fb82d5b86a0a73b30e8e6dfb74d694f565a13f163d87d4370067729" info >/dev/null &&

  # not matching keys but get commands should work
  (CLIENT_PRIVATE_KEY="75d5bb290fb82d5b86a0a73b30e8e6dfb74d694f565a13f163d87d4370067729" \
    python3 "${CLI_PATH}" client --address "0x999999cf1046e68e36E1aA2E0E07105eDDD1f08E" get-deals >/dev/null) &&  # not matching with env

  python3 "${CLI_PATH}" client --address "0x999999cf1046e68e36E1aA2E0E07105eDDD1f08E" --private-key "75d5bb290fb82d5b86a0a73b30e8e6dfb74d694f565a13f163d87d4370067729" get-deals >/dev/null &&

  # matching keys
  python3 "${CLI_PATH}" client --address "0x4300EbD613b8E965A81B54aCdF1fA843758420DA" --private-key "75d5bb290fb82d5b86a0a73b30e8e6dfb74d694f565a13f163d87d4370067729" info --test-keys >/dev/null &&
  python3 "${CLI_PATH}" client --private-key "75d5bb290fb82d5b86a0a73b30e8e6dfb74d694f565a13f163d87d4370067729" info --test-keys >/dev/null &&

  (CLIENT_PRIVATE_KEY="75d5bb290fb82d5b86a0a73b30e8e6dfb74d694f565a13f163d87d4370067729" \
    python3 "${CLI_PATH}" client --address "0x4300EbD613b8E965A81B54aCdF1fA843758420DA" info --test-keys >/dev/null) &&

  (CLIENT_PRIVATE_KEY="75d5bb290fb82d5b86a0a73b30e8e6dfb74d694f565a13f163d87d4370067729" \
    python3 "${CLI_PATH}" client info --test-keys >/dev/null) &&

  # fail when no matching keys
  ! (CLIENT_PRIVATE_KEY="75d5bb290fb82d5b86a0a73b30e8e6dfb74d694f565a13f163d87d4370067729" \
    python3 "${CLI_PATH}" client --address "0x999999cf1046e68e36E1aA2E0E07105eDDD1f08E" info --test-keys >/dev/null 2>&1) &&

  ! (python3 "${CLI_PATH}" client --address "0x999999cf1046e68e36E1aA2E0E07105eDDD1f08E" --private-key "75d5bb290fb82d5b86a0a73b30e8e6dfb74d694f565a13f163d87d4370067729" info --test-keys >/dev/null 2>&1) &&

  # dont fail when no keys provided for get commands
  CLIENT_PRIVATE_KEY="" \
    python3 "${CLI_PATH}" client --address "0x999999cf1046e68e36E1aA2E0E07105eDDD1f08E" get-deals >/dev/null &&

  CLIENT_PRIVATE_KEY="" \
    python3 "${CLI_PATH}" client --address "0x999999cf1046e68e36E1aA2E0E07105eDDD1f08E" get-deals >/dev/null &&

  ADMIN_PRIVATE_KEY="" \
    python3 "${CLI_PATH}" admin get-deals >/dev/null &&

  echo "All tests passed"
) || {
  echo "Error: CLI test failed: expected different exit code" >&2
  exit 1
}
