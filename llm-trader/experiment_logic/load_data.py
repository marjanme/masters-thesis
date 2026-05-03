import json
from datetime import date
from pathlib import Path
from typing import cast

from experiment_logic.types import (
    Configuration,
    DailyDataRow,
    Instruction,
    LoadedInputData,
    Market,
    NewsMode,
    NewsItem,
    OtherTraders,
)


VALID_OTHER_TRADERS = {"llms", "humans", "none"}
VALID_NEWS_MODES = {"all_until_day", "none"}


def load_input_data(input_data_dir: Path) -> LoadedInputData:
    markets: list[Market] = []
    seen_market_ids: set[str] = set()
    for row in _load_json_array(input_data_dir / "markets.json"):
        market_id = _require_non_empty_string(row, "market_id")
        _ensure_unique_id(market_id, seen_market_ids, "market_id")
        markets.append(
            Market(
                market_id=market_id,
                question=_require_non_empty_string(row, "question"),
                resolution_date=_parse_date(_require_non_empty_string(row, "resolution_date"), "resolution_date"),
            )
        )

    instructions: list[Instruction] = []
    seen_instruction_ids: set[str] = set()
    for row in _load_json_array(input_data_dir / "instructions.json"):
        instruction_id = _require_non_empty_string(row, "instruction_id")
        _ensure_unique_id(instruction_id, seen_instruction_ids, "instruction_id")
        instructions.append(
            Instruction(
                instruction_id=instruction_id,
                text=_require_non_empty_string(row, "text"),
            )
        )

    market_ids = {market.market_id for market in markets}
    instruction_ids = {instruction.instruction_id for instruction in instructions}

    daily_data: list[DailyDataRow] = []
    seen_market_dates: set[tuple[str, date]] = set()
    for row in _load_json_array(input_data_dir / "daily_data.json"):
        market_id = _require_non_empty_string(row, "market_id")
        _ensure_reference_exists(market_id, market_ids, "market_id", "markets.json")
        current_date = _parse_date(_require_non_empty_string(row, "date"), "date")
        probability_yes = _parse_probability(row, "probability_yes")
        probability_no = _parse_probability(row, "probability_no")
        _ensure_probability_sum(probability_yes, probability_no, market_id, current_date)

        market_date_key = (market_id, current_date)
        if market_date_key in seen_market_dates:
            raise ValueError(
                f"Duplicate daily data row for market_id={market_id!r} and date={current_date.isoformat()}."
            )
        seen_market_dates.add(market_date_key)

        daily_data.append(
            DailyDataRow(
                market_id=market_id,
                date=current_date,
                probability_yes=probability_yes,
                probability_no=probability_no,
            )
        )

    news: list[NewsItem] = []
    seen_news_ids: set[str] = set()
    for row in _load_json_array(input_data_dir / "news.json"):
        news_id = _require_non_empty_string(row, "news_id")
        market_id = _require_non_empty_string(row, "market_id")
        _ensure_unique_id(news_id, seen_news_ids, "news_id")
        _ensure_reference_exists(market_id, market_ids, "market_id", "markets.json")

        news.append(
            NewsItem(
                news_id=news_id,
                market_id=market_id,
                date=_parse_date(_require_non_empty_string(row, "date"), "date"),
                title=_require_non_empty_string(row, "title"),
                content=_require_non_empty_string(row, "content"),
            )
        )

    configurations: list[Configuration] = []
    seen_configuration_ids: set[str] = set()
    for row in _load_json_array(input_data_dir / "configurations.json"):
        configuration_id = _require_non_empty_string(row, "configuration_id")
        instruction_id = _require_non_empty_string(row, "instruction_id")
        _ensure_unique_id(configuration_id, seen_configuration_ids, "configuration_id")
        _ensure_reference_exists(instruction_id, instruction_ids, "instruction_id", "instructions.json")

        other_traders = _require_non_empty_string(row, "other_traders")
        news_mode = _require_non_empty_string(row, "news_mode")
        if other_traders not in VALID_OTHER_TRADERS:
            raise ValueError(
                f"Invalid other_traders value {other_traders!r}. Allowed values are: {sorted(VALID_OTHER_TRADERS)}."
            )
        if news_mode not in VALID_NEWS_MODES:
            raise ValueError(
                f"Invalid news_mode value {news_mode!r}. Allowed values are: {sorted(VALID_NEWS_MODES)}."
            )

        configurations.append(
            Configuration(
                configuration_id=configuration_id,
                instruction_id=instruction_id,
                show_market_probabilities=_require_boolean(row, "show_market_probabilities"),
                other_traders=cast(OtherTraders, other_traders),
                news_mode=cast(NewsMode, news_mode),
            )
        )

    return LoadedInputData(
        markets=markets,
        daily_data=daily_data,
        news=news,
        instructions=instructions,
        configurations=configurations,
    )


def _load_json_array(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Required input file does not exist: {path}")

    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in file {path}: {exc}") from exc

    if not isinstance(content, list):
        raise ValueError(f"Expected JSON array in file {path}, got {type(content).__name__}.")

    for index, item in enumerate(content):
        if not isinstance(item, dict):
            raise ValueError(f"Expected object at index {index} in file {path}, got {type(item).__name__}.")

    return content


def _require_non_empty_string(row: dict, field_name: str) -> str:
    if field_name not in row:
        raise ValueError(f"Missing required field: {field_name!r}.")

    value = row[field_name]
    if not isinstance(value, str):
        raise ValueError(f"Field {field_name!r} must be a string, got {type(value).__name__}.")

    value = value.strip()
    if not value:
        raise ValueError(f"Field {field_name!r} must be a non-empty string.")

    return value


def _require_boolean(row: dict, field_name: str) -> bool:
    if field_name not in row:
        raise ValueError(f"Missing required field: {field_name!r}.")

    value = row[field_name]
    if not isinstance(value, bool):
        raise ValueError(f"Field {field_name!r} must be a boolean, got {type(value).__name__}.")

    return value


def _parse_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Field {field_name!r} must be a valid date in YYYY-MM-DD format.") from exc


def _parse_probability(row: dict, field_name: str) -> float:
    if field_name not in row:
        raise ValueError(f"Missing required field: {field_name!r}.")

    value = row[field_name]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Field {field_name!r} must be a number, got {type(value).__name__}.")

    probability = float(value)
    if probability < 0.0 or probability > 1.0:
        raise ValueError(f"Field {field_name!r} must be between 0 and 1, got {probability}.")

    return probability


def _ensure_probability_sum(probability_yes: float, probability_no: float, market_id: str, current_date: date) -> None:
    total = probability_yes + probability_no
    if abs(total - 1.0) > 1e-9:
        raise ValueError(
            "Daily data probabilities must sum to 1.0 for "
            f"market_id={market_id!r} and date={current_date.isoformat()}, got {total}."
        )


def _ensure_unique_id(value: str, seen_values: set[str], field_name: str) -> None:
    if value in seen_values:
        raise ValueError(f"Duplicate {field_name} value: {value!r}.")
    seen_values.add(value)


def _ensure_reference_exists(value: str, valid_values: set[str], field_name: str, target_file: str) -> None:
    if value not in valid_values:
        raise ValueError(f"Field {field_name!r} references unknown value {value!r} from {target_file}.")
