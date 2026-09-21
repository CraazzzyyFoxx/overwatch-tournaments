"""Answer normalisation for a registration form: raw answers in, typed values
and structured field errors out.

Pure: no DB, no FastAPI, no ORM. The only I/O-adjacent import is
``shared.core.errors`` (plain Pydantic) for ``raise_field_errors``, the one
helper that turns collected errors into the wire exception.

Every error carries an ``ErrorCode`` value; those strings are the stable wire
contract the frontend looks up in its ``forms.errors.<code>`` table, so a code
outside the enum is a bug. ``msg`` is only an English fallback.

Rules that need a dependency (role composition, ``require_verified``) live in
tournament-service plugins and append their own ``FieldError``s.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Any, NoReturn

from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.social import (
    InvalidHandlePattern,
    SocialProvider,
    compile_handle_pattern,
    normalize_social_handle,
)
from shared.domain.forms.builtins import default_pattern, identity_provider
from shared.domain.forms.schema import Condition, FormField, FormSchema

__all__ = (
    "ErrorCode",
    "FieldError",
    "NormalizedAnswers",
    "evaluate_condition",
    "normalize_answers",
    "raise_field_errors",
    "visible_fields",
)


class ErrorCode(StrEnum):
    REQUIRED = "required"
    INVALID_FORMAT = "invalid_format"
    INVALID_TYPE = "invalid_type"
    INVALID_OPTION = "invalid_option"
    TOO_MANY = "too_many"
    NOT_VERIFIED = "not_verified"
    UNKNOWN_FIELD = "unknown_field"
    FORM_VERSION_STALE = "form_version_stale"
    SCHEMA_INVALID = "schema_invalid"


@dataclass(frozen=True, slots=True)
class FieldError:
    field: str
    code: str
    msg: str
    params: Mapping[str, Any] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class NormalizedAnswers:
    values: dict[str, Any]
    errors: list[FieldError]


#: A number as typed by a human: ``1,5`` is the Russian decimal separator.
_NUMBER = re.compile(r"^-?\d+(?:[.,]\d+)?$")
_BOOLS = {"true": True, "false": False}
#: ``truthy`` in ``visible_when``: a checkbox that round-tripped through a form
#: encoding arrives as the string ``"false"``, which is not a truthy answer.
_FALSE_STRINGS = frozenset({"", "false", "0"})
_BOOL_KEYS = frozenset({"stream_pov"})


def _err(field: str, code: ErrorCode, msg: str, **params: Any) -> FieldError:
    # ``FieldError.code`` is declared ``str``: it holds the plain wire string.
    return FieldError(field=field, code=code.value, msg=msg, params=MappingProxyType(params))


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() not in _FALSE_STRINGS
    return bool(value)


def evaluate_condition(cond: Condition, answers: Mapping[str, Any]) -> bool:
    """Whether ``cond`` holds for ``answers``. A missing answer is falsy, never an error."""
    answer = answers.get(cond.field)
    if cond.op == "truthy":
        return _truthy(answer)
    if cond.op == "in":
        options = cond.value if isinstance(cond.value, (list, tuple, set)) else [cond.value]
        if isinstance(answer, list):
            return any(item in options for item in answer)
        return answer in options
    if cond.op == "neq":
        return answer != cond.value
    return answer == cond.value


def visible_fields(schema: FormSchema, answers: Mapping[str, Any]) -> list[FormField]:
    """The fields ``answers`` is asked for. Conditions read the RAW answers."""
    return [f for f in schema.fields() if f.visible_when is None or evaluate_condition(f.visible_when, answers)]


def _battle_tag_candidate(value: str) -> str:
    """The canonical form a BattleTag pattern is matched against.

    The provider's own rule, not a second copy of it: the name is
    case-insensitive, the discriminator is not part of it, and the spacing a
    human types around the ``#`` is not either.
    """
    return normalize_social_handle(SocialProvider.BATTLENET, value)


def _coerce_number(key: str, raw: Any) -> tuple[Any, FieldError | None]:
    bad = _err(key, ErrorCode.INVALID_TYPE, "Expected a number.")
    if raw is None:
        return None, None
    # ``bool`` is an ``int`` in Python; a checkbox is not an answer to a number.
    if isinstance(raw, bool):
        return None, bad
    # An ``int`` is returned untouched: above 2**53 a float round-trip corrupts it.
    if isinstance(raw, int):
        return raw, None
    if isinstance(raw, float):
        return (int(raw) if raw.is_integer() else raw), None
    if not isinstance(raw, str):
        return None, bad
    text = raw.strip()
    if not text:
        return "", None
    if not _NUMBER.fullmatch(text):
        return None, bad
    text = text.replace(",", ".")
    try:
        return int(text), None
    except ValueError:
        number = float(text)
    return (int(number) if number.is_integer() else number), None


def _coerce_bool(key: str, raw: Any) -> tuple[Any, FieldError | None]:
    if isinstance(raw, bool):
        return raw, None
    if isinstance(raw, str):
        text = raw.strip().casefold()
        if not text:
            return "", None
        if text not in _BOOLS:
            return None, _err(key, ErrorCode.INVALID_TYPE, "Expected true or false.")
        return _BOOLS[text], None
    if raw is None:
        return None, None
    return None, _err(key, ErrorCode.INVALID_TYPE, "Expected true or false.")


def _coerce_date(key: str, raw: Any) -> tuple[Any, FieldError | None]:
    if raw is None:
        return None, None
    if isinstance(raw, date):
        return raw.isoformat(), None
    if not isinstance(raw, str):
        return None, _err(key, ErrorCode.INVALID_TYPE, "Expected a date.")
    text = raw.strip()
    if not text:
        return "", None
    try:
        return date.fromisoformat(text).isoformat(), None
    except ValueError:
        return None, _err(key, ErrorCode.INVALID_TYPE, "Expected a date as YYYY-MM-DD.")


def _coerce_select(field: FormField, raw: Any) -> tuple[Any, FieldError | None]:
    key = field.key
    if not isinstance(raw, str):
        if raw is None:
            return None, None
        return None, _err(key, ErrorCode.INVALID_TYPE, "Expected one of the options.")
    text = raw.strip()
    if not text:
        return "", None
    options = field.options or []
    if text not in options:
        return None, _err(key, ErrorCode.INVALID_OPTION, "Not one of the options.", value=text)
    return text, None


def _coerce_multi_select(field: FormField, raw: Any) -> tuple[Any, FieldError | None]:
    key = field.key
    if raw is None:
        return None, None
    if not isinstance(raw, list):
        return None, _err(key, ErrorCode.INVALID_TYPE, "Expected a list of options.")
    options = field.options or []
    chosen = {item.strip() for item in raw if isinstance(item, str) and item.strip()}
    unknown = sorted(chosen - set(options)) + [str(i) for i in raw if not isinstance(i, str)]
    if unknown:
        return None, _err(key, ErrorCode.INVALID_OPTION, "Not one of the options.", values=tuple(unknown))
    return [option for option in options if option in chosen], None


def _coerce_tags(key: str, raw: Any) -> tuple[Any, FieldError | None]:
    if raw is None:
        return None, None
    if not isinstance(raw, list):
        return None, _err(key, ErrorCode.INVALID_TYPE, "Expected a list of BattleTags.")
    tags: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            return None, _err(key, ErrorCode.INVALID_TYPE, "Expected a list of BattleTags.")
        text = item.strip()
        if text and text not in tags:
            tags.append(text)
    return tags, None


def _coerce_roles(key: str, raw: Any) -> tuple[Any, FieldError | None]:
    """Structure only: ``[{role, subrole?, is_primary, top_heroes?}]``. The
    composition rules (primary/flex/sub-role catalog) are a service-side plugin."""
    if raw is None:
        return None, None
    bad = _err(key, ErrorCode.INVALID_TYPE, "Expected a list of roles.")
    if not isinstance(raw, list):
        return None, bad
    for item in raw:
        if not isinstance(item, dict):
            return None, bad
        role = item.get("role")
        subrole = item.get("subrole")
        heroes = item.get("top_heroes")
        if not isinstance(role, str) or not role.strip():
            return None, bad
        if subrole is not None and not isinstance(subrole, str):
            return None, bad
        if not isinstance(item.get("is_primary", False), bool):
            return None, bad
        if heroes is not None and not (isinstance(heroes, list) and all(isinstance(h, str) for h in heroes)):
            return None, bad
    return list(raw), None


def _coerce_text(key: str, raw: Any) -> tuple[Any, FieldError | None]:
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        return None, _err(key, ErrorCode.INVALID_TYPE, "Expected text.")
    return raw.strip(), None


def _coerce(field: FormField, raw: Any) -> tuple[Any, FieldError | None]:
    key, kind = field.key, field.kind
    if kind == "number":
        return _coerce_number(key, raw)
    if kind == "checkbox" or key in _BOOL_KEYS:
        return _coerce_bool(key, raw)
    if kind == "date":
        return _coerce_date(key, raw)
    if kind == "select":
        return _coerce_select(field, raw)
    if kind == "multi_select":
        return _coerce_multi_select(field, raw)
    if key == "smurf_tags":
        return _coerce_tags(key, raw)
    if key == "roles":
        return _coerce_roles(key, raw)
    provider = identity_provider(key)
    value, error = _coerce_text(key, raw)
    if error is not None or provider is None or not value:
        return value, error
    return normalize_social_handle(provider, value), None


def _pattern_targets(field: FormField, value: Any) -> list[str]:
    """What the pattern actually runs on: BattleTags match in canonical form,
    ``smurf_tags`` matches every tag."""
    if field.key == "smurf_tags":
        return [_battle_tag_candidate(tag) for tag in value]
    if not isinstance(value, str):
        return []
    return [_battle_tag_candidate(value) if field.key == "battle_tag" else value]


def _check_pattern(field: FormField, value: Any) -> FieldError | None:
    explicit = field.validation.regex if field.validation else None
    pattern = explicit or default_pattern(field.key, field.kind)
    if not pattern:
        return None
    targets = _pattern_targets(field, value)
    if not targets:
        return None
    # Defence in depth only: `FormSchema` refuses an uncompilable `validation.regex`
    # at save time (where `field` is the schema path, as the design says). This
    # branch catches a row stored before that invariant existed, so all it can name
    # is the answer key.
    try:
        compiled = compile_handle_pattern(pattern)
    except InvalidHandlePattern as exc:
        return _err(field.key, ErrorCode.SCHEMA_INVALID, str(exc))
    message = (field.validation.error_message if field.validation else None) or "Invalid format."
    bad = next((t for t in targets if compiled.fullmatch(t) is None), None)
    return None if bad is None else _err(field.key, ErrorCode.INVALID_FORMAT, message, value=bad)


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def normalize_answers(
    schema: FormSchema,
    answers: Mapping[str, Any],
    *,
    partial: bool = False,
    enforce_required: bool = True,
) -> NormalizedAnswers:
    """Coerce ``answers`` to typed values, collecting EVERY error.

    ``partial`` (a PATCH) validates only the keys that are present; a hidden
    field is neither required nor stored. ``enforce_required=False`` is the
    draft path: formats still have to be right, blanks are allowed.
    """
    declared = {f.key for f in schema.fields()}
    values: dict[str, Any] = {}
    errors = [_err(key, ErrorCode.UNKNOWN_FIELD, f"Unknown field {key!r}.") for key in answers if key not in declared]
    for field in visible_fields(schema, answers):
        key = field.key
        if partial and key not in answers:
            continue
        value, error = _coerce(field, answers.get(key))
        if error is not None:
            errors.append(error)
            continue
        required = field.required and enforce_required
        # An unchecked required checkbox is a missing answer, not a wrong type.
        if _is_empty(value) or value is False:
            if required:
                errors.append(_err(key, ErrorCode.REQUIRED, "This field is required."))
                continue
            if _is_empty(value):
                continue
        pattern_error = _check_pattern(field, value)
        if pattern_error is not None:
            errors.append(pattern_error)
            continue
        values[key] = value
    return NormalizedAnswers(values=values, errors=errors)


def raise_field_errors(errors: Sequence[FieldError], status_code: int = 422) -> NoReturn:
    raise ApiHTTPException(
        status_code=status_code,
        detail=[ApiExc(msg=e.msg, code=e.code, field=e.field) for e in errors],
    )
