import enum

class RailStatus(enum.Enum):
    NONE = 0
    PREPARED = 10
    ACTIVE = 20
    TERMINATED = 100

    @staticmethod
    def from_string(s: str | None) -> "RailStatus | None":
        if not s:
            return None

        s = s.strip().lower()

        if s == "none":
            return RailStatus.NONE
        elif s == "prepared":
            return RailStatus.PREPARED
        elif s == "active":
            return RailStatus.ACTIVE
        elif s == "terminated":
            return RailStatus.TERMINATED
        else:
            raise ValueError(f"Invalid rail status: {s}")

    @staticmethod
    def to_string_list():
        return [status.name for status in RailStatus]

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name