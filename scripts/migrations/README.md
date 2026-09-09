# V1 to V2 operator steps

Run from the repository root. These scripts are for the migration operator. Clients and SPs use the commands in the main README.

Configure the existing V2 contracts and Filecoin Pay, plus:

- `POREP_MARKET_V1`: trusted source market address.
- `POREP_MARKET_V1_CHAIN_ID`: source chain ID, matching the connected network.
- `POREP_MARKET_SECTOR_STATUS_INSPECTOR`: inspector bound to the V2 market.
- `MIGRATION_PAYMENT_TOKEN`: expected offer token address. Use the verified USDFC deployment for the selected network.

Inventory requires an RPC endpoint exposing `Filecoin.StateMinerActiveSectors`. An unsupported RPC method is an error, not evidence of healthy sectors. Use the existing admin signing configuration for proposal and close prerequisites. The service close step uses `POREP_SERVICE_PRIVATE_KEY`, or `POREP_SERVICE_LOTUS_WALLET` with `POREP_SERVICE_LOTUS_TOKEN`. Keep credentials in the configured environment, never in a migration plan or command-line argument.

## Qualify and propose

```bash
uv run python scripts/migrations/v1_to_v2.py inventory
uv run python scripts/migrations/v1_to_v2.py propose <v1-deal-id> <offer-id> --print-only
uv run python scripts/migrations/v1_to_v2.py propose <v1-deal-id> <offer-id>
```

Only complete, running V1 deals qualify. Review the selected provider, original client, token, price, SLI requirements and 180-day duration before proposal. The original manifest hash and URL are preserved; the URL fragment records the source reference. No mapping file is published or exchanged.
Migration discovery currently supports successful direct admin calls to `proposeDealWithSpecificOffer`.
Multisig or forwarded proposals are rejected because their authority is not verified by this tooling.

Clients run `prepare-migration`, SPs run `extend-deal-sectors`, and clients run `finish-migration` when ready. Participants can proceed independently. The existing V2 service/admin path submits evidence and activates V2.

## Close V1 after V2 activates

```bash
uv run python scripts/migrations/v1_to_v2.py close-v1-if-v2-active --print-only
uv run python scripts/migrations/v1_to_v2.py close-v1-if-v2-active <v2-deal-id>
```

The script verifies the V2 replacement before stopping V1. The optional ID is a V2 deal ID. Without it, the script checks all discovered migration pairs. Waiting deals must keep their V1 rail open.

If admin and service roles run in separate environments, select `--step admin`, `--step service` or `--step settle`. The admin step reduces the settlement interval and lockup period. The service step disables future payments. Settlement then finalizes the terminated rail. Re-running reads chain state and continues the remaining steps.

For an already reviewed deployment, an external scheduler can call:

```bash
uv run python scripts/migrations/v1_to_v2.py --yes close-v1-if-v2-active
```

Configure one execution at a time for each signing wallet. This repository does not install a scheduler. Do not run the same wallet concurrently from multiple machines. Resolve pending or uncertain transactions before another run.

## Pilot acceptance

Before closing the first V1 deal, verify the deployed V2 evidence, refresh and payment services. URL Finder support for the migration fragment is separate work. Unavailable manifests require an explicit operational decision about SLI and payment behavior; this tooling does not manufacture SLI data.

Immediately before `activateEvidence`, the deployed service must check one current tipset.
Reject activation after `proposedAtEpoch + 30 days`, or if the registered IDs differ from
the complete source set, any claim is terminated or ends before `currentEpoch + 180 days`,
or any sector is inactive or expires before that epoch. Incomplete reads must stop
activation. The existing activation contract does not enforce these migration checks;
the earlier client finish check cannot guarantee a later asynchronous activation is safe.
Implement and verify this service guard before the pilot.

Record actual V2 activation and V1 finalization from chain. Verify a V2 settlement and a multi-batch resume before wider migration. Short overlapping payments are expected. Skipped V1 deals remain obligations to resolve before retiring V1 infrastructure.
