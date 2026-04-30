import dataclasses
import enum
import json
import os
from typing import TypeVar, Callable

from dotenv import load_dotenv

load_dotenv(dotenv_path=None)

MAX_UINT256 = 2 ** 256 - 1

T = TypeVar("T")


def get_env_required(name, default: T | None = None, required_type: Callable[[str], T] = str) -> T:
    return get_env(name, required=True, default=default, required_type=required_type)


def get_env(name, required=False, default: T | None = None, required_type: Callable[[str], T] = str) -> T | None:
    value = os.getenv(name)

    def is_empty(v):
        return v is None or v.strip() == ""

    if is_empty(value) and default is not None:
        return default

    if is_empty(value):
        if required:
            raise RuntimeError(f"Environment variable {name} is not set, see .env file")

        return None

    # noinspection PyTypeChecker
    return required_type(value)


def string_to_bool(value: str | None) -> bool | None:
    if value is None:
        return None

    value = value.strip().lower()

    if value in ["true", "1", "yes", "y"]:
        return True
    elif value in ["false", "0", "no", "n"]:
        return False
    else:
        raise ValueError(f"Unknown boolean value: {value}")


def confirm_str(prompt: str, default_answer: str | None = None, valid_answers: list[str] | None = None) -> str:
    default_str = f" [default: {default_answer}]" if default_answer else ""
    valid_answers = [answer.strip().lower() for answer in valid_answers] if valid_answers else []

    while True:
        answer = input(f"{prompt}{default_str}: ").strip().lower()

        if not answer and default_answer is not None:
            return default_answer
        elif answer and (not valid_answers or answer in valid_answers):
            return str(answer)
        else:
            continue

    assert False  # should not happen


# equivalent to "press enter to continue"
def confirm_ok(prompt: str):
    _ = confirm_str(f"{prompt} [OK]", default_answer="")


def json_dataclass(eq=True, init=True, **d_kwargs):
    def wrapper(cls):
        cls = dataclasses.dataclass(**d_kwargs, eq=eq, init=init)(cls)

        def __repr__(self):
            return json.dumps(
                dataclasses.asdict(self),
                indent=4,
                default=str
            )

        cls.__repr__ = __repr__
        return cls

    return wrapper


def json_pretty(json_data, sort_keys: bool = False):
    def _json_pretty(data):
        if issubclass(type(data), enum.Enum):
            return data.name
        if hasattr(data, "__dict__") and data.__dict__:
            return _json_pretty(data.__dict__)
        if isinstance(data, list):
            return [_json_pretty(item) for item in data]
        if isinstance(data, dict) and data:
            return {key: _json_pretty(value) for key, value in data.items()}
        if not isinstance(data, bool) and type(data) is not int and isinstance(data, int):
            return str(data)
            
        return data

    return json.dumps(_json_pretty(json_data), indent=4, sort_keys=sort_keys)


# converts 1100000000000000000 wei -> 1.1 ETH
def from_wei(amount: int | float, decimals: int) -> float:
    return amount / (10 ** decimals)


def str_from_wei(amount: int | float, decimals: int) -> str:
    # pylint: disable=consider-using-f-string
    return "{:.{}f}".format(from_wei(amount, decimals), decimals)  # cannot be f-string because decimals is dynamic


# converts 1.1 ETH -> 1100000000000000000 wei
def to_wei(amount: int | float, decimals: int) -> int:
    result = amount * (10 ** decimals)

    if result != int(result):
        raise ValueError(f"Precision lost: {result:.10f} != {int(result)}")

    return int(result)


# returns minimal size if size is None
def uint_to_bytes(x: int, size: int | None = 32) -> bytes:
    if x < 0:
        raise ValueError("Cannot convert negative integer to bytes")

    if size is None:
        if x == 0:
            return b"\x00"

        size = (x.bit_length() + 7) // 8

    if not size or size < 0:
        raise ValueError(f"Invalid size: {size}")

    return x.to_bytes(size, "big")


def int_from_bytes(xbytes: bytes) -> int:
    return int.from_bytes(xbytes, "big")


def private_str_to_log_str(private_str) -> str:
    if not private_str:
        return ""

    if isinstance(private_str, bytes):
        _private_str = "0x" + private_str.hex()
    elif isinstance(private_str, int):
        _private_str = hex(private_str)
    else:
        _private_str = str(private_str)

    hex_padding = 2 if _private_str.startswith("0x") else 0

    if len(_private_str) > 65:
        return f"{_private_str[:4 + hex_padding]}...{_private_str[-4:]}"

    if len(_private_str) > 40:
        return f"{_private_str[:2 + hex_padding]}...{_private_str[-2:]}"

    if len(_private_str) > 20:
        return f"{_private_str[:1 + hex_padding]}...{_private_str[-1:]}"

    if len(_private_str) > 5:
        return "*" * len(_private_str)

    return "*" * 5
