# V1 to V2 migration: SP runbook

Nothing is resealed or moved. The client attaches the existing V1 DataCap claims to a new V2 deal,
and you extend the sectors that hold those claims. Payments then switch from the V1 rail to the V2 rail.
The V1 rail is closed by the client after V2 is active, so for up to 30 days both rails pay you.
That overlap is expected.

Client steps are in [the client runbook](migration-v1-to-v2-client.md).

## What you need

- `SP_ORGANIZATION` set in `.env` to the V2 organization address that owns the provider.
  Check with `uv run python porep_tooling_cli.py sp info`.
- No PoRep wallet signing is needed for this step. The extension message is sent by `sptool` with the miner worker key.
- An active V2 offer that accepts USDFC with a minimum duration of 180 days.
  The V2 deals are proposed by the admin from your offer; you do not accept them.
- Lotus `sptool` installed and configured for the miner, with FIL for the extension message.
  Use `--sptool <path>` or `SPTOOL_PATH` if it is not on `PATH`.
- No resealing and no claim drop. The same claims, now also under the V2 deal.

## Commands

See where each of your deals stands:

```bash
uv run python porep_tooling_cli.py migration-status --provider <f0-provider-id> --check-sectors
```

`--check-sectors` reads the sector expirations behind the adopted claims (slow). It says when the earliest
sector expires too early and the SP must extend.

Extend the sectors of one V2 deal:

```bash
uv run python porep_tooling_cli.py sp extend-deal-sectors <v2-deal-id> --print-only
uv run python porep_tooling_cli.py sp extend-deal-sectors <v2-deal-id>
```

Options: `--sptool PATH`, `--target-epoch N`, `--sector-file FILE`.

The command reads the claim IDs from the V2 deal, maps them to sectors on chain and lists which sectors
expire before the target. It writes those sectors to a file and runs `sptool sectors extend` on them.
It shows a preview and asks for confirmation before it sends the message.

The default target is the V2 service end plus 30 days. While the deal is still ACCEPTED, it is now plus
180 days plus 60 days.

`--print-only` writes the sector file and prints the `sptool` command without running it. If `sptool` is not
on this machine, copy the file and run the printed command where `sptool` is configured.

## When to run

- The client must have adopted the claims first. Until then there is nothing to extend.
- You can run it before or after the V2 deal is activated. Earlier is safer: it only has to land before
  the current sector expiration.
- After the message lands, run the same command again. It prints `nothing to extend` once all sectors
  reach the target. A pending message is not a confirmation.

## Troubleshooting

| Error text | Meaning | Action |
| --- | --- | --- |
| `provider ... does not belong to organization` | Wrong `SP_ORGANIZATION` | Set the V2 organization address; V1 values do not work |
| `has no claims on its adapter yet` | The client has not adopted the claims | Ask the client to run `adopt-v1-claims` |
| `Claim ... is not held by provider` | Claim and provider do not match | Check the deal ID, ask the admin |
| `sptool executable not found` | `sptool` not installed or not on `PATH` | Install it, or pass `--sptool` / `SPTOOL_PATH`, or run the printed command elsewhere |
| `sptool skipped N sector(s)` | `sptool` refused some sectors | Read the printed lines, usually a claim in that sector ends before the target |
| `Warning: some claims end before the target epoch` | A claim in a sector ends before the target | Sectors with other claims may be clamped or skipped; ask the admin |
| `sptool failed` | `sptool` returned an error | Fix the `sptool` setup (miner API, FIL for the message) and re-run |
| `Sector ... is not live on chain` | The sector is gone | Tell the admin; it cannot be extended |

## NV29

NV29 is on 2026-10-19 12:59 UTC (mainnet epoch 6470279). Adopting claims must happen before it, and that
is the client's step. Your step has no NV29 deadline: everything except adoption still works afterwards.
The real deadline is the current expiration of the sectors.
