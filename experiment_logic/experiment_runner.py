import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from experiment_logic.build_prompt import build_prompt
from experiment_logic.llm_client import LLMClient
from experiment_logic.parse_llm_response import parse_llm_response
from experiment_logic.select_news import select_visible_news
from experiment_logic.types import (
    Configuration,
    ConversationMessage,
    DailyDataRow,
    Instruction,
    LoadedInputData,
    Market,
    NewsItem,
    Prediction,
)


def run_experiment(
    loaded_input_data: LoadedInputData,
    market_id: str,
    configuration_id: str,
    llm_client: LLMClient,
    results_dir: Path,
) -> Path:
    markets_by_id = {market.market_id: market for market in loaded_input_data.markets}
    configurations_by_id = {
        configuration.configuration_id: configuration for configuration in loaded_input_data.configurations
    }
    instructions_by_id = {
        instruction.instruction_id: instruction for instruction in loaded_input_data.instructions
    }

    try:
        market = markets_by_id[market_id]
    except KeyError as exc:
        raise ValueError(f"Unknown market_id: {market_id!r}.") from exc

    try:
        configuration = configurations_by_id[configuration_id]
    except KeyError as exc:
        raise ValueError(f"Unknown configuration_id: {configuration_id!r}.") from exc

    try:
        instruction = instructions_by_id[configuration.instruction_id]
    except KeyError as exc:
        raise ValueError(f"Unknown instruction_id: {configuration.instruction_id!r}.") from exc

    market_daily_data = _get_sorted_daily_data_for_market(loaded_input_data, market.market_id)
    market_news = _get_news_for_market(loaded_input_data, market.market_id)

    run_dir = _create_run_directory(results_dir, market.market_id, configuration.configuration_id)
    predictions_path = run_dir / "predictions.json"
    if hasattr(llm_client, "set_debug_output_dir"):
        llm_client.set_debug_output_dir(run_dir)

    predictions: list[Prediction] = []
    total_days = len(market_daily_data)
    for day_index, daily_data_row in enumerate(market_daily_data, start=1):
        print(
            f"[{market.market_id} config {configuration.configuration_id}] "
            f"{day_index}/{total_days} {daily_data_row.date.isoformat()}",
            flush=True,
        )
        predictions.append(
            _build_prediction_for_day(
                market=market,
                daily_data_row=daily_data_row,
                market_news=market_news,
                configuration=configuration,
                instruction=instruction,
                llm_client=llm_client,
                run_dir=run_dir,
            )
        )
        _write_predictions(predictions_path, predictions)

    return run_dir


def _build_prediction_for_day(
    market: Market,
    daily_data_row: DailyDataRow,
    market_news: list[NewsItem],
    configuration: Configuration,
    instruction: Instruction,
    llm_client: LLMClient,
    run_dir: Path,
) -> Prediction:
    visible_news = select_visible_news(
        news_items=market_news,
        current_date=daily_data_row.date,
        news_mode=configuration.news_mode,
    )

    rendered_prompt = build_prompt(
        market=market,
        daily_data_row=daily_data_row,
        visible_news=visible_news,
        configuration=configuration,
        instruction=instruction,
    )

    user_message = ConversationMessage(role="user", content=rendered_prompt)
    initial_conversation = [user_message]

    raw_response = ""
    try:
        raw_response = llm_client.generate_response(initial_conversation)
        parsed_response = parse_llm_response(raw_response)
    except Exception as exc:
        _write_failed_generation(
            run_dir=run_dir,
            market=market,
            configuration=configuration,
            daily_data_row=daily_data_row,
            rendered_prompt=rendered_prompt,
            raw_response=raw_response,
            exc=exc,
        )
        raise

    assistant_message = ConversationMessage(role="assistant", content=raw_response)
    complete_conversation = [user_message, assistant_message]

    p_yes = round(parsed_response.probability_yes, 6)
    p_no = round(1.0 - parsed_response.probability_yes, 6)

    return Prediction(
        market_id=market.market_id,
        configuration_id=configuration.configuration_id,
        date=daily_data_row.date,
        reasoning=parsed_response.reasoning,
        p_yes=p_yes,
        p_no=p_no,
        rendered_prompt=rendered_prompt,
        complete_conversation=complete_conversation,
    )


def _get_sorted_daily_data_for_market(
    loaded_input_data: LoadedInputData,
    market_id: str,
) -> list[DailyDataRow]:
    market_daily_data = [row for row in loaded_input_data.daily_data if row.market_id == market_id]
    if not market_daily_data:
        raise ValueError(f"No daily_data rows found for market_id: {market_id!r}.")

    return sorted(market_daily_data, key=lambda row: row.date)


def _get_news_for_market(loaded_input_data: LoadedInputData, market_id: str) -> list[NewsItem]:
    return [news_item for news_item in loaded_input_data.news if news_item.market_id == market_id]


def _create_run_directory(results_dir: Path, market_id: str, configuration_id: str) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = results_dir / f"{market_id}_{configuration_id}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _write_predictions(path: Path, predictions: list[Prediction]) -> None:
    serializable_predictions = []
    for prediction in predictions:
        prediction_dict = asdict(prediction)
        prediction_dict["date"] = prediction.date.isoformat()
        serializable_predictions.append(prediction_dict)

    path.write_text(
        json.dumps(serializable_predictions, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_failed_generation(
    run_dir: Path,
    market: Market,
    configuration: Configuration,
    daily_data_row: DailyDataRow,
    rendered_prompt: str,
    raw_response: str,
    exc: Exception,
) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    failure_path = run_dir / f"failed_generation_{timestamp}.json"
    failure_object = {
        "market_id": market.market_id,
        "configuration_id": configuration.configuration_id,
        "date": daily_data_row.date.isoformat(),
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "rendered_prompt": rendered_prompt,
        "raw_response": raw_response,
    }
    failure_path.write_text(
        json.dumps(failure_object, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
