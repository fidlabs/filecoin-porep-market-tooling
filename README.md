# Filecoin PoRep Market tooling CLI

[![cli/test.sh](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/test-sh.yml/badge.svg)](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/test-sh.yml)
[![Code linters](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/lint.yml/badge.svg)](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/lint.yml)
[![CodeQL](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/github-code-scanning/codeql)
[![Copilot code review](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/copilot-pull-request-reviewer/copilot-pull-request-reviewer/badge.svg)](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/copilot-pull-request-reviewer/copilot-pull-request-reviewer)

Python3 CLI tool for interacting with [Filecoin PoRep Market](https://github.com/fidlabs/porep-market) smart contracts
using [Click](https://click.palletsprojects.com/en/stable/#), [Web3](https://web3py.readthedocs.io/en/stable/) and [psycopg](https://www.psycopg.org/docs/). \
Developed for admins, clients, and SPs to **manage their market interactions** from command line.

## What is this tool?

This command-line tool lets **Storage Providers (SPs)** and **Clients** interact with the Filecoin PoRep Market on-chain.

- **Clients** can propose storage deals, set up payment rails, allocate DataCap, and fund ongoing storage fees.
- **Storage Providers** can review incoming deals, accept or reject them, download deal data, and claim allocations in Curio or Boost.

You do not need to be a CLI expert to use it. Each command prints what it is about to do and asks for confirmation before sending blockchain transactions (
see [Security considerations](#security-considerations)).

## Installation

**Use python >= 3.10**

```bash
python3 --version
python3 -m pip install -r requirements.txt
cp .env.mainnet .env
```

Clone this repo if you have not already:

```bash
git clone https://github.com/fidlabs/filecoin-porep-market-tooling
```

NOTE: this repo is still heavily developed and continuously improved so please make sure to do `git pull` from inside the folder with the code
to ensure you have the latest version of the code.

## Running the CLI

Make sure you have the required environment variables (see [Configuration](#configuration-env)). \
Run the script: `python3 ./porep_tooling_cli.py` and follow help prompts.

```bash
python3 ./porep_tooling_cli.py --help
python3 ./porep_tooling_cli.py sp --help
python3 ./porep_tooling_cli.py client --help
```

## Before you begin

### Everyone

- **Python 3.10+** installed
- A **Filecoin wallet** initialized on the network (you need **FIL** for gas)
- Access to a Filecoin RPC endpoint (configured in `.env` as `RPC_URL`)

### Storage Providers

- A **controller wallet** registered for your miner(s) — **do not use your miner owner wallet** (see [Storage Provider guide](#storage-provider-guide))
- [Curio](https://docs.curiostorage.org/) or [Boost](https://boost.filecoin.io/) installed for claiming allocations
- [aria2](https://aria2.github.io/) installed for downloading deal data (optional but very useful)
- Your organization registered in the PoRep Market SP Registry

### Clients

- A wallet with **USDC** (axlUSDC on mainnet) for storage payments
- A prepared **manifest URL** pointing to your dataset (from Singularity or similar)
- Enough **DataCap** to allocate to the SP

### Glossary

| Term            | Meaning                                                            |
|-----------------|--------------------------------------------------------------------|
| **Deal**        | A storage agreement between a client and an SP on the PoRep Market |
| **Manifest**    | A JSON file listing all data pieces (`.car` files) in a deal       |
| **DDO**         | Direct Data Onboarding — allocating DataCap directly to an SP      |
| **Allocation**  | A DataCap grant for a specific piece of data                       |
| **FileCoinPay** | On-chain payment rail for deal storage fees (USDC)                 |
| **Rail**        | A FileCoinPay payment channel tied to a specific deal              |
| **Validator**   | A per-deal smart contract that manages payments                    |

## How a deal progresses

Every deal moves through these states:

```
PROPOSED → ACCEPTED → COMPLETED → (SP onboards & gets paid)
    ↓
 REJECTED / TERMINATED
```

| State          | What it means                                                                                                                 | Who acts next                                                |
|----------------|-------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------|
| **PROPOSED**   | The data is prepared and the client has submitted a deal proposal with all required metadata and SLA requirements.            | **SP** accepts or rejects                                    |
| **ACCEPTED**   | The Storage Provider has accepted the deal. At this stage, the deal is waiting for the client to make the DataCap allocation. | **Client** initializes payment and makes DataCap allocations |
| **COMPLETED**  | The client has made the DataCap allocation. The deal is now ready to be onboarded by the Storage Provider.                    | **SP** downloads data and claims allocations                 |
| **REJECTED**   | SP declined the deal                                                                                                          | No further action                                            |
| **TERMINATED** | Deal was terminated (admin action)                                                                                            | No further action                                            |

Deals in `COMPLETED` state are ready for onboarding. The deal includes a `manifest_location` entry: this tells you where the Singularity manifest is. \
All the `.car` files referenced are then available for pulling from the standard location of `<manifest_ip>:7777/piece/<CID>`.

**Client steps (ACCEPTED state):**

1. Deploy validator and set up FileCoinPay (`init-accepted-deals`)
2. Make DataCap allocations in batches (`make-allocations`) — this also marks the deal COMPLETED
3. Keep FileCoinPay funded for ongoing storage fees (`deposit-for-deals`)

**SP steps (COMPLETED state):**

1. Download `.car` files (`onboard-data`)
2. Claim allocations in Curio or Boost (`claim-allocations`)

## Storage Provider guide

### One-time setup

1. **IMPORTANT**: interaction with the chain requires the private key for the message sender,
   so for security do not use your miner wallet for sending commands to the Peer-to-pool PoRep Market. \
   Instead you will need to create a miner controller wallet. If you already have one and want to reuse it, that's fine. \
   However for most efficiency, we recommend you create a new wallet, and register it as a controller wallet for all the miners you will be using in P2PP. \
   The Market then uses controller status to verify that the command sender is authorised to send commands on behalf of your miner. \
   Follow the steps here:
   [https://lotus.filecoin.io/storage-providers/operate/addresses/#control-addresses](https://lotus.filecoin.io/storage-providers/operate/addresses/#control-addresses)

2. Export the private key of your newly created wallet. The value you store in `SP_PRIVATE_KEY`
   must be this exported private key in 32-byte hex format with a `0x` prefix — **not** the wallet
   address you pass to `lotus wallet export`:
   ```bash
   lotus wallet export <your-wallet-address-from-above> | xxd -r -p | jq -r '.PrivateKey' | base64 -d | xxd -p -c 32 | sed 's/^/0x/'
   ```

3. Go into your local copy of the tool and install dependencies:
   ```bash
   python3 -m pip install -r requirements.txt
   ```

4. Then copy the config file:
   ```bash
   cp .env.mainnet .env
   ```

5. Edit the `.env` file:
    - put in the secret key of the controller wallet from step 2:
      ```bash
      # Private key used in SP operations
      # Set this if you want to interact with the system as a storage provider (organization)
      # This address needs to be the controlling address of provider_id you want to manage in the SPRegistry contract
      # See https://lotus.filecoin.io/storage-providers/operate/addresses/#control-addresses
      # 32-byte raw private key (hex, 0x-prefixed)

      SP_PRIVATE_KEY=<your miner controller wallet from step 2>
      ```

    - add your SP organization address:
      ```bash
      # Organization address to manage SPs from
      # You must have the SP_PRIVATE_KEY of an organization controlling address set to perform SP management operations

      SP_ORGANIZATION=<your organization address>
      ```

6. Ensure the file permissions on `.env` prevent the reading of this value by any user other than the one that runs the tooling.
   Assuming you are already logged in as the correct user, that would be:
   ```bash
   chmod 600 .env
   ```

7. Optional but very useful for downloading the deals: install aria2:
    - on Mac `brew install aria2`
    - on Debian/Ubuntu: `sudo apt install aria2`
    - on Arch: `sudo pacman -S aria2`

   If aria2 is installed but not in your PATH, set `ARIA2C_PATH` in `.env`.
   Similarly, set `CURIO_PATH` or `BOOSTD_PATH` if Curio or Boost binaries are not in PATH.

8. Verify your setup:
   ```bash
   python3 ./porep_tooling_cli.py sp info --confirm-info
   python3 ./porep_tooling_cli.py sp is-authorized <YOUR_PROVIDER_ID>
   ```

### Step 1: Find deals allocated to you

```bash
python3 ./porep_tooling_cli.py sp get-deals
```

Filter by state:

```bash
python3 ./porep_tooling_cli.py sp get-deals proposed
python3 ./porep_tooling_cli.py sp get-deals accepted
python3 ./porep_tooling_cli.py sp get-deals completed
```

Filter by a specific miner/provider ID:

```bash
python3 ./porep_tooling_cli.py sp get-deals proposed --provider-id 12345
```

Inspect a single deal:

```bash
python3 ./porep_tooling_cli.py sp get-deal <DEAL_ID>
python3 ./porep_tooling_cli.py sp get-deal-manifest <DEAL_ID>
python3 ./porep_tooling_cli.py sp get-deal-rail <DEAL_ID>
```

### Step 2: Accept or reject proposed deals

Deals in `PROPOSED` state need to be accepted. Assuming you are happy to accept the deal on the terms offered, run:

```bash
python3 ./porep_tooling_cli.py sp accept-deal <dealID you want to accept>
```

then check back a few minutes later.

Reject a deal:

```bash
python3 ./porep_tooling_cli.py sp reject-deal <DEAL_ID>
```

Review all proposed deals interactively (accept / reject / skip each one):

```bash
python3 ./porep_tooling_cli.py sp manage-proposed-deals
```

Or auto-accept/reject all:

```bash
python3 ./porep_tooling_cli.py sp manage-proposed-deals accept
python3 ./porep_tooling_cli.py sp manage-proposed-deals reject
```

After accepting, wait for the client to complete their steps (see [Client guide](#client-guide)). Check back with:

```bash
python3 ./porep_tooling_cli.py sp get-deals completed
```

### Step 3: Download deal data

To download the deal that is allocated to you and in `COMPLETED` state run:

```bash
python3 ./porep_tooling_cli.py sp get-deals completed
python3 ./porep_tooling_cli.py sp onboard-data <DEAL ID> --output-dir <your dir>
```

Override download host/port if needed:

```bash
python3 ./porep_tooling_cli.py sp onboard-data <DEAL_ID> --output-dir <your dir> --host http://1.2.3.4 --port 7777
```

Additional aria2 options can be passed directly after the command (see `aria2c --help`).

### Step 4: Claim allocations

Get the allocation IDs:

```bash
python3 ./porep_tooling_cli.py sp get-allocations <DEAL ID>
```

Show only unclaimed allocations:

```bash
python3 ./porep_tooling_cli.py sp get-allocations <DEAL_ID> --not-claimed
```

Check which allocations have already been claimed:

```bash
python3 ./porep_tooling_cli.py sp get-claims <DEAL_ID>
```

And claim deals with Curio:

```bash
python3 ./porep_tooling_cli.py sp claim-allocations curio <DEAL ID>
```

Or with Boost (requires the directory containing downloaded `.car` files):

```bash
python3 ./porep_tooling_cli.py sp claim-allocations boost <DEAL_ID> --cars-dir <your dir>
```

### Step 5: Manage payments

Check your FileCoinPay balance:

```bash
python3 ./porep_tooling_cli.py sp get-filecoinpay-account
```

Withdraw USDC earnings:

```bash
python3 ./porep_tooling_cli.py sp withdraw-from-filecoinpay <TO_ADDRESS> <AMOUNT>
# Example: withdraw 100.5 USDC
python3 ./porep_tooling_cli.py sp withdraw-from-filecoinpay 0xYourWallet 100.5
```

### Other useful SP commands

Check your SP registry info:

```bash
python3 ./porep_tooling_cli.py sp get-registered-info
python3 ./porep_tooling_cli.py sp get-registered-info <PROVIDER_ID>
```

Wait for pending transactions to confirm:

```bash
python3 ./porep_tooling_cli.py sp wait
```

### Automating multiple deals

For batch processing completed deals, use the included script. Edit `PROVIDER_ID`, `ONBOARD_DATA_OUTPUT_DIR`, and `CLAIM_ALLOCATIONS_SOFTWARE` in the script
first:

```bash
./tools/sp-pipeline.sh
```

### Full SP command list

```bash
python3 ./porep_tooling_cli.py sp --help
```

## Client guide

### One-time setup

1. Install dependencies and copy config (same as [Installation](#installation)):
   ```bash
   python3 -m pip install -r requirements.txt
   cp .env.mainnet .env
   ```

2. Edit `.env`:
   ```bash
   # Private key used in client operations
   # Set this if you want to interact with the system as a client
   # This is the address that will be charged for deal payments
   # 32-byte raw private key (hex, 0x-prefixed)
   CLIENT_PRIVATE_KEY=0x...

   # Client address to use in client read-only operations
   # Must match the address derived from CLIENT_PRIVATE_KEY for blockchain transactions
   CLIENT_ADDRESS=0x...
   ```

3. Ensure the file permissions on `.env` prevent the reading of this value by any user other than the one that runs the tooling:
   ```bash
   chmod 600 .env
   ```

4. Verify your setup:
   ```bash
   python3 ./porep_tooling_cli.py client info --confirm-info
   python3 ./porep_tooling_cli.py client info --test-keys
   ```

You need:

- **FIL** in your wallet for gas fees
- **USDC** (axlUSDC) for storage payments via FileCoinPay
- Enough **DataCap** to allocate to the SP

### Step 1: Propose a deal

Propose a deal from a manifest URL with your desired SLA terms:

```bash
python3 ./porep_tooling_cli.py client propose-deal-from-manifest <MANIFEST_URL> \
  --retrievability-bps 7550 \
  --bandwidth-mbps 100 \
  --price-per-sector-per-month 2000000 \
  --duration-months 12 \
  --latency-ms 500 \
  --indexing-pct 0
```

| Parameter                      | Meaning                                                                      | Example              |
|--------------------------------|------------------------------------------------------------------------------|----------------------|
| `--retrievability-bps`         | Retrievability SLA in basis points (7550 = 75.50%). Use `0` for "don't care" | `7550`               |
| `--bandwidth-mbps`             | Bandwidth guarantee in Mbps. Capped at ~64 Gbps.                             | `100`                |
| `--price-per-sector-per-month` | Monthly price per 32 GiB sector in USDC smallest units (wei-equivalent)      | `2000000` (= 2 USDC) |
| `--duration-months`            | Deal length in months (minimum 6)                                            | `12`                 |
| `--latency-ms`                 | Latency guarantee in milliseconds                                            | `500`                |
| `--indexing-pct`               | IPNI indexing guarantee (0–100). Use `0` for "don't care"                    | `0`                  |

The tool will show you the deal size, estimated monthly cost, and total cost before asking for confirmation.

### Step 2: Wait for SP acceptance

Check your deals:

```bash
python3 ./porep_tooling_cli.py client get-deals
python3 ./porep_tooling_cli.py client get-deals proposed
python3 ./porep_tooling_cli.py client get-deals accepted
```

Once the SP accepts, the deal moves to **ACCEPTED**.

### Step 3: Initialize accepted deals

This deploys a per-deal validator, deposits USDC to FileCoinPay, and sets up the payment rail:

```bash
# Initialize all accepted deals
python3 ./porep_tooling_cli.py client init-accepted-deals

# Or initialize a specific deal
python3 ./porep_tooling_cli.py client init-accepted-deals <DEAL_ID>
```

This step requires enough USDC in your wallet for the first month's deposit.

### Step 4: Make DataCap allocations

Allocate DataCap to the SP in batches (up to 500 pieces per batch):

```bash
python3 ./porep_tooling_cli.py client make-allocations <DEAL_ID>
```

Options:

- `--print-only` — preview allocation parameters without sending transactions
- `--exclude-dag` — skip the manifest DAG piece (default is to include it)
- `--local-manifest /path/to/manifest.json` — use a local manifest instead of fetching from the deal

This command automatically marks the deal as **COMPLETED** after all pieces are allocated.

If you need to complete a deal manually (e.g. allocations were made outside this tool):

```bash
python3 ./porep_tooling_cli.py client complete-deal <DEAL_ID>
```

### Step 5: Keep FileCoinPay funded

Deposit USDC to cover ongoing storage fees:

```bash
# Deposit for all completed deals (1 month of coverage)
python3 ./porep_tooling_cli.py client deposit-for-deals

# Deposit for a specific deal, covering 3 months
python3 ./porep_tooling_cli.py client deposit-for-deals <DEAL_ID> --months 3

# Deposit a specific amount
python3 ./porep_tooling_cli.py client deposit-amount 50.0
```

Check your FileCoinPay balance:

```bash
python3 ./porep_tooling_cli.py client get-filecoinpay-account
```

### Monitoring your deals

```bash
python3 ./porep_tooling_cli.py client get-deal <DEAL_ID>
python3 ./porep_tooling_cli.py client get-deal-manifest <DEAL_ID>
python3 ./porep_tooling_cli.py client get-deal-rail <DEAL_ID>
```

Wait for pending transactions to confirm:

```bash
python3 ./porep_tooling_cli.py client wait
```

### Full client command list

```bash
python3 ./porep_tooling_cli.py client --help
```

## Command reference

### Storage Provider commands

| Command                                      | What it does                                  | Needs private key? |
|----------------------------------------------|-----------------------------------------------|--------------------|
| `sp get-deals [STATE]`                       | List your deals, optionally filtered by state | No                 |
| `sp get-deals [STATE] --provider-id <ID>`    | List deals for a specific provider ID         | No                 |
| `sp get-deal <ID>`                           | Get details for one deal                      | No                 |
| `sp get-deal-manifest <ID>`                  | Download and print the deal manifest          | No                 |
| `sp get-deal-rail <ID>`                      | Show FileCoinPay rail info for a deal         | No                 |
| `sp accept-deal <ID>`                        | Accept a proposed deal                        | Yes                |
| `sp reject-deal <ID>`                        | Reject a proposed deal                        | Yes                |
| `sp manage-proposed-deals [accept\|reject]`  | Interactively review all proposed deals       | Yes                |
| `sp onboard-data <ID> --output-dir <DIR>`    | Download `.car` files for a completed deal    | No                 |
| `sp get-allocations <ID>`                    | List DataCap allocations for a deal           | No                 |
| `sp get-allocations <ID> --not-claimed`      | Show only unclaimed allocations               | No                 |
| `sp get-claims <ID>`                         | List claimed allocations for a deal           | No                 |
| `sp claim-allocations curio\|boost <ID>`     | Claim allocations in Curio or Boost           | No*                |
| `sp get-registered-info [PROVIDER_ID]`       | Show your SP registry info                    | No                 |
| `sp is-authorized <PROVIDER_ID>`             | Check if your key can manage a provider       | No                 |
| `sp get-filecoinpay-account`                 | Show FileCoinPay balances                     | No                 |
| `sp withdraw-from-filecoinpay <TO> <AMOUNT>` | Withdraw USDC earnings                        | Yes                |
| `sp info`                                    | Show current SP configuration                 | No                 |
| `sp wait`                                    | Wait for pending transactions to confirm      | No                 |

\* `claim-allocations` runs external tools (curio/boostd), not blockchain transactions.

### Client commands

| Command                                             | What it does                             | Needs private key? |
|-----------------------------------------------------|------------------------------------------|--------------------|
| `client propose-deal-from-manifest <URL> [options]` | Propose a new storage deal               | Yes                |
| `client get-deals [STATE]`                          | List your deals                          | No                 |
| `client get-deal <ID>`                              | Get details for one deal                 | No                 |
| `client get-deal-manifest <ID>`                     | Download and print the deal manifest     | No                 |
| `client get-deal-rail <ID>`                         | Show FileCoinPay rail info               | No                 |
| `client init-accepted-deals [ID]`                   | Set up validator, deposit, and rail      | Yes                |
| `client make-allocations <ID>`                      | Allocate DataCap and complete deal       | Yes                |
| `client complete-deal <ID>`                         | Manually mark deal as completed          | Yes                |
| `client deposit-for-deals [ID] [--months N]`        | Top up FileCoinPay for deals             | Yes                |
| `client deposit-amount <AMOUNT>`                    | Deposit USDC to FileCoinPay              | Yes                |
| `client get-filecoinpay-account`                    | Show FileCoinPay balance                 | No                 |
| `client info`                                       | Show current client configuration        | No                 |
| `client wait`                                       | Wait for pending transactions to confirm | No                 |

### Utility commands

| Command             | What it does                                             |
|---------------------|----------------------------------------------------------|
| `info`              | Show network and contract configuration                  |
| `convert <ADDRESS>` | Convert between Ethereum, Filecoin, and Actor ID formats |
| `--dry-run`         | Simulate transactions without broadcasting (global flag) |

## Configuration (.env)

Copy `.env.mainnet` to `.env` and fill in the values you need.

| Variable                   | Required for        | Description                                            |
|----------------------------|---------------------|--------------------------------------------------------|
| `RPC_URL`                  | Everyone            | Filecoin RPC endpoint                                  |
| `SP_PRIVATE_KEY`           | SP transactions     | Controller wallet private key (0x-prefixed hex)        |
| `SP_ORGANIZATION`          | SP commands         | Your organization address                              |
| `CLIENT_PRIVATE_KEY`       | Client transactions | Client wallet private key                              |
| `CLIENT_ADDRESS`           | Client read-only    | Client wallet address                                  |
| `ADMIN_PRIVATE_KEY`        | Admin commands      | Admin wallet private key                               |
| `USDC_TOKEN`               | Payments            | USDC token contract address (pre-set for mainnet)      |
| `POREP_MARKET`             | Everyone            | PoRep Market contract (pre-set for mainnet)            |
| `FILECOIN_PAY`             | Payments            | FileCoinPay contract (pre-set for mainnet)             |
| `ARIA2C_PATH`              | SP download         | Path to aria2c binary (default: `aria2c` in PATH)      |
| `CURIO_PATH`               | SP Curio claims     | Path to curio binary (default: `curio` in PATH)        |
| `BOOSTD_PATH`              | SP Boost claims     | Path to boostd binary (default: `boostd` in PATH)      |
| `DRY_RUN`                  | Testing             | Set to `true` to simulate without sending transactions |
| `SP_REGISTRY_DATABASE_URL` | Admin only          | SPRegistry database connection string                  |
| `DEBUG`                    | Debugging           | Set to `true` for verbose error output                 |

There are 3 ways of providing the user's private key for blockchain transactions and the priority is as follows:

1. `[ADMIN|CLIENT|SP]_PRIVATE_KEY` variable in the system environment variables,
2. `[ADMIN|CLIENT|SP]_PRIVATE_KEY` variable in the local `.env` file,
3. if none of those are set, the app will prompt the user to input the private key for required operations in a secure manner.

## Important notes

- The app **does not store any state** locally - all state is retrieved from the blockchain by design.
- The app stores all blockchain transaction logs to `logs/`.
- Default behaviour is to wait for each transaction to succeed after sending it.
- The app operates on EVM 0x-addresses and **FEVM smart contract** and does not fully support Filecoin f-addresses.
- The app expects the private key to be 32-byte raw private key (hex, 0x-prefixed).
- Read-only commands do not require private key set, though some of them require user's address (`client --address` and `sp --organization`).
- Rule of thumb: the private key you set is the one that signs and sends transactions, \
  so always use the one with correct permissions / approvals / rights for the transaction you want to send.
- Make sure the address for blockchain transactions you use has enough FIL for gas fees and is **initialized on the Filecoin network**.
- The app prints output of read-only commands in json format to be easily parsable by other tools.
- PoRep Market smart contracts supports only 32 GiB sectors.
- PoRep Market smart contracts assumes a month is always 30 days.

## Security considerations

- All blockchain transactions **require manual user confirmation** before sending. There is no option to override this. \
  If you decline the final confirmation, the command falls back to dry-run behavior without broadcasting the transaction.
- The app runs locally and does not transmit any data to external servers besides blockchain.
  All interactions are between the user's machine and the provided `RPC_URL` blockchain.
- The app does not log any sensitive information to the console or to the log files.
  All transaction logs are stored without any sensitive information.

## Troubleshooting

### "SP organization is not set"

Set `SP_ORGANIZATION` in your `.env` file or pass `--organization` on the command line.

### "Deal is in state X != Y"

You are running a command at the wrong stage. See [How a deal progresses](#how-a-deal-progresses).

### "aria2c not found"

Install aria2: `brew install aria2` (Mac), `sudo apt install aria2` (Debian/Ubuntu), or set `ARIA2C_PATH` in `.env`.

### "curio not found" / "boostd not found"

Install [Curio](https://docs.curiostorage.org/installation) or [Boost](https://boost.filecoin.io/getting-started), or set `CURIO_PATH` / `BOOSTD_PATH` in
`.env`.

### "Insufficient token balance"

Your wallet needs more USDC. Check balance with `client get-filecoinpay-account` and deposit with `client deposit-amount`.

### "Address does not match private key"

Your `CLIENT_ADDRESS` and `CLIENT_PRIVATE_KEY` in `.env` do not correspond. Run `client info --test-keys` to verify.

### "Not authorized for provider"

Your `SP_PRIVATE_KEY` wallet is not registered as a controller for that provider ID.
See [control addresses docs](https://lotus.filecoin.io/storage-providers/operate/addresses/#control-addresses).

### Transactions seem stuck

Run `sp wait` or `client wait` to wait for pending transactions to confirm before sending new ones.

### Want to test without spending gas?

Add `--dry-run` to any command to simulate transactions:

```bash
python3 ./porep_tooling_cli.py --dry-run sp accept-deal 42
```

## Developing new CLI commands

- See files in `cli/commands` for examples of how to implement new commands.
- Keep the code clean and simple, follow the existing patterns and best practices.
- Use `Exception` (`ValueError`, `RuntimeError`, ...) for internal-like errors (things that "should not happen")
  and `click.ClickException` for user-like errors (things that happens "because of the user").
- Use `click.echo` for all user-facing output and `logger` for file logging.
- For read-only commands, print the output in json format for easy parsing by other tools.
