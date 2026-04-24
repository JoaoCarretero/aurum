"""
AURUM Finance — Compare two backtest runs.

Usage: python analysis/compare_runs.py <run_id_a> <run_id_b>
Example: python analysis/compare_runs.py citadel_2026-04-09_1940 citadel_2026-04-09_2304
"""
import sys
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python analysis/compare_runs.py <run_id_a> <run_id_b>")
        print("Example: python analysis/compare_runs.py citadel_2026-04-09_1940 citadel_2026-04-09_2304")
        sys.exit(1)

    from core.ops.run_manager import compare_runs, print_compare

    run_a = sys.argv[1]
    run_b = sys.argv[2]

    diff = compare_runs(run_a, run_b)
    print_compare(diff)
