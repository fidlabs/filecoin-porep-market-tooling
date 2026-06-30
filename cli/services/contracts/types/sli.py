from cli import utils

# @notice Unified SLI thresholds for requirements, capabilities, and attestations
# @dev STRUCT EXTENSION PROTOCOL:
#      - This struct may be extended by appending new fields
#      - New fields MUST be added at the end only
#      - Field value of 0 means "do not evaluate this dimension"
#      - Existing field order and types MUST NOT change
#      - Contracts MUST handle 0 values as "don't care" in comparisons
# @dev Storage compatibility:
#      - Old data reads 0 for new fields (uninitialized storage)
#      - Old deals automatically skip new SLI dimensions
# @dev Extension example:
#      V1: { retrievabilityBps, bandwidthBytesPerSecond, latencyMs }
#      V2: { retrievabilityBps, bandwidthBytesPerSecond, latencyMs, indexingPct }
@utils.json_dataclass()
class SLIThresholds:
    retrievability_bps: int  # Valid range: 0-10000 (basis points, e.g. 7550 = 75.50%). 0 means "don't care"
    bandwidth_bytes_per_second: int  # Capped at ~64 Gbps
    latency_ms: int
    indexing_pct: int  # Valid range: 0-100. 0 means "don't care"



# @notice Represents an attestation record for SLI (Service Level Indicator) tracking
# @dev Stores the timestamp of the last update and the associated SLI thresholds
@utils.json_dataclass()
class Attestation:
    last_update: int
    slis: SLIThresholds
