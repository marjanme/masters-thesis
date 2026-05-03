from experiment_logic.types import Configuration, DailyDataRow, Instruction, Market, NewsItem


def build_prompt(
    market: Market,
    daily_data_row: DailyDataRow,
    visible_news: list[NewsItem],
    configuration: Configuration,
    instruction: Instruction,
) -> str:
    prompt_parts: list[str] = [instruction.text.strip()]

    prompt_parts.append(f"Market question:\n{market.question}")
    prompt_parts.append(f"Current date:\n{daily_data_row.date.isoformat()}")
    prompt_parts.append(f"Resolution date:\n{market.resolution_date.isoformat()}")

    if configuration.other_traders == "llms":
        prompt_parts.append("Other participants in this market are LLM agents.")
    elif configuration.other_traders == "humans":
        prompt_parts.append("Other participants in this market are human traders.")

    if configuration.show_market_probabilities:
        prompt_parts.append(
            "\n".join(
                [
                    "Current market probabilities:",
                    f"YES: {daily_data_row.probability_yes:.6f}",
                    f"NO: {daily_data_row.probability_no:.6f}",
                ]
            )
        )

    if visible_news:
        lines = ["Relevant news:"]
        for index, news_item in enumerate(visible_news, start=1):
            lines.append(f"{index}. {news_item.title} ({news_item.date.isoformat()})")
            lines.append(news_item.content)
            lines.append("")
        prompt_parts.append("\n".join(lines).rstrip())

    prompt_parts.append(
        "Return valid JSON in exactly this format:\n"
        "{\n"
        '  "reasoning": "short explanation",\n'
        '  "probability_yes": 0.0\n'
        "}\n\n"
        'The value of "probability_yes" must be a decimal number between 0 and 1.\n'
        "Do not return any text outside the JSON object."
    )
    return "\n\n".join(prompt_parts)
