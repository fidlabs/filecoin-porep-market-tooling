# Move V1 deals to V2: client

Your V1 deals move to V2 with the same provider and the same data, without resealing.
You attach the V1 DataCap claims to a new V2 deal, then stop paying for the V1 deal.
The SP has its own steps: [SP runbook](migration-v1-to-v2-sp.md).

**Deadline: steps 1-3 of "Move a deal" must be done for every deal before NV29, 2026-10-19 12:59 UTC. Aim for 17 October.**
After NV29 the claims can no longer be attached. Everything after step 3 has no deadline.

`porep` below is an alias, not a separate tool. It means `uv run python porep_tooling_cli.py`, run from the
repository root (or `python3 porep_tooling_cli.py` if you installed with pip, see [Installation](../README.md#installation)).
To set it: `alias porep='uv run python porep_tooling_cli.py'`.

## Before you start

- `.env` created from `.env.mainnet`, with the client wallet: `CLIENT_PRIVATE_KEY`, or `CLIENT_LOTUS_WALLET` and `CLIENT_LOTUS_TOKEN`.
  If you already had a `.env`, copy `POREP_MARKET_V1` and `POREP_MARKET_V1_CHAIN_ID` into it from `.env.mainnet`.
- FIL for gas in the client wallet.
- USDFC in the client wallet. `init-deal` deposits the first month of each V2 deal into Filecoin Pay.
- The pair list from us, grouped by SP: V1 deal → V2 deal, the V1 end date, and which SPs confirmed the extension.

## Move a deal

For each pair, in this order:

```bash
porep client adopt-v1-claims <V2> <V1> --print-only   # 1 check
porep client init-deal <V2>                            # 2 init
porep client adopt-v1-claims <V2> <V1>                 # 3 adopt
porep client finish-migration <V2> <V1>                # 4 finish
```

1. **Check.** Sends nothing. It should end with `has no payment rail yet`.
   On any other error stop and send us the output: the V2 deal can still be fixed at this point.
2. **Init.** Creates the payment rail and deposits the first month. It ends by suggesting `client make-allocations`:
   don't run it on a migration deal, it would make the SP seal the data again.
3. **Adopt.** Attaches the V1 claims. Done when it prints `All N V1 claims are registered on V2 deal <V2>`.
   Large deals take a while: about 5 minutes to check the claims, then 1-3 minutes per batch of 100 claims.
   Run one adopt per deal at a time.
4. **Finish.** Done when it prints `DataCap posting finished`. After this the V2 deal is activated and starts paying,
   so run it only once the SP has confirmed it will extend its sectors. It can wait until after NV29.

Every command asks before it sends and is safe to re-run.
A claim attached to a V2 deal stays with that deal forever, so check the pair before step 3.

## Wait for activation (nothing to do)

```bash
porep migration-status --client <your address>
```

The service activates the V2 deal and V2 starts paying the SP. The SP extends its sectors on its own.

## Stop paying for V1 (after V2 is ACTIVE)

```bash
porep client close-v1-deal <V1> --v2-deal-id <V2>
```

Done when it prints `Rail settled and finalized`.

Close it as soon as the V2 deal is ACTIVE.

V1 rails were created with 30 days' notice: after you close one, V1 keeps paying the SP for that long.
We shorten the notice for each deal before you close it, so V1 and V2 overlap only briefly.
The command refuses while the notice is longer than 2 days; then ask us and re-run later.

If it prints `still paying until epoch ...`, re-run after that epoch.

If a V2 deal will not be ACTIVE before its V1 deal's end date, ask us: we close that V1 rail before then.

## If a command fails

Send us the full output. These you can fix yourself:

| Output contains | Do |
| --- | --- |
| `Environment variable POREP_MARKET_V1` | copy `POREP_MARKET_V1` and `POREP_MARKET_V1_CHAIN_ID` from `.env.mainnet` into your `.env` |
| `has no payment rail yet` | `porep client init-deal <V2>`, then re-run |
| pending transaction | `porep client wait`, then re-run |
| `already registered on V2 deal` | another adopt run for this deal is still going; let it finish, then re-run |
| `429 Too Many Requests` | the RPC is rate limiting, re-run |
| `Deposit ... with` | run the printed `client deposit-amount` command, then re-run |

## Good to know

- A V2 deal runs 180 days from activation, paid in USDFC at the SP's offer price.
- Your Filecoin Pay account must stay funded in USDFC; while it is short, V2 activation and closing V1 rails fail. Check it with
  `porep client get-filecoinpay-account 0x80B98d3aa09ffff255c3ba4A241111Ff1262F045`.
