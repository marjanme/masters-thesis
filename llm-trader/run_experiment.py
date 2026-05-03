import argparse
from pathlib import Path

from experiment_logic.experiment_runner import run_experiment
from experiment_logic.llm_client import build_llm_client
from experiment_logic.load_data import load_input_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one LLM prediction experiment.")
    parser.add_argument("--market-id", required=True, help="Market identifier to run.")
    parser.add_argument("--configuration-id", required=True, help="Configuration identifier to run.")
    parser.add_argument(
        "--provider",
        required=True,
        choices=["mock", "ollama"],
        help="LLM provider to use.",
    )
    parser.add_argument(
        "--model-name",
        default="qwen3.5:4b",
        help="Model name for Ollama.",
    )
    parser.add_argument(
        "--ollama-base-url",
        default="http://hivecore.famnit.upr.si:6666",
        help="Base URL for the Ollama server.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=120,
        help="Request timeout in seconds for Ollama calls.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_data_dir = Path("input_data")
    results_dir = Path("results")

    loaded_input_data = load_input_data(input_data_dir)
    llm_client = build_llm_client(
        provider=args.provider,
        model_name=args.model_name,
        ollama_base_url=args.ollama_base_url,
        timeout_seconds=args.timeout_seconds,
    )

    run_dir = run_experiment(
        loaded_input_data=loaded_input_data,
        market_id=args.market_id,
        configuration_id=args.configuration_id,
        llm_client=llm_client,
        results_dir=results_dir,
    )

    print(f"Experiment completed. Results written to {run_dir / 'predictions.json'}")


if __name__ == "__main__":
    main()
