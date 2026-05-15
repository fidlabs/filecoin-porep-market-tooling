import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class DealCacheRecord:
    deal_id: int
    provider_id: int
    onchain: bool
    rail_id: int
    payment_rate: int
    checked_at: str


@dataclass
class DealOnboardCache:
    """
    Optional local cache of on-chain deal onboarding status (Filecoin Pay rail payment rate).
    The cache is derived from chain reads; it is not used as the source of truth for skipping deals.
    """

    path: Path
    deals: dict[int, DealCacheRecord] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "DealOnboardCache":
        cache = cls(path=path)

        if not path.exists():
            return cache

        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        deals_raw = raw.get("deals", raw.get("onboarded_deals", {}))
        for deal_id_str, record in deals_raw.items():
            if "onchain" in record:
                cache.deals[int(deal_id_str)] = DealCacheRecord(
                    deal_id=int(deal_id_str),
                    provider_id=int(record["provider_id"]),
                    onchain=bool(record["onchain"]),
                    rail_id=int(record.get("rail_id", 0)),
                    payment_rate=int(record.get("payment_rate", 0)),
                    checked_at=record.get("checked_at", datetime.now(timezone.utc).isoformat()),
                )
            else:
                # Legacy onboarded_deals format: treat as on-chain snapshot without rail details.
                cache.deals[int(deal_id_str)] = DealCacheRecord(
                    deal_id=int(deal_id_str),
                    provider_id=int(record["provider_id"]),
                    onchain=True,
                    rail_id=0,
                    payment_rate=0,
                    checked_at=record.get("onboarded_at", datetime.now(timezone.utc).isoformat()),
                )

        return cache

    def update_deal(
        self,
        deal_id: int,
        *,
        provider_id: int,
        onchain: bool,
        rail_id: int,
        payment_rate: int,
    ) -> None:
        self.deals[deal_id] = DealCacheRecord(
            deal_id=deal_id,
            provider_id=provider_id,
            onchain=onchain,
            rail_id=rail_id,
            payment_rate=payment_rate,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "deals": {
                str(deal_id): {
                    "provider_id": record.provider_id,
                    "onchain": record.onchain,
                    "rail_id": record.rail_id,
                    "payment_rate": str(record.payment_rate),
                    "checked_at": record.checked_at,
                }
                for deal_id, record in self.deals.items()
            }
        }

        temp_path = self.path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")

        temp_path.replace(self.path)


# Backward-compatible alias used by older imports.
OnboardState = DealOnboardCache
OnboardedDealRecord = DealCacheRecord
