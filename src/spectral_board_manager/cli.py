import argparse
import sys
import time

from spectral_board_manager.board_manager import BoardManager


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run parallel spectral sensing boards from a config file."
    )

    parser.add_argument(
        "--config-path",
        required=True,
        help="Path to config.yaml file defining boards and settings",
    )

    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Total number of runs to execute (default: 1)",
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=0.0,
        help="Interval in seconds between runs (default: 0)",
    )

    args = parser.parse_args()

    if args.runs < 1:
        print("--runs must be >= 1", file=sys.stderr)
        sys.exit(1)

    if args.interval < 0:
        print("--interval must be >= 0", file=sys.stderr)
        sys.exit(1)

    mgr = BoardManager(args.config_path)
    mgr.experiment_id = time.strftime("%Y%m%d_%H%M%S")

    try:
        for i in range(args.runs):
            print(f"Run {i + 1}/{args.runs}")
            mgr.run()

            if i < args.runs - 1 and args.interval > 0:
                time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nInterrupted by user. Shutting down cleanly...", file=sys.stderr)

    finally:
        mgr.close()


if __name__ == "__main__":
    main()
