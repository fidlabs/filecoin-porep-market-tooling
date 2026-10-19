# Move V1 deals to V2: SP

Nothing is resealed. The client attaches your V1 DataCap claims to new V2 deals.
You extend the sectors that hold those claims, so they last as long as the V2 deal (180 days from activation).
Once V2 is active it pays you, and the client stops the V1 payment shortly after.
The client's steps: [client runbook](migration-v1-to-v2-client.md).

**Deadline: the current expiration of your sectors, not NV29.** `migration-status` below shows the earliest one.

`porep` below is an alias, not a separate tool. It means `uv run python porep_tooling_cli.py`, run from the
repository root (or `python3 porep_tooling_cli.py` if you installed with pip, see [Installation](../README.md#installation)).
To set it: `alias porep='uv run python porep_tooling_cli.py'`.

## Before you start

- `.env` created from `.env.mainnet`, with `SP_ORGANIZATION` set to your V2 organization address. Check it with `porep sp info`.
  No PoRep wallet key is needed for these steps.
- Lotus `sptool` configured for your miner, with FIL for the message. If it is not on `PATH`, pass `--sptool <path>` or set `SPTOOL_PATH`.
- Your V2 deal IDs from us.
- To make your life easy, set up an alias, so that you can use `porep` rather than `uv run python porep_tooling_cli.py` or `python3 porep_tooling_cli.py`, depending on the installation process you used see [Installation](../README.md#installation): 
```bash
alias porep='uv run python porep_tooling_cli.py' 
```
or 
```bash
alias porep='python3 porep_tooling_cli.py>'
```

## Update the .env file
Add the following 2 lines to the .env file
```bash
POREP_MARKET_V1=0xBD669aBd1188F52e82aF114E17aCE2842DCc0Eb4
POREP_MARKET_V1_CHAIN_ID=314
```

## Extend the sectors

After the client has attached the claims:

```bash
porep migration-status --provider <f0 provider id> --check-sectors   # 1 status
porep sp extend-deal-sectors <V2> --print-only                       # 2 check
porep sp extend-deal-sectors <V2>                                    # 3 extend
```

1. **Status.** Shows your deals and the earliest sector expiration. Slow.
2. **Check.** Lists the sectors to extend and prints the `sptool` command. Sends nothing.
3. **Extend.** Runs `sptool sectors extend` after you confirm.

Done when step 3, run again after the message lands, prints `nothing to extend`.
If `sptool` runs on another machine, step 2 writes the sector file: copy it there and run the printed command.

## If a command fails

| Output contains | Do |
| --- | --- |
| `does not belong to organization` | Set `SP_ORGANIZATION` to the V2 organization address |
| `has no claims on its adapter yet` | The client has not attached the claims yet; wait |
| `sptool executable not found` | Install `sptool`, or pass `--sptool` / set `SPTOOL_PATH` |
| `sptool failed` | Fix the `sptool` setup (miner API, FIL for the message), then re-run |
| anything else | Send us the full output |
