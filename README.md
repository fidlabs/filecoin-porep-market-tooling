# Filecoin PoRep Market tooling CLI

[![cli/test.sh](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/test-sh.yml/badge.svg)](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/test-sh.yml)
[![Code linters](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/lint.yml/badge.svg)](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/lint.yml)
[![CodeQL](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/github-code-scanning/codeql)
[![Copilot code review](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/copilot-pull-request-reviewer/copilot-pull-request-reviewer/badge.svg)](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/copilot-pull-request-reviewer/copilot-pull-request-reviewer)

Python3 CLI tool for interacting with [Filecoin PoRep Market](https://github.com/fidlabs/porep-market) smart contracts
using [Click](https://click.palletsprojects.com/en/stable/#), [Web3](https://web3py.readthedocs.io/en/stable/) and [psycopg](https://www.psycopg.org/docs/). \
Developed for admins, clients, and SPs to **manage their market interactions** from command line.

## Installation

**Use python >= 3.10**

```bash
python3 --version  # check your python version
git clone https://github.com/fidlabs/filecoin-porep-market-tooling && cd filecoin-porep-market-tooling  # clone the repo
python3 -m pip install -r requirements.txt  # install dependencies
cp .env.mainnet .env  # create your local .env file
chmod 600 .env  # optional, but recommended for security: restrict access to the .env file
```

## Running the CLI

Make sure you have the required environment variables set (see `.env`). \
Run the script: `python3 ./porep_tooling_cli.py` and follow help prompts.

## Important notes

- The app **does not store any state** locally - all state is retrieved from the blockchain by design.
- The app stores all blockchain transaction logs to `logs/`.
- Default behaviour is to wait for each transaction to succeed after sending it.
- The app operates on **FEVM smart contracts** (thus EVM 0x-addresses) but **fully supports Filecoin f-addresses / Actor IDs** with proper conversion.
- There are multiple ways of providing the user's private key for blockchain transactions and the priority is as follows:
    1. `[ADMIN|CLIENT|SP]_PRIVATE_KEY` variable in the system environment variables or in the local `.env` file,
    2. `[ADMIN|CLIENT|SP]_LOTUS_WALLET` and `[ADMIN|CLIENT|SP]_LOTUS_TOKEN` variables when using Lotus wallet,
    3. if non of those are set, the app will prompt the user to input the private key for required operations in a secure manner.
- Read-only commands do not require private key / lotus wallet set, though some of them require user's address (`client --address` and `sp --organization`).
- Rule of thumb: the private key / lotus wallet you set is the one that signs and sends transactions, \
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
- When using Lotus wallet for blockchain transaction signing, the **private key never leaves the Lotus wallet** and is not exposed to the CLI app. \
  This is the recommended way of using the app.

## Typical SP workflow

1. Follow the [Installation](#installation) steps.

2. Steps 3-5 below are required for SP to make blockchain _write_ transactions (such as `sp register-offer`).
   You won't need this in a typical SP flow.

3. **IMPORTANT**: interaction with the chain requires the private key for the message sender,
   so for security do not use your miner wallet for sending commands to the PoRep Market. \
   Instead, you will need to create a _miner controller_ wallet. If you already have one and want to reuse it, that’s fine. \
   However, to follow best security practices, we recommend you create a new wallet and register it as a _controller wallet_
   for all the miners you will be using in the PoRep Market. \
   The PoRep Market then uses controller status to verify that the command sender is authorised to send commands on behalf of your miner. \
   Follow the steps here:
   [https://lotus.filecoin.io/storage-providers/operate/addresses/#control-addresses](https://lotus.filecoin.io/storage-providers/operate/addresses/#control-addresses)

4. Export the private key of your newly created wallet:

   ```bash
   lotus wallet export <your-controller-address> | xxd -r -p | jq -r '.PrivateKey' | base64 -d | xxd -p -c 32 | sed 's/^/0x/'
   ```

   And set it as `SP_PRIVATE_KEY` in your `.env` file. The value you store there
   must be this exported private key in 32-byte hex format with a `0x` prefix - **not** the wallet
   address you pass to `lotus wallet export`

5. Alternatively, generate an auth token for your _controller address_ and use it instead of the private key:

    ```bash
    lotus auth create-token --perm sign --wallet <your-controller-address>
    ```

   And set it as `SP_LOTUS_TOKEN` in your `.env` file alongside `SP_LOTUS_WALLET` with the address of your _controller wallet_. \
   Using this method, the private key never leaves the Lotus wallet and is not exposed to the CLI app.
   You must use _f410 address_ or _standard EVM address_ for this method.

6. Set your SP organization address in `.env`:

      ```bash
      # Organization address to manage SPs from
      # You must have the SP_PRIVATE_KEY of an organization controlling address set to perform SP management operations
      
      SP_ORGANIZATION=<your-controller-address>
      ```

7. Optional, but very useful for downloading the deal data: install `aria2`:
    - on Mac `brew install aria2`
    - on Debian/Ubuntu: `sudo apt install aria2`
    - on Arch: `sudo pacman -S aria2`

8. Now you should be ready to run the tools.
    - to find deals allocated to you and ready to download / onboard:

      ```bash
      python3 ./porep_tooling_cli.py sp get-deals ACTIVE
      ```

    - to download / onboard the deal that is allocated to you:

      ```bash
      python3 ./porep_tooling_cli.py sp onboard-data <deal-id> --output-dir <dir-to-download-to>
      ``` 

    - get the deal allocation IDs:

      ```bash
      python3 ./porep_tooling_cli.py sp get-allocations <deal-id>
      ``` 

    - and claim allocations for a deal:

      ```bash
      python3 ./porep_tooling_cli.py sp claim-allocations {curio|boost} <deal-id> 
      ```

9. To get the full list of commands for the tooling:

    ```bash
    python3 ./porep_tooling_cli.py sp --help
    ```

## Typical PoRep Market Client workflow

1. Follow the [Installation](#installation) steps.

2. Put your client keys in the `.env` file:

   ```bash
   # Use `lotus wallet list` to see your wallets and their addresses and `lotus wallet new delegated` to create new delegated wallet
   # Must be delegated f410 address or standard EVM address
   CLIENT_LOTUS_WALLET=<lotus-wallet>
   
   # Generate this by running `lotus auth create-token --perm sign`
   CLIENT_LOTUS_TOKEN=<lotus-token>
   ```

   or

   ```bash
   # 32-byte raw private key (hex, 0x-prefixed)
   CLIENT_PRIVATE_KEY=<private key>
   ```

3. Prepare your dataset with [Singularity](https://github.com/filecoin-project/singularity) (or equivalent) so you have a published **manifest URL** and piece
   CARs served for the SP to fetch.

4. Propose a deal from that manifest. Deals can be **public** (open retrieval) or **private** (retrieval limited to the deal owner and any wallets you later
   authorize with a voucher):

   ```bash
   python3 ./porep_tooling_cli.py client propose-deal <manifest-url> \
     --price-per-tib-per-month <usdc-in-decimal-format> \
     --duration-months <months> \
     --retrievability-pct <pct> \
     --bandwidth-mbps <mbps> \
     --latency-ms <ms> \
     --indexing-pct <pct> \
     --deal-type <public|private>
   ```

5. Initialize payment (validator, deposit, rail):

   ```bash
   python3 ./porep_tooling_cli.py client init-deal <deal-id>
   ```

6. Make DataCap allocations:

   ```bash
   python3 ./porep_tooling_cli.py client make-allocations <deal-id>
   ```

7. Optional - for a **private** deal, sign an EIP-712 retrieval voucher so a third-party wallet can retrieve the data (used
   with [large-paid-retrievals](https://github.com/fidlabs/large-paid-retrievals)):

   ```bash
   python3 ./porep_tooling_cli.py client sign-retrieval-voucher \
     --grantee <0x-third-party-wallet> \
     --scope <DEAL_ID>
   ```

   Prints a long-lived standalone `RetrievalVoucher` token (`grantee`, `scope`, `issuedAt`,
   `deadline`, embedded `signature`) for `Authorization: RetrievalVoucher`. \
   Clients mint a per-piece `RetrievalProof` and send it as `Authorization: RetrievalProof` —
   see [access-vouchers-eip712](https://github.com/fidlabs/large-paid-retrievals/blob/main/docs/access-vouchers-eip712.md). \
   `--deal-id` is accepted as an alias for `--scope`.

## FCSS repair flow (re-onboard a dataset from a healthy SP)

FCSS requires two SP copies of every dataset. When one SP exits, the client repairs the dataset with a new deal: a
**new SP**, matched by the market like for any other deal, fetches the data from the **healthy SP** (the one still
serving a copy), paying for that retrieval with [large-paid-retrievals](https://github.com/fidlabs/large-paid-retrievals)
(LPR) where needed. The client pays for that one-off retrieval up front, so the new SP never fronts the cost. No keys
are shared and the client, the new SP and the healthy SP don't need to exchange anything outside the CLI and the chain.

**Finding the healthy SP:** the CLI looks for other providers' deals for the same dataset (same manifest hash) that are
ACTIVE, PUBLIC and have claims on-chain. It then checks each provider's advertised HTTP piece endpoint (cid.contact,
else the miner's on-chain multiaddrs, as LPR does, plus Curio's market address) actually serves every piece of the
dataset, using `retrieval-client fetch --dry-run`.
Free sources are preferred, then the cheapest. Both the client and the new SP do this on their own.

**Finding the price:** the CLI runs LPR's `retrieval-client fetch --dry-run` for every piece of the dataset against each
candidate source. The `sp-proxy` quotes each piece through its `402 Payment Required` MPP challenge
([protocol](https://github.com/fidlabs/large-paid-retrievals/blob/main/docs/mpp-filecoinpay.md)) and the dry run sums
those quotes without paying or downloading anything. If the healthy SP serves the data for free, there is nothing to pay.
The dry run signs with a throwaway key that is deleted afterwards, so clients need `retrieval-client` installed too
(see step 3 below), but no wallet key for it.

**How the retrieval payment works:** the LPR `sp-proxy` only accepts a Filecoin Pay one-time rail payment whose payer is
the wallet that signs the retrieval request, i.e. the wallet that downloads. So the client cannot pay the healthy SP
on the new SP's behalf. Instead, `client repair` (or `client pay-repair-retrieval`) makes a one-off
FileCoinPay `deposit` of the retrieval cost **into the FileCoinPay account of the new deal's SP payee**. That is the
payee address the SP registered with `sp register-sp --payee-address`, recorded on-chain in the deal. The new SP runs
LPR `retrieval-client` with the payee key, and it spends available FileCoinPay funds before using any wallet balance,
so the new SP's download is paid by the client. The client's exposure is capped at the deposited amount; the deposit
is separate from and in addition to the regular deal payment rail (`client init-deal`).

**The deposit is the new SP's go-signal:** before a paid download, `sp onboard-data` quotes the pieces it still has to
fetch and only starts once the client's deposits into the payee account, less what the payee has spent on retrievals
since the deal was proposed, cover that quote. Both sides read this from chain, so there is nothing to coordinate.

1. **Healthy SP:** if it charges for retrievals, it runs LPR `sp-proxy` in front of its piece server with a flat
   `--price-usdfc-per-gb` rate, following [LPR for storage providers](https://github.com/fidlabs/large-paid-retrievals#for-storage-providers).
   As LPR requires, its advertised HTTP endpoint must point at the `sp-proxy`.

2. **Client:** install LPR `retrieval-client` as in step 3 (only for quotes; it never gets a client key), then run:

   ```bash
   python3 ./porep_tooling_cli.py client repair <repaired-deal-id>
   ```

   This finds the healthy SP and shows its quoted repair cost, then proposes a new deal for the same manifest with the
   repaired deal's terms (`--price-per-tib-per-month` / `--duration-months` override them). The deal is matched to an
   SP **exactly like any other deal**: clients can't choose the SP. The command waits a few minutes
   (`--wait-minutes`) for that SP to accept, deposits the retrieval cost into its payee account, and runs
   `client init-deal` and `client make-allocations`. The deposit can only be returned by the SP, so it is never made
   for a deal that is still only proposed.

   The command is resumable. The new deal's manifest URL carries a marker naming the repaired deal,
   `<manifest URL>#fcss-repair-of=<repaired-deal-id>` (a URL fragment is never sent to the server, so the manifest
   is fetched and hashed as usual). A re-run finds the deal marked for that repaired deal on-chain and continues from
   wherever it stopped, e.g. when the SP accepted after the wait or a step failed, without proposing or depositing
   twice; once that deal is ACTIVE it reports the repair as done. Other deals for the dataset, such as its surviving
   original copy, are never taken for the repair deal. If unmarked deals for the dataset are still pending, the command
   lists them and asks before proposing another one. A repair deal proposed before deals were marked is continued with
   `--repair-deal <new-deal-id>`, after a confirmation.

   `--source-url` overrides the detected source, e.g. when no healthy SP is advertised on-chain.
   `client pay-repair-retrieval <new-deal-id> --repair-of <repaired-deal-id>` runs the deposit step on its own, e.g. to
   top it up when the new SP reports a shortfall.

   Before depositing, the CLI checks the client's earlier deposits to that payee since the deal was proposed. If they
   already cover the cost it refuses (`--allow-repeat-deposit` overrides, e.g. when they were for another deal with the
   same SP); if they cover part of it, only the shortfall is deposited. If the RPC can't serve logs that old (some
   providers only keep the last 24h), it refuses rather than risk paying twice: use an RPC that serves older logs, or
   check the deposits yourself and pass `--allow-unverified-history`.

3. **New SP:** build LPR `retrieval-client`
   ([for dataset consumers](https://github.com/fidlabs/large-paid-retrievals#for-dataset-consumers)), put it in `PATH`
   or set `RETRIEVAL_CLIENT_PATH`, and onboard the data through LPR instead of aria2:

   ```bash
   git clone https://github.com/fidlabs/large-paid-retrievals && cd large-paid-retrievals
   go build -o bin/retrieval-client ./cmd/retrieval-client
   ```

   ```bash
   python3 ./porep_tooling_cli.py sp onboard-data <new-deal-id> --output-dir <dir> \
     --payee-key-file ./payee.key
   ```

   By default (`--downloader auto`) `onboard-data` uses aria2 when the manifest host serves sample pieces for free, as
   for any regular deal, and otherwise retrieves the data through `retrieval-client` as a repair; `--downloader lpr`
   forces the latter. The payee key is only needed when the source charges. The CLI finds the healthy SP itself
   (`--host` / `--port` override it), and checks that the key belongs to the deal's payee before downloading. If the
   client's deposits don't cover the quote yet, it stops with `Waiting for client funding: quote …, available …, short
   …` and the command the client runs to close the gap; run `onboard-data` again once it is funded. If the RPC can't
   serve the deposit and payment logs since the deal was proposed, it also stops rather than pay from the SP's own
   funds. `--allow-unfunded-retrieval` downloads anyway, paying any difference from the payee's own funds. The payee
   must be a regular `0x` wallet, not a contract, with a little FIL for Filecoin Pay gas. `retrieval-client` gets the
   CLI's `RPC_URL` and `FILECOIN_PAY`, so it spends from the same FileCoinPay account the client funded, in USDFC.
   Works with `retrieval-client` built from LPR `main` or `v1-maintenance`. In `tools/sp-pipeline.sh`, set
   `PAYEE_KEY_FILE`; deals still waiting for client funding are skipped and retried on the next run.

To have a specific SP store the repair copy, an admin proposes the deal with `admin propose-deal-for-offer`, and the
client then runs `client pay-repair-retrieval`. Choosing an SP is an admin-only action.

Limitations:

- Only deals paid in **USDFC** can be repaired: LPR `sp-proxy`s settle retrievals in USDFC, and the client's deposit and the
  new SP's retrieval use the deal's payment token. `client repair` and `pay-repair-retrieval` refuse other tokens.
  USDFC is the chain's known USDFC address, or `SP_PROXY_PAY_TOKEN_ADDRESS` on local devnets (the same variable
  `retrieval-client` reads).
- LPR currently lets only the deal owner retrieve **private** deals, so only **public** deals can be repaired. The
  `client sign-retrieval-voucher` integration depends on LPR's unmerged voucher-based access.
- Health is judged from on-chain deal state, claims and a dry-run quote of every piece. The CLI does not check sector
  faults or proving status directly.
- LPR has no price endpoint, so the price comes from a dry run that requests every piece. Each dry run makes the
  `sp-proxy` store an unpaid quote per piece, which it prunes after its retention period.
- The payee's FileCoinPay account also collects the SP's deal earnings, and LPR has no spend cap. The funding check
  runs right before the download, so a price rise after the client's quote makes the new SP wait for a top-up; but if
  the `sp-proxy` raises its price during the download itself, `retrieval-client` covers the difference from those
  funds or the payee wallet's USDFC.
- The funding check counts all of the client's deposits to the payee and all of the payee's retrieval payments since the
  deal was proposed, so concurrent repairs between the same client and SP share one budget, and other paid retrievals
  by the same payee in that window count against it.
- LPR can't sign through a Lotus wallet, so the payee key must be available as a plain key file on the downloading host.
  The payee is also the account that receives your deal revenue, so this puts a high-value key on a machine that
  downloads third-party data: keep the file `chmod 600` and owned by the user running the CLI (`onboard-data` refuses it
  otherwise), prefer `--payee-key-file` over the `FILPAY_PRIVATE_KEY` variable, and withdraw revenue from the payee's
  FileCoinPay account regularly. A separate low-balance retrieval wallet or an external signer would remove this
  exposure but needs support in LPR and the registry.

## Developing new CLI commands

- See files in `cli/commands` for examples of how to implement new commands.
- Keep the code clean and simple, follow the existing patterns and best practices.
- Use `Exception` (`ValueError`, `RuntimeError`, ...) for internal-like errors (things that "should not happen")
  and `click.ClickException` for user-like errors (things that happens "because of the user").
- Use `click.echo` for all user-facing output and `logger` for file logging.
- For read-only commands, print the output in json format for easy parsing by other tools.
