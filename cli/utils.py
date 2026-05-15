import dataclasses
import enum
import json
import os
from typing import TypeVar, Callable

import click
from dotenv import load_dotenv

load_dotenv(dotenv_path=None)

MAX_UINT256 = 2 ** 256 - 1
SECTOR_SIZE_BYTES = 32 * 1024 ** 3  # 32 GiB  # TODO LATER take sector size from smart contracts

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


_confirm_yes_for_all_sessions: set[str] = set()


def confirm(text: str,
            default: bool | None = False,
            abort: bool = False,
            session_id: str | None = None) -> bool:
    #
    answer = "yes" if session_id and session_id in _confirm_yes_for_all_sessions else None
    default_answer = "yes" if default else "no" if default is False else None
    yes_for_all_answers = ["all"] if session_id else []
    yes_answers = ["yes"]
    no_answers = ["no"]

    answer = confirm_str(text=text,
                         default=default_answer,
                         valid_answers=yes_answers + no_answers + yes_for_all_answers,
                         answer=answer).strip().lower()

    if answer in no_answers:
        if abort:
            raise click.Abort()
        else:
            return False
    #
    elif answer in yes_for_all_answers and session_id:
        _confirm_yes_for_all_sessions.add(session_id)
        return True
    elif answer in yes_answers:
        return True
    else:
        assert False  # should not happen


# if answer is set, print the prompt and return the answer immediately without asking the user
# this function supports only case insensitive mode
def confirm_str(text: str,
                default: str | None = None,
                valid_answers: list[str] | None = None,
                prompt_suffix: str = ": ",
                show_choices: bool = True,
                answer: str | None = None,
                allow_short_answer: bool = True) -> str:
    #
    valid_answers = [_answer.strip().lower() for _answer in valid_answers] if valid_answers else []
    default = default.strip().lower() if default else None

    if default is not None and valid_answers and default not in valid_answers:
        valid_answers = [default] + valid_answers

    if allow_short_answer:
        # pylint: disable=unsubscriptable-object
        valid_answers_short = {answer[0]: answer for answer in valid_answers}

        if len(valid_answers_short) != len(valid_answers):
            raise RuntimeError("Short answers are not unique")
    else:
        valid_answers_short = {}

    valid_answers_labels = [answer.capitalize() if answer == default else answer for answer in valid_answers]
    valid_answers_labels = f" [{'/'.join(valid_answers_labels)}]" if valid_answers_labels and show_choices else ""
    text = f"{text}{valid_answers_labels}{prompt_suffix}"

    if answer is not None:
        click.echo(text + answer)
        return answer.strip().lower()

    while True:
        answer = click.prompt(text=text,
                              prompt_suffix="",
                              default=default,
                              show_default=False).strip().lower()

        if not valid_answers or answer in valid_answers:
            return answer
        if answer in valid_answers_short:
            return valid_answers_short[answer]
        else:
            continue

    assert False  # should not happen


# equivalent to "press enter to continue"
def confirm_ok(prompt: str):
    _ = confirm_str(f"{prompt} [OK]", default="OK", prompt_suffix=" ")


def json_dataclass(eq=True, init=True, **d_kwargs):
    def wrapper(cls):
        cls = dataclasses.dataclass(**d_kwargs, eq=eq, init=init)(cls)

        def __str__(self):
            return json_pretty(dataclasses.asdict(self))

        cls.__str__ = __str__
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
        # pylint: disable=unidiomatic-typecheck
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


def bytes_to_sectors(bytes_size: int) -> float:
    return bytes_size / SECTOR_SIZE_BYTES
