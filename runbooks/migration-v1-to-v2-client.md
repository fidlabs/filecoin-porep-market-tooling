# V1 to V2 migration: client runbook

Your existing V1 deals move to V2 without resealing. You keep the same provider and the same data.
The V1 DataCap claims are attached to a new V2 deal, then the V1 payment rail is closed.
SPs have their own steps: see [the SP runbook](migration-v1-to-v2-sp.md).

## Who does what

| Step | Actor | Tool and wallet |
| --- | --- | --- |
| 1. Propose one V2 deal per V1 deal, send you the pair list `V1 id -> V2 id` | Admin | Admin wallet |
| 2. Adopt the V1 claims into the V2 deal | You | PoRep CLI, client wallet |
| 3. Initialize the V2 deal, then finish DataCap posting | You | PoRep CLI, client wallet |
| 4. Submit evidence and activate the V2 deal | PoRep Market service | Nothing for you to do |
| 5. Extend the sectors holding the claims | SP | PoRep CLI and `sptool` (miner worker key) |
| 6. Close the V1 rail (twice) | You | PoRep CLI, client wallet |

You do nothing before step 1 is done. Everything is read from chain, so the pair list is the only
thing to exchange. Every command below is safe to re-run.

## Deadline

Step 2 must land before the NV29 network upgrade: mainnet epoch 6470279, **2026-10-19 12:59 UTC**.
After it, DataCap transfers are disabled on chain and the only way to move the data would be resealing.
Target: all 12 deals adopted by **2026-10-17**.

Steps 3 to 6 have no NV29 deadline. After NV29 everything except `adopt-v1-claims` still works.

## Prerequisites

- CLI installed and `.env` created from `.env.mainnet`: see [Installation](../README.md#installation).
  `POREP_MARKET_V1` and `POREP_MARKET_V1_CHAIN_ID` are already set in `.env.mainnet`.
- Client signing set in `.env`: `CLIENT_PRIVATE_KEY`, or `CLIENT_LOTUS_WALLET` with `CLIENT_LOTUS_TOKEN`.
  Use `CLIENT_ADDRESS` (or `client --address`) for read-only commands.
  It must be the client address of the V1 deals.
- FIL for gas in the client wallet. Step 2 needs gas only, no DataCap balance.
- USDFC for the V2 deposits (steps 3 and later). See [Funding](#funding).
- The pair list from the admin.

Run the commands from the repository root.

## Steps

### Step 2. Adopt the V1 claims (before NV29)

Run once per pair. Check the plan first, then send:

```bash
uv run python porep_tooling_cli.py client adopt-v1-claims <v2-deal-id> <v1-deal-id> --print-only
uv run python porep_tooling_cli.py client adopt-v1-claims <v2-deal-id> <v1-deal-id>
```

The command extends the term of each V1 claim through the V2 DataCap adapter. It sends batches of up
to 100 claims per transaction: deal 68 has 305 claims, so 4 transactions. It asks for confirmation
once for the whole batch set. The global `--dry-run` option (or `DRY_RUN`) behaves like `--print-only` here;
use `--print-only` for planning.

Done when it prints `All N V1 claims are registered on V2 deal <id>`. Re-running afterwards reports that
all claims are registered and skips them.

### Step 3. Initialize the V2 deal and finish posting

First create the validator, approve the operator and create the payment rail:

```bash
uv run python porep_tooling_cli.py client init-deal <v2-deal-id>
```

It deposits the first month in USDFC into your Filecoin Pay account. See [Funding](#funding).
Then close DataCap posting. Check readiness first:

```bash
uv run python porep_tooling_cli.py client finish-migration <v2-deal-id> <v1-deal-id> --print-only
uv run python porep_tooling_cli.py client finish-migration <v2-deal-id> <v1-deal-id>
```

It requires every V1 claim adopted and the rail in status PREPARED. Done when it prints
`DataCap posting finished`. V2 payments start when the service activates the deal.

### Step 4. Wait for activation

The PoRep Market service submits evidence and activates the V2 deal. You do nothing. Watch it:

```bash
uv run python porep_tooling_cli.py migration-status --client <client-address>
```

Done when the V2 deal shows as ACTIVE. Add `--check-sectors` to also see the earliest sector expiration
(slow). The V1 sectors must outlive the V2 service window; the SP extends them in step 5.

### Step 5. SP extends the sectors

The SP does this; you do nothing. It can happen before or after activation. See the SP runbook.

### Step 6. Close the V1 deal

Once the V2 deal is ACTIVE, run this twice, with the same arguments:

```bash
uv run python porep_tooling_cli.py client close-v1-deal <v1-deal-id> --v2-deal-id <v2-deal-id> --print-only
uv run python porep_tooling_cli.py client close-v1-deal <v1-deal-id> --v2-deal-id <v2-deal-id>
```

- First run: terminates the V1 Filecoin Pay rail. The SP is still paid on V1 for the rail lockup period
  (30 days). That overlap with V2 is expected and accepted. The goal is no gap.
- Second run, after the rail end epoch: settles and finalizes the rail. Until then it prints the end
  epoch and exits. The admin pauses the V1 settlement bot for this rail in between.

Termination needs your account lockup settled in the V1 token. If it is not, the command prints the
shortfall and the exact `client deposit-amount` command to run. Done when the second run prints
`Rail settled and finalized`, or `already settled and finalized; nothing to do`.

## Funding

- V2 deals are paid in USDFC. An axlUSDC balance does not fund a USDFC deal.
- `init-deal` deposits one month of the offer price (deal size in 32 GiB sectors times the price) and
  asks for confirmation. Part of the deposit is held as lockup, not charged.
- After `finish-migration`, `client deposit-for-deals <v2-deal-id> --months N` tops up the account to cover
  N months. It deposits only the missing amount. It refuses deals whose DataCap posting is not finished.
- Check the balance with `client get-filecoinpay-account <token-address>`.
- USDFC is `0x80B98d3aa09ffff255c3ba4A241111Ff1262F045`.
- Closing a V1 rail may need more of the V1 token (USDFC or axlUSDC), see step 6.

## Things to know

- A claim adopted into a V2 deal stays bound to that deal forever. Check the pair list before you run
  adopt. The command checks that client and provider match, not that it is the intended deal.
- The V2 deal runs 180 days from activation at the offer price in USDFC.
- The V2 requested size must be within 10% of the V1 claimed size, otherwise adopt refuses and the admin
  fixes the manifest.
- A V2 proposal expires if it is not finished within the deal expiration window. Finish steps 2 and 3 early.
- The public Glif RPC works for all commands.

## Troubleshooting

| Error text | Meaning | Action |
| --- | --- | --- |
| `POREP_MARKET_V1_CHAIN_ID ... does not match the connected chain` | `.env` points at a different network than the V1 market | Use the `.env.mainnet` values: `RPC_URL` for mainnet and `POREP_MARKET_V1_CHAIN_ID=314` |
| `V2 deal ... client ... differs from V1 deal ... client` (or `provider ... differs`) | Wrong pair | Check the pair list, ask the admin |
| `V1 deal ... belongs to client ..., not ...` | Wrong client wallet or `CLIENT_ADDRESS` | Use the client of the V1 deal |
| `requested size ... is not within ...% of the V1 claimed size` | V2 manifest size is off | Admin fixes the V2 manifest; nothing to do on your side |
| `V1 claim ... already has term max` | The claim cannot be extended further | Ask the admin; do not retry |
| `V1 claim ... expired at epoch` | The claim is already gone | Ask the admin; it cannot be adopted |
| `V2 deal ... is EXPIRED, expected ACCEPTED` (or another state) | The proposal expired or was activated already | Ask the admin to propose a new V2 deal |
| `DataCap posting is already finished` | Step 3 is done | Wait for activation (step 4) |
| `V2 evidence adapter is not operational` | The admin switched the V2 adapter off | Ask the admin |
| `has no payment rail yet` | `init-deal` not run | Run `client init-deal <v2-deal-id>` |
| `rail status is ..., expected PREPARED` | `init-deal` did not finish | Re-run `client init-deal <v2-deal-id>` |
| `V1 claim(s) are not registered on V2 deal` | Adoption incomplete | Re-run `adopt-v1-claims` |
| `Cannot terminate rail ... right now` | Account lockup not settled | Deposit the printed amount with `client deposit-amount`, re-run |
| `RailInactiveOrSettled` or `already settled and finalized` | The V1 rail is already closed | Nothing to do |
| Pending transaction error, or a stuck run | An earlier transaction has not landed | Run `client wait`, then re-run the command |
