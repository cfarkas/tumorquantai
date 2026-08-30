from __future__ import annotations

import csv
import stat
from pathlib import Path

import numpy as np
import pytest

from tumorquantai_cli import ihc, immunoscore


def _secret(path: Path) -> Path:
    path.write_bytes(bytes(range(32)))
    path.chmod(0o600)
    return path


def _bundle(root: Path, name: str, *, scale: float = 0.26178) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "info.ini").write_text(
        f"[Scanner]\nscale={scale:.6f}\n",
        encoding="utf-8",
    )
    path = directory / "1.mds"
    path.write_bytes(name.encode("utf-8"))
    return path


def test_discovery_creates_stable_hmac_aliases_and_private_linkage(
    tmp_path: Path,
) -> None:
    source = tmp_path / "private"
    for marker in immunoscore.IMMUNOSCORE_MARKERS:
        _bundle(source, f"private-case-{marker}-scan")
    secret = _secret(tmp_path / "alias.bin")

    first = immunoscore.discover_mds_slides(source, secret)
    second = immunoscore.discover_mds_slides(source, secret)

    assert [row.case_alias for row in first] == [row.case_alias for row in second]
    assert len({row.case_alias for row in first}) == 1
    assert all(immunoscore.CASE_ALIAS_RE.fullmatch(row.case_alias) for row in first)
    assert all(immunoscore.SLIDE_ALIAS_RE.fullmatch(row.slide_alias) for row in first)
    assert all("private-case" not in str(row.public_row()) for row in first)
    assert "source_mds_sha256" not in first[0].public_row()

    digested = immunoscore.add_source_digests(first)
    linkage = tmp_path / "controlled" / "linkage.csv"
    immunoscore.write_or_verify_private_linkage(linkage, digested, resume=True)
    assert stat.S_IMODE(linkage.stat().st_mode) == 0o600
    text = linkage.read_text(encoding="utf-8")
    assert "private-case" in text
    immunoscore.write_or_verify_private_linkage(linkage, digested, resume=True)


def test_discovery_requires_owner_only_alias_secret(tmp_path: Path) -> None:
    source = tmp_path / "private"
    _bundle(source, "case-CD3-scan")
    secret = _secret(tmp_path / "alias.bin")
    secret.chmod(0o644)
    with pytest.raises(immunoscore.ImmunoscoreError, match="0600"):
        immunoscore.discover_mds_slides(source, secret)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("block_boundary_exclusion_um", -1.0),
        ("minimum_dab_color_margin_od", -0.01),
        ("minimum_dab_color_ratio", -0.01),
        ("cell_expansion_um", -1.0),
        ("ck20_target_analysis_mpp", 0.0),
        ("ck20_minimum_dab_od", -0.01),
        ("ck20_minimum_projected_fraction", 0.0),
        ("ck20_minimum_projected_fraction", 1.01),
        ("ck20_minimum_component_um2", 0.0),
        ("ck20_epithelium_expansion_um", -1.0),
        ("minimum_tissue_area_mm2", 0.0),
    ],
)
def test_config_rejects_invalid_nonpositive_bounds(field: str, value: float) -> None:
    config = immunoscore.ImmunoscoreConfig(**{field: value})
    with pytest.raises(immunoscore.ImmunoscoreError):
        config.validate()


def test_run_rejects_symlink_input(tmp_path: Path) -> None:
    source = tmp_path / "private"
    for marker in immunoscore.IMMUNOSCORE_MARKERS:
        _bundle(source, f"case-{marker}-scan")
    linked_source = tmp_path / "linked-source"
    linked_source.symlink_to(source, target_is_directory=True)
    with pytest.raises(immunoscore.ImmunoscoreError, match="must not be a symlink"):
        immunoscore.run_immunoscore(
            linked_source,
            tmp_path / "result",
            _secret(tmp_path / "alias.bin"),
            tmp_path / "linkage.csv",
            immunoscore.ImmunoscoreConfig(),
            dry_run=True,
        )


def test_grouping_retains_incomplete_cases(tmp_path: Path) -> None:
    source = tmp_path / "private"
    for marker in immunoscore.IMMUNOSCORE_MARKERS:
        _bundle(source, f"complete-{marker}-scan")
    _bundle(source, "incomplete-CD3-scan")
    records = immunoscore.discover_mds_slides(source, _secret(tmp_path / "alias.bin"))
    grouped, unavailable = immunoscore.group_case_slides(records)
    assert len(grouped) == 2
    assert len(unavailable) == 1
    assert unavailable[0]["missing_markers"] == "CD8;CK20"


def test_expanded_cell_dab_rule_detects_positive_object() -> None:
    labels = np.zeros((30, 30), dtype=np.int32)
    labels[10:15, 10:15] = 1
    nuclei = ihc.SegmentedNuclei(
        labels=labels,
        label_ids=np.asarray([1], dtype=np.int32),
        centroid_y=np.asarray([12.0]),
        centroid_x=np.asarray([12.0]),
        area_um2=np.asarray([25.0]),
        mean_hematoxylin_od=np.asarray([0.3]),
        mean_dab_od=np.asarray([0.2]),
        nuclear_threshold_od=0.1,
    )
    dab = np.zeros((30, 30), dtype=np.float32)
    dab[8:18, 8:18] = 0.3
    positive, means, coverage = immunoscore._immune_positive_cells(
        nuclei, dab, 1.0, immunoscore.ImmunoscoreConfig()
    )
    assert positive.tolist() == [True]
    assert means[0] > immunoscore.ImmunoscoreConfig().weak_dab_od
    assert coverage[0] > 0.5


def test_streamed_area_includes_tissue_block_with_no_detected_nucleus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    level = immunoscore.MdsLevel(0, "1", 1, 2, 20, 20)

    class FakeSlide:
        levels = (level,)

        def read_tile_block(
            self,
            _level,
            _row_start,
            _row_stop,
            column_start,
            _column_stop,
        ):
            return np.full(
                (20, 20, 3),
                80 if column_start == 0 else 160,
                dtype=np.uint8,
            )

    overview = immunoscore.Overview(
        rgb=np.full((20, 40, 3), 180, dtype=np.uint8),
        level_index=0,
        level_name="1",
        level_width=40,
        level_height=20,
        source_width=40,
        source_height=20,
        overview_mpp_x=1.0,
        overview_mpp_y=1.0,
    )
    registration = immunoscore.RegistrationResult(
        matrix=np.asarray([[1, 0, 0], [0, 1, 0]], dtype=np.float64),
        method="identity-fixture",
        feature_matches=10,
        inliers=10,
        inlier_fraction=1.0,
        tissue_dice=1.0,
        registered_tissue_fraction=1.0,
        qc_status="pass",
    )
    empty = np.empty(0, dtype=np.float64)

    def fake_segment(
        _hematoxylin,
        _dab,
        _tissue,
        _marker,
        _mpp,
        _config,
    ):
        if float(np.mean(_tissue)) and int(_hematoxylin[0, 0]) == 1:
            labels = np.zeros((20, 20), dtype=np.int32)
            labels[9:12, 9:12] = 1
            return ihc.SegmentedNuclei(
                labels=labels,
                label_ids=np.asarray([1], dtype=np.int32),
                centroid_y=np.asarray([10.0]),
                centroid_x=np.asarray([10.0]),
                area_um2=np.asarray([9.0]),
                mean_hematoxylin_od=np.asarray([0.2]),
                mean_dab_od=np.asarray([0.0]),
                nuclear_threshold_od=0.1,
            )
        return ihc.SegmentedNuclei(
            labels=np.zeros((20, 20), dtype=np.int32),
            label_ids=np.empty(0, dtype=np.int32),
            centroid_y=empty,
            centroid_x=empty,
            area_um2=empty,
            mean_hematoxylin_od=empty,
            mean_dab_od=empty,
            nuclear_threshold_od=0.1,
        )

    monkeypatch.setattr(
        ihc,
        "tissue_mask",
        lambda rgb, _mpp: np.ones(rgb.shape[:2], dtype=bool),
    )
    monkeypatch.setattr(
        ihc,
        "separate_hematoxylin_dab_color_checked",
        lambda rgb, *_args: (
            np.full(
                rgb.shape[:2],
                1 if int(rgb[0, 0, 0]) == 80 else 2,
                dtype=np.float32,
            ),
            np.zeros(rgb.shape[:2], dtype=np.float32),
            np.zeros(rgb.shape[:2], dtype=np.float32),
        ),
    )
    monkeypatch.setattr(ihc, "segment_nuclei", fake_segment)
    record = immunoscore.ImmunoscoreSlide(
        case_alias="TQA_CI_" + "A" * 20,
        slide_alias="TQA_CIS_" + "B" * 20,
        source_case_id="private",
        source_slide_id="private-CD3",
        marker="CD3",
        source_path=Path("/private/1.mds"),
        source_mpp=1.0,
        source_mpp_provenance="fixture",
    )
    config = immunoscore.ImmunoscoreConfig(
        target_analysis_mpp=1.0,
        overview_max_edge=512,
        block_tiles=1,
        block_boundary_exclusion_um=1.0,
        minimum_tissue_area_mm2=0.0,
    )
    tissue = np.ones((20, 40), dtype=bool)
    rows, _details = immunoscore.quantify_immune_slide(
        FakeSlide(),
        record,
        overview,
        overview,
        registration,
        tissue,
        np.zeros_like(tissue),
        tissue,
        tissue,
        config,
    )
    common = next(row for row in rows if row["compartment"] == "common_tissue")
    assert common["analyzed_area_mm2"] == pytest.approx(648 / 1_000_000)


def test_ck20_compartment_uses_streamed_pixels_not_blurred_overview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    level = immunoscore.MdsLevel(0, "1", 1, 1, 80, 80)

    class FakeSlide:
        levels = (level,)

        def read_tile_block(self, *_args):
            rgb = np.full((80, 80, 3), 180, dtype=np.uint8)
            rgb[20:60, 20:60] = (120, 70, 30)
            return rgb

    overview = immunoscore.Overview(
        rgb=np.full((20, 20, 3), 180, dtype=np.uint8),
        level_index=0,
        level_name="1",
        level_width=80,
        level_height=80,
        source_width=80,
        source_height=80,
        overview_mpp_x=4.0,
        overview_mpp_y=4.0,
    )
    record = immunoscore.ImmunoscoreSlide(
        case_alias="TQA_CI_" + "A" * 20,
        slide_alias="TQA_CIS_" + "B" * 20,
        source_case_id="private",
        source_slide_id="private-CK20",
        marker="CK20",
        source_path=Path("/private/1.mds"),
        source_mpp=1.0,
        source_mpp_provenance="fixture",
    )
    monkeypatch.setattr(
        ihc,
        "tissue_mask",
        lambda rgb, _mpp: np.ones(rgb.shape[:2], dtype=bool),
    )
    monkeypatch.setattr(
        ihc,
        "separate_hematoxylin_dab_color_checked",
        lambda rgb, *_args: (
            np.zeros(rgb.shape[:2], dtype=np.float32),
            np.zeros(rgb.shape[:2], dtype=np.float32),
            (rgb[:, :, 0] < 150).astype(np.float32),
        ),
    )
    config = immunoscore.ImmunoscoreConfig(
        ck20_target_analysis_mpp=1.0,
        ck20_minimum_component_um2=16.0,
        ck20_minimum_projected_fraction=0.20,
        ck20_epithelium_expansion_um=0.0,
    )

    tissue, epithelium, stroma, metrics = immunoscore.ck20_compartment_masks(
        FakeSlide(), record, overview, config
    )

    assert np.all(tissue)
    assert 0 < np.count_nonzero(epithelium) < epithelium.size
    assert np.array_equal(stroma, tissue & ~epithelium)
    assert metrics["ck20_detection_method"].startswith("streamed-")
    assert metrics["ck20_stream_dab_positive_pixel_count"] == 1600
    assert metrics["ck20_projected_positive_fraction_maximum"] == pytest.approx(1.0)


def test_level_projection_uses_pyramid_scale_not_padded_canvas_ratio() -> None:
    level = immunoscore.MdsLevel(3, "0.125000", 27, 19, 512, 512)
    overview = immunoscore.Overview(
        rgb=np.zeros((2048, 1536, 3), dtype=np.uint8),
        level_index=6,
        level_name="0.015625",
        level_width=1536,
        level_height=2048,
        source_width=75264,
        source_height=107520,
        overview_mpp_x=12.8,
        overview_mpp_y=13.7,
    )
    assert immunoscore._level_to_overview_scale(level, overview) == (0.125, 0.125)
    assert immunoscore._project_block_to_overview(
        8000, 4000, 512, 512, level, overview
    ) == (1000, 500, 1064, 564)


def _slide(case_alias: str, marker: str) -> immunoscore.ImmunoscoreSlide:
    return immunoscore.ImmunoscoreSlide(
        case_alias=case_alias,
        slide_alias=f"TQA_CIS_{marker}{'A' * (17 if marker != 'CK20' else 16)}",
        source_case_id="private",
        source_slide_id=f"private-{marker}",
        marker=marker,
        source_path=Path("/private/1.mds"),
        source_mpp=0.26178,
        source_mpp_provenance="private Motic info.ini scale",
    )


def _case_result(case_alias: str, value: float) -> dict[str, object]:
    rows = []
    for marker in immunoscore.IMMUNE_MARKERS:
        for compartment in (
            "ck20_epithelium_proxy",
            "ck20_stroma_proxy",
        ):
            rows.append(
                {
                    "case_alias": case_alias,
                    "marker": marker,
                    "compartment": compartment,
                    "positive_cell_count": 10,
                    "segmented_nucleus_count": 20,
                    "analyzed_area_mm2": 2.0,
                    "positive_cell_density_per_mm2": value,
                    "mapped_positive_cell_fraction": 1.0,
                    "analysis_mpp": 0.52356,
                    "registration_tissue_dice": 0.8,
                    "qc_status": "pass",
                    "qc_flags": "",
                }
            )
    return {
        "case_alias": case_alias,
        "qc_status": "pass",
        "qc_flags": [],
        "registration_rows": [],
        "compartment_rows": rows,
    }


def test_qc_policy_never_passes_bbox_fallback_or_zero_nuclei() -> None:
    case_alias = "TQA_CI_" + "A" * 20
    payload = _case_result(case_alias, 10.0)
    payload["registration_rows"] = [
        {"marker": "CD3", "method": "tissue-bbox", "qc_status": "pass"},
        {"marker": "CD8", "method": "sift-affine", "qc_status": "pass"},
    ]
    payload["marker_details"] = {
        "CD3": {"segmented_nucleus_count_before_mapping": 0},
        "CD8": {"segmented_nucleus_count_before_mapping": 100},
    }
    reviewed = immunoscore.apply_case_qc_policy(payload)
    assert reviewed["qc_status"] == "review"
    assert reviewed["qc_policy_version"] == immunoscore.IMMUNOSCORE_QC_POLICY_VERSION
    assert reviewed["registration_rows"][0]["qc_status"] == "review"
    cd3_rows = [row for row in reviewed["compartment_rows"] if row["marker"] == "CD3"]
    assert all(row["qc_status"] == "review" for row in cd3_rows)
    assert all("no_segmented_nuclei" in row["qc_flags"] for row in cd3_rows)
    assert all(
        "registration_fallback_requires_review" in row["qc_flags"] for row in cd3_rows
    )


def test_qc_policy_flags_empty_ck20_compartment() -> None:
    case_alias = "TQA_CI_" + "A" * 20
    payload = _case_result(case_alias, 10.0)
    payload["ck20_metrics"] = {
        "ck20_epithelium_fraction_of_tissue": 0.0,
        "ck20_stroma_fraction_of_tissue": 1.0,
    }
    reviewed = immunoscore.apply_case_qc_policy(payload)
    assert reviewed["qc_status"] == "review"
    assert all(
        "degenerate_ck20_compartment" in row["qc_flags"]
        for row in reviewed["compartment_rows"]
    )


def test_aggregation_never_labels_internal_rank_as_consensus_immunoscore(
    tmp_path: Path,
) -> None:
    aliases = ["TQA_CI_" + "A" * 20, "TQA_CI_" + "B" * 20]
    grouped = {
        alias: {
            marker: _slide(alias, marker) for marker in immunoscore.IMMUNOSCORE_MARKERS
        }
        for alias in aliases
    }
    summary = immunoscore.aggregate_results(
        tmp_path,
        grouped,
        grouped,
        [],
        [_case_result(aliases[0], 10.0), _case_result(aliases[1], 20.0)],
        [],
    )
    with (tmp_path / "tables/tumorquantai_immunoscore_values.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert summary["pass_case_count"] == 2
    assert {row["consensus_immunoscore"] for row in rows} == {""}
    assert all(
        "unavailable_requires_pathologist" in row["consensus_immunoscore_status"]
        for row in rows
    )
    assert {row["ck20_guided_internal_rank_group"] for row in rows} == {
        "low",
        "high",
    }
    assert {row["ck20_guided_provisional_immunoscore"] for row in rows} == {
        "pI1",
        "pI3",
    }
    assert {row["ck20_guided_provisional_reference_n"] for row in rows} == {"2"}
    with (tmp_path / "tables/cohort_density_summary.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        density_summary = list(csv.DictReader(handle))
    assert len(density_summary) == 8
    assert {row["analysis_population"] for row in density_summary} == {
        "automatic_qc_pass",
        "all_numerically_available",
    }
    assert {row["n"] for row in density_summary} == {"2"}
    assert {row["mean"] for row in density_summary} == {"15.0"}
    report = (tmp_path / "START_HERE.html").read_text(encoding="utf-8")
    assert "not clinical Immunoscore" in report
    assert "Cohort density summary" in report
    review = (tmp_path / "PATHOLOGIST_REVIEW.html").read_text(encoding="utf-8")
    assert "accept" in review
    assert "flag" in review
    assert "exclude" in review
    with (tmp_path / "tables/pathologist_review_template.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        review_rows = list(csv.DictReader(handle))
    assert len(review_rows) == 2
    assert {row["review_eligibility"] for row in review_rows} == {"eligible"}
    assert {row["pathologist_decision"] for row in review_rows} == {""}


@pytest.mark.parametrize(
    ("percentile", "expected"),
    [
        (0.0, "pI0"),
        (10.0, "pI0"),
        (10.0001, "pI1"),
        (25.0, "pI1"),
        (25.0001, "pI2"),
        (70.0, "pI2"),
        (70.0001, "pI3"),
        (95.0, "pI3"),
        (95.0001, "pI4"),
        (100.0, "pI4"),
    ],
)
def test_provisional_immunoscore_uses_published_five_band_boundaries(
    percentile: float,
    expected: str,
) -> None:
    assert immunoscore._provisional_immunoscore(percentile) == expected


def test_review_qc_case_receives_provisional_score_for_pathologist_adjudication(
    tmp_path: Path,
) -> None:
    aliases = ["TQA_CI_" + letter * 20 for letter in "ABC"]
    grouped = {
        alias: {
            marker: _slide(alias, marker) for marker in immunoscore.IMMUNOSCORE_MARKERS
        }
        for alias in aliases
    }
    results = [_case_result(aliases[0], 10.0), _case_result(aliases[1], 20.0)]
    review_result = _case_result(aliases[2], 30.0)
    for row in review_result["compartment_rows"]:
        row["qc_status"] = "review"
        row["qc_flags"] = "analyzed_area_below_minimum"
    results.append(review_result)
    immunoscore.aggregate_results(tmp_path, grouped, grouped, [], results, [])
    with (tmp_path / "tables/tumorquantai_immunoscore_values.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        by_case = {row["case_alias"]: row for row in csv.DictReader(handle)}
    reviewed = by_case[aliases[2]]
    assert reviewed["qc_status"] == "review"
    assert reviewed["ck20_guided_provisional_immunoscore"] == "pI4"
    assert (
        "requires_pathologist_review"
        in reviewed["ck20_guided_provisional_immunoscore_status"]
    )
    with (tmp_path / "tables/pathologist_review_template.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        review_by_case = {row["case_alias"]: row for row in csv.DictReader(handle)}
    assert review_by_case[aliases[2]]["review_eligibility"] == "eligible"
    assert review_by_case[aliases[2]]["algorithm_qc_status"] == "review"


def test_dry_run_does_not_create_output_or_linkage(tmp_path: Path) -> None:
    source = tmp_path / "private"
    for marker in immunoscore.IMMUNOSCORE_MARKERS:
        _bundle(source, f"case-{marker}-scan")
    output = tmp_path / "result"
    linkage = tmp_path / "controlled/linkage.csv"
    result = immunoscore.run_immunoscore(
        source,
        output,
        _secret(tmp_path / "alias.bin"),
        linkage,
        immunoscore.ImmunoscoreConfig(),
        dry_run=True,
    )
    assert result["complete_case_count"] == 1
    assert not output.exists()
    assert not linkage.exists()
