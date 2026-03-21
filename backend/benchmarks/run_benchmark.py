from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "data" / "manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "results"


def _backend_path() -> Path:
    return ROOT.parent


if str(_backend_path()) not in sys.path:
    sys.path.insert(0, str(_backend_path()))

from benchmarks.reporting import save_report  # noqa: E402
from benchmarks.runner import run_benchmark  # noqa: E402
from benchmarks.strategies import create_strategy, STRATEGY_REGISTRY  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run retrieval benchmark on a prepared manifest.")
    parser.add_argument(
        "--strategy",
        default="current_dino_hybrid",
        choices=sorted(STRATEGY_REGISTRY),
        help="Retrieval strategy to evaluate.",
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    output_dir = Path(args.output_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    strategy = create_strategy(args.strategy)
    report = run_benchmark(manifest, strategy=strategy, top_k=args.top_k)
    saved = save_report(report, output_dir)

    metrics = report["metrics"]
    manifest_meta = report.get("manifest_meta", {})
    print(f"strategy={report['strategy']}")
    if manifest_meta.get("dataset_name"):
        print(f"dataset={manifest_meta['dataset_name']}")
    print(
        "metrics "
        f"queries={metrics['queries']} "
        f"top1_exact={metrics.get('hit_at_1_count', 0)}/{metrics['queries']} "
        f"hit@1={metrics['hit_at_1']:.4f} "
        f"hit@3={metrics['hit_at_3']:.4f} "
        f"mrr@5={metrics['mrr_at_5']:.4f}"
    )
    print(f"report_json={saved['json']}")
    print(f"report_md={saved['markdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
