from dataclasses import dataclass
from datetime import date
from typing import Literal


OtherTraders = Literal["llms", "humans", "none"]
NewsMode = Literal["all_until_day", "none"]
ConversationRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class Market:
    market_id: str
    question: str
    resolution_date: date


@dataclass(frozen=True)
class DailyDataRow:
    market_id: str
    date: date
    probability_yes: float
    probability_no: float


@dataclass(frozen=True)
class NewsItem:
    news_id: str
    market_id: str
    date: date
    title: str
    content: str


@dataclass(frozen=True)
class Instruction:
    instruction_id: str
    text: str


@dataclass(frozen=True)
class Configuration:
    configuration_id: str
    instruction_id: str
    show_market_probabilities: bool
    other_traders: OtherTraders
    news_mode: NewsMode


@dataclass(frozen=True)
class ConversationMessage:
    role: ConversationRole
    content: str


@dataclass(frozen=True)
class ParsedLLMResponse:
    reasoning: str
    probability_yes: float


@dataclass(frozen=True)
class Prediction:
    market_id: str
    configuration_id: str
    date: date
    reasoning: str
    p_yes: float
    p_no: float
    rendered_prompt: str
    complete_conversation: list[ConversationMessage]


@dataclass(frozen=True)
class LoadedInputData:
    markets: list[Market]
    daily_data: list[DailyDataRow]
    news: list[NewsItem]
    instructions: list[Instruction]
    configurations: list[Configuration]
