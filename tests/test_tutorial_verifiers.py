from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUICKSTART_SAMPLE = "TumorQuantAI_LymphomaWSI_022"


def write_text(path: Path, text: str = "ok\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_script(script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / script), *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def create_prepared_quickstart(root: Path) -> None:
    write_text(root / "START_HERE.html", "<html>prepared</html>\n")
    write_text(root / "download/tumorquantai_lymphoma_mds_manifest.csv")
    write_text(root / f"download/raw/{QUICKSTART_SAMPLE}/1.mds")
    write_text(root / f"converted/{QUICKSTART_SAMPLE}/1_L0_rgb.tif")
    write_text(root / f"converted/{QUICKSTART_SAMPLE}/1_L2_rgb.tif")
    write_csv(
        root / "converted/samples.csv",
        ["sample_id", "slide_path"],
        [{"sample_id": QUICKSTART_SAMPLE, "slide_path": "1_L0_rgb.tif"}],
    )
    write_text(root / "inspection/INSPECTION.html", "<html>inspection</html>\n")
    write_csv(
        root / "inspection/inspection_manifest.csv",
        ["sample_id", "slide_path"],
        [{"sample_id": QUICKSTART_SAMPLE, "slide_path": "1_L0_rgb.tif"}],
    )


def create_completed_sample(output: Path, sample: str, percent: float) -> None:
    write_text(output / sample / "overlays/celltypes_overview_and_zoom.png")
    summary = {
        "slide_id": sample,
        "tile_sampling": {"percent_slide": percent, "random_seed": 20260709},
    }
    summary_path = output / sample / "summary/summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    write_csv(
        output / sample / "cell_types/class_counts.csv",
        ["class_id", "cell_type", "count"],
        [{"class_id": 1, "cell_type": "lymphocyte", "count": 3}],
    )
    write_csv(
        output / sample / "cell_types/cell_type_coordinates.csv",
        ["cell_id", "cell_type", "x", "y"],
        [{"cell_id": 1, "cell_type": "lymphocyte", "x": 10, "y": 20}],
    )


def create_aggregate(output: Path, samples: list[str], percent: float) -> None:
    aggregate = output / "aggregated_celltypes"
    write_csv(
        aggregate / "sample_aggregation_audit.csv",
        ["slide_id", "sample_id", "included", "status", "reason", "percent_slide"],
        [
            {
                "slide_id": sample,
                "sample_id": sample,
                "included": "true",
                "status": "included",
                "reason": "",
                "percent_slide": percent,
            }
            for sample in samples
        ],
    )
    header = ["class_id", "cell_type", *samples]
    row = ["1", "lymphocyte", *("3" for _ in samples)]
    for filename in (
        "celltype_counts_by_sample.csv",
        "celltype_fractions_by_sample.csv",
    ):
        path = aggregate / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerow(row)


def test_quickstart_preparation_verifier(tmp_path: Path) -> None:
    create_prepared_quickstart(tmp_path)
    completed = run_script(
        "examples/quickstart/verify_outputs.py",
        "--tutorial-root",
        str(tmp_path),
        "--preparation-only",
    )
    assert completed.returncode == 0, completed.stderr
    assert "QuickStart preparation is complete" in completed.stdout


def test_quickstart_complete_verifier(tmp_path: Path) -> None:
    create_prepared_quickstart(tmp_path)
    output = tmp_path / "smoke-results"
    write_text(output / "START_HERE.html", "<html>results</html>\n")
    create_completed_sample(output, QUICKSTART_SAMPLE, 1.0)
    create_aggregate(output, [QUICKSTART_SAMPLE], 1.0)

    completed = run_script(
        "examples/quickstart/verify_outputs.py",
        "--tutorial-root",
        str(tmp_path),
    )
    assert completed.returncode == 0, completed.stderr
    assert "QuickStart outputs are complete" in completed.stdout


def test_fast_cohort_verifier(tmp_path: Path) -> None:
    samples = ["TumorQuantAI_LymphomaWSI_002", "TumorQuantAI_LymphomaWSI_006"]
    write_text(tmp_path / "START_HERE.html", "<html>cohort</html>\n")
    for sample in samples:
        create_completed_sample(tmp_path, sample, 10.0)
    create_aggregate(tmp_path, samples, 10.0)

    completed = run_script(
        "examples/lymphoma/verify_fast21_outputs.py",
        "--output",
        str(tmp_path),
        "--expected-samples",
        "2",
    )
    assert completed.returncode == 0, completed.stderr
    assert "2-slide TumorQuantAI 10% tutorial outputs are complete" in completed.stdout
