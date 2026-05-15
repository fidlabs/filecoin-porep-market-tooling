import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class OnboardedDealRecord:
    deal_id: int
    onboarded_at: str
    software: str
    provider_id: int


@dataclass
class OnboardState:
    path: Path
    deals: dict[int, OnboardedDealRecord] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "OnboardState":
        state = cls(path=path)

        if not path.exists():
            return state

        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        for deal_id_str, record in raw.get("onboarded_deals", {}).items():
            state.deals[int(deal_id_str)] = OnboardedDealRecord(
                deal_id=int(deal_id_str),
                onboarded_at=record["onboarded_at"],
                software=record["software"],
                provider_id=int(record["provider_id"]),
            )

        return state

    def is_onboarded(self, deal_id: int) -> bool:
        return deal_id in self.deals

    def mark_onboarded(self, deal_id: int, software: str, provider_id: int) -> None:
        self.deals[deal_id] = OnboardedDealRecord(
            deal_id=deal_id,
            onboarded_at=datetime.now(timezone.utc).isoformat(),
            software=software,
            provider_id=provider_id,
        )
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "onboarded_deals": {
                str(deal_id): {
                    "onboarded_at": record.onboarded_at,
                    "software": record.software,
                    "provider_id": record.provider_id,
                }
                for deal_id, record in self.deals.items()
            }
        }

        temp_path = self.path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")

        temp_path.replace(self.path)
