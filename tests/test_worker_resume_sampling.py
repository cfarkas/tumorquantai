from __future__ import annotations

import importlib.util
import gzip
import json
import logging
import os
import tempfile
import types
import unittest
import sys
from argparse import Namespace
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "lazyslide_histoplus_wsi_celltype.py"
SPEC = importlib.util.spec_from_file_location("histoplus_worker_resume_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def requested(percent: float, seed: int = 7) -> Namespace:
    return Namespace(percent_slide=percent, patch_random_seed=seed, collage_grid=None)


def completed(percent: float, seed: int = 7) -> dict:
    return {
        "tile_sampling": {"percent_slide": percent, "random_seed": seed},
        "patch_sampling": {},
    }


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def write_core_outputs(output: Path, *, plain_csv: bool = True, counts: bool = True) -> None:
    csv_paths = [output / "plotting_metadata/detected_cell_types.csv"]
    if counts:
        csv_paths.append(output / "cell_types/class_counts.csv")
    for path in csv_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("column\n", encoding="utf-8")

    coordinate_path = output / "cell_types" / (
        "cell_type_coordinates.csv" if plain_csv else "cell_type_coordinates.csv.gz"
    )
    coordinate_path.parent.mkdir(parents=True, exist_ok=True)
    if plain_csv:
        coordinate_path.write_text("class_name\n", encoding="utf-8")
    else:
        with gzip.open(coordinate_path, "wt", encoding="utf-8") as handle:
            handle.write("class_name\n")
    (output / "cell_types/cell_type_coordinates.npy").write_bytes(b"\x93NUMPYtest")

    for relative in [
        "overlays/overview_with_zoom_box.png",
        "overlays/zoom_overlay_celltypes.png",
        "overlays/celltypes_overview_and_zoom.png",
        "paper_figures/celltypes_paper_figure.png",
        "paper_figures/celltype_counts_barplot.png",
    ]:
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG_MAGIC + b"test")
    for relative in [
        "overlays/celltypes_overview_and_zoom.pdf",
        "paper_figures/celltypes_paper_figure.pdf",
        "paper_figures/celltype_counts_barplot.pdf",
    ]:
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-test")
    legend_path = output / "paper_figures/celltypes_paper_figure_legend.txt"
    legend_path.write_text(
        "Figure legend\nSlide ID: fixture\nCounts source: cell_types/class_counts.csv\n",
        encoding="utf-8",
    )
    for relative in [
        "plotting_metadata/detected_cell_types.json",
        "plotting_metadata/cell_type_palette.json",
        "summary/run_metadata.json",
    ]:
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")


class SourceMppTests(unittest.TestCase):
    def test_explicit_source_mpp_overrides_missing_metadata(self) -> None:
        wsi = types.SimpleNamespace(
            properties=types.SimpleNamespace(mpp=None),
            set_mpp=mock.Mock(),
        )
        args = Namespace(slide_mpp=0.261780, mpp=0.5)
        value = module.resolve_source_slide_mpp(wsi, args, logging.getLogger(__name__))
        self.assertAlmostEqual(value, 0.261780)
        wsi.set_mpp.assert_called_once_with(0.261780)

    def test_embedded_source_mpp_is_used_without_override(self) -> None:
        wsi = types.SimpleNamespace(properties=types.SimpleNamespace(mpp=0.25))
        args = Namespace(slide_mpp=None, mpp=0.5)
        value = module.resolve_source_slide_mpp(wsi, args, logging.getLogger(__name__))
        self.assertEqual(value, 0.25)

    def test_missing_source_mpp_fails_closed(self) -> None:
        wsi = types.SimpleNamespace(properties=types.SimpleNamespace(mpp=None))
        args = Namespace(slide_mpp=None, mpp=0.5)
        with self.assertRaisesRegex(RuntimeError, "--slide-mpp"):
            module.resolve_source_slide_mpp(wsi, args, logging.getLogger(__name__))


class ThumbnailSourceTests(unittest.TestCase):
    def test_original_slide_thumbnail_can_override_processing_mosaic(self) -> None:
        attached = module.np.full((12, 18, 3), 17, dtype=module.np.uint8)
        fallback = module.np.full((10, 15, 3), 231, dtype=module.np.uint8)

        class FakeWsi:
            images = {}

            def __getitem__(self, key):
                if key == "wsi_thumbnail":
                    return attached
                raise KeyError(key)

        class FakeSlide:
            def get_thumbnail(self, _size):
                return module.Image.fromarray(fallback)

        normal = module.get_wsi_thumbnail_rgb(FakeWsi(), FakeSlide(), 100)
        original = module.get_wsi_thumbnail_rgb(
            FakeWsi(), FakeSlide(), 100, prefer_fallback=True
        )
        self.assertEqual(int(normal[0, 0, 0]), 17)
        self.assertEqual(int(original[0, 0, 0]), 231)


class PaperFigureLayoutTests(unittest.TestCase):
    def test_rare_nonzero_percentages_do_not_render_as_zero(self) -> None:
        self.assertEqual(module.format_paper_percentage(0.0), "0.0%")
        self.assertEqual(module.format_paper_percentage(2 / 5118), "0.04%")
        self.assertEqual(module.format_paper_percentage(1 / 20000), "<0.01%")
        self.assertEqual(module.format_paper_percentage(0.7), "70.0%")

    def test_legacy_positional_renderer_call_remains_supported(self) -> None:
        overview = module.np.full((24, 36, 3), 245, dtype=module.np.uint8)
        qc_inset = module.np.full((20, 28, 3), 225, dtype=module.np.uint8)
        detected = module.pd.DataFrame(
            {
                "class_name": ["Cancer cell"],
                "count": [1],
                "fraction": [1.0],
                "color_hex": ["#005AB5"],
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            outputs = module.build_paper_celltype_figures(
                overview,
                qc_inset,
                detected,
                "LEGACY_CALL",
                Path(temporary),
                30,
                360,
                0.5,
            )
            self.assertEqual(len(outputs), 5)
            legend = Path(outputs["paper_figure_legend_txt"]).read_text(
                encoding="utf-8"
            )
            self.assertIn("ROI coordinates in source pixels: not recorded", legend)
            self.assertIn("c, Enlarged QC view", legend)
            self.assertNotIn("outlined box marks", legend)

    def test_layout_places_statistics_left_and_images_stacked_right(self) -> None:
        fig, axes = module.create_paper_celltype_layout()
        try:
            self.assertEqual(
                list(axes), ["statistics", "overview", "qc_inset"]
            )
            statistics = axes["statistics"].get_subplotspec()
            overview = axes["overview"].get_subplotspec()
            qc_inset = axes["qc_inset"].get_subplotspec()
            self.assertEqual((statistics.colspan.start, statistics.colspan.stop), (0, 1))
            self.assertEqual((statistics.rowspan.start, statistics.rowspan.stop), (0, 2))
            self.assertEqual((overview.colspan.start, overview.colspan.stop), (1, 2))
            self.assertEqual((overview.rowspan.start, overview.rowspan.stop), (0, 1))
            self.assertEqual((qc_inset.colspan.start, qc_inset.colspan.stop), (1, 2))
            self.assertEqual((qc_inset.rowspan.start, qc_inset.rowspan.stop), (1, 2))
            self.assertGreater(fig.get_figwidth(), fig.get_figheight())
        finally:
            module.plt.close(fig)

    def test_paper_figure_has_publication_panels_and_companion_legend(self) -> None:
        overview = module.np.full((120, 180, 3), 245, dtype=module.np.uint8)
        qc_inset = module.np.full((100, 140, 3), 225, dtype=module.np.uint8)
        detected = module.pd.DataFrame(
            {
                "class_id": [1, 2],
                "class_name": ["Cancer cell", "Lymphocytes"],
                "count": [7, 3],
                "fraction": [0.7, 0.3],
                "color_hex": ["#005AB5", "#228B22"],
            }
        )
        created = []
        original_layout = module.create_paper_celltype_layout

        def capture_layout():
            figure, axes = original_layout()
            created.append((figure, axes))
            return figure, axes

        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(
                module, "create_paper_celltype_layout", side_effect=capture_layout
            ):
                outputs = module.build_paper_celltype_figures(
                    overview_rgb=overview,
                    zoom_rgb=qc_inset,
                    detected_df=detected,
                    slide_id="CASE_001",
                    out_dir=Path(temporary),
                    dpi=72,
                    slide_w=1800,
                    slide_h=1200,
                    mpp=0.5,
                    roi=(100, 200, 500, 600),
                    counts_scope="the selected public patches",
                    histoplus_repo_id="example/histoplus",
                    histoplus_revision="revision-123",
                    histoplus_magnification="20x",
                )

            for key in (
                "paper_figure_png",
                "paper_figure_pdf",
                "paper_figure_legend_txt",
                "celltype_counts_barplot_png",
                "celltype_counts_barplot_pdf",
            ):
                self.assertTrue(Path(outputs[key]).is_file(), key)
            with module.Image.open(outputs["paper_figure_png"]) as rendered_png:
                self.assertEqual(rendered_png.size, (518, 374))
            figure, axes = created[0]
            self.assertIsNone(figure._suptitle)
            self.assertTrue(all(axis.get_title() == "" for axis in axes.values()))
            panel_text = {
                item.get_text(): item
                for axis in axes.values()
                for item in axis.texts
                if item.get_text() in {"a", "b", "c"}
            }
            self.assertEqual(set(panel_text), {"a", "b", "c"})
            self.assertTrue(
                all(item.get_fontweight() == "bold" for item in panel_text.values())
            )
            self.assertEqual(len(figure.artists), 2)
            self.assertTrue(
                all(
                    isinstance(artist, module.ConnectionPatch)
                    for artist in figure.artists
                )
            )
            self.assertEqual(len(axes["overview"].patches), 2)
            self.assertEqual(len(axes["qc_inset"].patches), 2)
            for axis_name in ("overview", "qc_inset"):
                self.assertTrue(
                    any(
                        item.get_text().endswith((" um", " µm", " mm"))
                        for item in axes[axis_name].texts
                    )
                )
            statistics_text = {
                item.get_text() for item in axes["statistics"].texts
            }
            self.assertIn("7 (70.0%)", statistics_text)
            self.assertNotIn("CASE_001", statistics_text)

            legend = Path(outputs["paper_figure_legend_txt"]).read_text(
                encoding="utf-8"
            )
            for expected in (
                "Slide ID: CASE_001",
                "a, Cell-type counts",
                "b, Overview",
                "c, Enlarged QC inset",
                "Counts source: cell_types/class_counts.csv",
                "the selected public patches",
                "Scale and ROI:",
                "ROI coordinates in source pixels: x0=100, y0=200, x1=500, y1=600",
                "Model: LazySlide HistoPLUS 20x",
                "revision-123",
                "Research-use caveat:",
                "for research use only",
                module.PAPER_FIGURE_LAYOUT_VERSION,
            ):
                self.assertIn(expected, legend)



class ResumeSamplingTests(unittest.TestCase):
    def test_sampling_percent_must_match_exactly(self) -> None:
        self.assertFalse(module.summary_matches_requested_sampling(completed(100), requested(10)))
        self.assertFalse(module.summary_matches_requested_sampling(completed(10), requested(100)))
        self.assertTrue(module.summary_matches_requested_sampling(completed(10), requested(10)))

    def test_seed_must_match_for_sampled_runs(self) -> None:
        self.assertFalse(module.summary_matches_requested_sampling(completed(10, 7), requested(10, 8)))
        self.assertTrue(module.summary_matches_requested_sampling(completed(100, 7), requested(100, 8)))

    def test_legacy_summary_is_treated_as_full_slide(self) -> None:
        self.assertTrue(module.summary_matches_requested_sampling({}, requested(100)))
        self.assertFalse(module.summary_matches_requested_sampling({}, requested(10)))


    def test_exact_resume_signature_tracks_input_and_processing_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            slide = Path(temporary) / "slide.tif"
            slide.write_bytes(b"original")
            job = module.SlideJob("sample_1", Path("."), "slide", slide)
            args = requested(10, 7)
            payload = module.processing_signature_payload(job, args)
            self.assertNotIn("paper_figure_layout_version", payload)
            summary = {"processing_signature": module.processing_signature(job, args)}
            self.assertTrue(module.summary_matches_requested_run(summary, job, args))

            changed_args = requested(10, 7)
            changed_args.mpp = 0.75
            self.assertFalse(
                module.summary_matches_requested_run(summary, job, changed_args)
            )
            changed_slide_mpp = requested(10, 7)
            changed_slide_mpp.slide_mpp = 0.261780
            self.assertFalse(
                module.summary_matches_requested_run(summary, job, changed_slide_mpp)
            )
            slide.write_bytes(b"changed-and-longer")
            self.assertFalse(module.summary_matches_requested_run(summary, job, args))
            self.assertFalse(module.summary_matches_requested_run({}, job, args))

    def test_resume_requires_class_counts_and_all_core_exports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            args = requested(100)
            args.plain_csv = True
            write_core_outputs(output, counts=False)
            self.assertFalse(module.slide_has_required_plot_exports(output, args))
            (output / "cell_types/class_counts.csv").write_text("class_name,count\n", encoding="utf-8")
            self.assertTrue(module.slide_has_required_plot_exports(output, args))
            legend_path = output / "paper_figures/celltypes_paper_figure_legend.txt"
            legend_text = legend_path.read_text(encoding="utf-8")
            legend_path.unlink()
            self.assertFalse(module.slide_has_required_plot_exports(output, args))
            self.assertTrue(
                module.slide_has_required_plot_exports(
                    output, args, require_paper_figure_legend=False
                )
            )
            legend_path.write_text(legend_text, encoding="utf-8")
            self.assertTrue(module.slide_has_required_plot_exports(output, args))
            (output / "overlays/overview_with_zoom_box.png").write_bytes(b"")
            self.assertFalse(module.slide_has_required_plot_exports(output, args))

    def test_processing_signature_tracks_l2_revision_and_local_weight_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            slide = root / "slide_L0_rgb.tif"
            companion = root / "slide_L2_rgb.tif"
            slide.write_bytes(b"l0")
            companion.write_bytes(b"l2-v1")
            job = module.SlideJob("sample_1", Path("."), "slide", slide)
            args = requested(10)

            first = module.processing_signature(job, args)
            companion_stat = companion.stat()
            companion.write_bytes(b"l2-v2")
            os.utime(
                companion,
                ns=(companion_stat.st_atime_ns, companion_stat.st_mtime_ns),
            )
            self.assertNotEqual(first, module.processing_signature(job, args))

            args.histoplus_revision = "a" * 40
            changed_revision = module.processing_signature(job, args)
            args.histoplus_revision = "b" * 40
            self.assertNotEqual(changed_revision, module.processing_signature(job, args))

            weight = root / "model.pt"
            weight.write_bytes(b"aaaa")
            original_stat = weight.stat()
            args.histoplus_model_path = weight
            local_first = module.processing_signature(job, args)
            weight.write_bytes(b"bbbb")
            os.utime(weight, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            self.assertNotEqual(local_first, module.processing_signature(job, args))

    def test_unprovenanced_weight_cache_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            filename = module.expected_histoplus_weight_filename("20x")
            weight = cache / filename
            weight.write_bytes(b"weights")
            args = Namespace(
                histoplus_magnification="20x",
                histoplus_model_path=None,
                histoplus_repo_id="example/private-model",
                histoplus_revision="a" * 40,
                histoplus_cache_dir=cache,
            )
            self.assertIsNone(module.find_local_histoplus_weight(args, filename))
            identity = module.requested_histoplus_weight_identity(args)
            module.write_histoplus_weight_provenance(weight, identity)
            self.assertEqual(module.find_local_histoplus_weight(args, filename), weight.resolve())

            weight.write_bytes(b"tampered")
            self.assertIsNone(module.find_local_histoplus_weight(args, filename))

    def test_resolved_local_weight_identity_refreshes_after_same_metadata_edit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            weight = Path(temporary) / "model.pt"
            weight.write_bytes(b"first")
            args = Namespace(
                histoplus_magnification="20x",
                histoplus_model_path=weight,
                copy_histoplus_weight_to=None,
            )
            logger = logging.getLogger("resolved-local-weight-refresh-test")
            module.resolve_histoplus_weight_source(args, logger)
            first_sha = args._resolved_histoplus_weight_identity["resolved_file"]["sha256"]
            original_stat = weight.stat()

            weight.write_bytes(b"other")
            os.utime(weight, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            module.resolve_histoplus_weight_source(args, logger)
            refreshed = args._resolved_histoplus_weight_identity

            self.assertNotEqual(first_sha, refreshed["resolved_file"]["sha256"])
            self.assertEqual(
                refreshed["file"]["sha256"], refreshed["resolved_file"]["sha256"]
            )

    def test_huggingface_download_receives_immutable_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            weight = root / module.expected_histoplus_weight_filename("20x")
            weight.write_bytes(b"pinned-weight")
            revision = "c" * 40
            args = Namespace(
                histoplus_magnification="20x",
                histoplus_model_path=None,
                histoplus_repo_id="example/private-model",
                histoplus_revision=revision,
                histoplus_cache_dir=root / "empty-cache",
                histoplus_force_download=False,
                copy_histoplus_weight_to=None,
                hf_token=None,
                hf_token_file=None,
                hf_token_env="TEST_HF_TOKEN",
            )
            download = mock.Mock(return_value=str(weight))
            hub = types.ModuleType("huggingface_hub")
            hub.__path__ = []
            hub.hf_hub_download = download
            errors = types.ModuleType("huggingface_hub.errors")
            errors.GatedRepoError = type("GatedRepoError", (Exception,), {})

            with (
                mock.patch.object(module, "find_local_histoplus_weight", return_value=None),
                mock.patch.dict(
                    sys.modules,
                    {"huggingface_hub": hub, "huggingface_hub.errors": errors},
                ),
                mock.patch.dict(os.environ, {}, clear=True),
            ):
                resolved, _filename = module.resolve_histoplus_weight_source(
                    args, logging.getLogger("pinned-download-test")
                )

            self.assertEqual(resolved, weight.resolve())
            self.assertEqual(download.call_args.kwargs["revision"], revision)
            self.assertEqual(
                args._resolved_histoplus_weight_identity["revision"], revision
            )

    def test_streaming_coordinate_json_has_tamper_evident_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "coordinates.json"
            dataframe = module.pd.DataFrame(
                [
                    {
                        "cell_id": "cell-1",
                        "class_id": 2,
                        "class_name": "Lymphocytes",
                        "centroid_x": 1.5,
                        "centroid_y": 2.5,
                        "bbox_x0": 1.0,
                        "bbox_y0": 2.0,
                        "bbox_x1": 2.0,
                        "bbox_y1": 3.0,
                        "polygon_coords_json": "[[[1, 2], [2, 3]]]",
                    }
                ]
            )
            module.write_json_dump(dataframe, output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))[0]["cell_id"], "cell-1")
            self.assertTrue(module.valid_integrity_checked_artifact(output))
            with output.open("a", encoding="utf-8") as handle:
                handle.write("tamper")
            self.assertFalse(module.valid_integrity_checked_artifact(output))

    def test_requested_optional_outputs_and_retained_store_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            args = requested(100)
            args.plain_csv = True
            write_core_outputs(output)
            self.assertTrue(module.slide_has_required_plot_exports(output, args))

            args.export_qupath = True
            self.assertFalse(module.slide_has_required_plot_exports(output, args))
            (output / "cell_types/cell_types_qupath.json").write_text("[]", encoding="utf-8")
            module.write_artifact_integrity(output / "cell_types/cell_types_qupath.json")
            self.assertTrue(module.slide_has_required_plot_exports(output, args))

            args.save_geojson_like_json = True
            self.assertFalse(module.slide_has_required_plot_exports(output, args))
            (output / "cell_types/cell_type_coordinates.json").write_text("[]", encoding="utf-8")
            module.write_artifact_integrity(output / "cell_types/cell_type_coordinates.json")

            args.qc_patch_count = 1
            qc = output / "qc_patches"
            (qc / "patch_001").mkdir(parents=True)
            (qc / "patch_manifest.csv").write_text("patch_index\n1\n", encoding="utf-8")
            (qc / "patch_001/rgb.png").write_bytes(PNG_MAGIC + b"rgb")
            (qc / "patch_001/overlay.png").write_bytes(PNG_MAGIC + b"overlay")
            (qc / "patch_001/class_counts.csv").write_text("class_name,count\n", encoding="utf-8")
            (qc / "patch_001/metadata.json").write_text("{}", encoding="utf-8")
            self.assertTrue(module.slide_has_required_plot_exports(output, args))

            args.percent_slide = 10
            self.assertFalse(module.slide_has_required_plot_exports(output, args))
            sampled = output / "sampled_patches"
            (sampled / "patch_00001").mkdir(parents=True)
            (sampled / "patch_manifest.csv").write_text("patch_id\n1\n", encoding="utf-8")
            (sampled / "patch_summary.json").write_text(
                json.dumps({"n_sampled_patches": 1}), encoding="utf-8"
            )
            (sampled / "patch_00001/rgb.tif").write_bytes(b"tiff")
            (sampled / "patch_00001/rgb.png").write_bytes(PNG_MAGIC + b"sample")
            (sampled / "patch_00001/metadata.json").write_text("{}", encoding="utf-8")

            args.collage_grid = 2
            mosaic = output / "sampled_patch_mosaic"
            mosaic.mkdir()
            (mosaic / "patch_mosaic_mapping.csv").write_text("patch_id\n1\n", encoding="utf-8")
            (mosaic / "patch_mosaic_flat.tif").write_bytes(b"flat")
            (mosaic / "patch_mosaic_pyramidal.tif").write_bytes(b"pyramid")
            (mosaic / "patch_mosaic_summary.json").write_text(
                json.dumps({"processing_l0_path": "sampled_patch_mosaic/patch_mosaic_pyramidal.tif"}),
                encoding="utf-8",
            )

            args.keep_store = True
            job = module.SlideJob("sample_1", Path("."), "slide", output / "slide.tif")
            self.assertFalse(module.slide_has_required_plot_exports(output, args, job))
            store = module.expected_slide_store_path(args, output, job)
            store.mkdir(parents=True)
            (store / "zarr.json").write_text("{}", encoding="utf-8")
            self.assertTrue(module.slide_has_required_plot_exports(output, args, job))

    def test_corrupt_and_non_object_summaries_are_incomplete(self) -> None:
        logger = logging.getLogger("resume-summary-test")
        with tempfile.TemporaryDirectory() as temporary:
            summary_path = Path(temporary) / "summary.json"
            summary_path.write_text('{"processing_signature":', encoding="utf-8")
            self.assertIsNone(module.load_resume_summary(summary_path, logger))

            summary_path.write_text('["not", "an", "object"]', encoding="utf-8")
            self.assertIsNone(module.load_resume_summary(summary_path, logger))

            expected = {"processing_signature": "abc"}
            summary_path.write_text(json.dumps(expected), encoding="utf-8")
            self.assertEqual(module.load_resume_summary(summary_path, logger), expected)

    def test_stale_completion_marker_is_invalidated_before_rerun(self) -> None:
        logger = logging.getLogger("resume-invalidation-test")
        with tempfile.TemporaryDirectory() as temporary:
            summary_path = Path(temporary) / "summary" / "summary.json"
            summary_path.parent.mkdir(parents=True)
            summary_path.write_text('{"old": true}', encoding="utf-8")

            module.invalidate_completion_summary(summary_path, logger)

            self.assertFalse(summary_path.exists())

    def test_run_slide_invalidates_matching_marker_before_processing_failure(self) -> None:
        logger = logging.getLogger("resume-rerun-integration-test")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            slide = root / "slide.tif"
            slide.write_bytes(b"slide")
            output = root / "output"
            summary_path = output / "summary" / "summary.json"
            summary_path.parent.mkdir(parents=True)
            job = module.SlideJob("sample_1", Path("."), "slide", slide)
            args = requested(10)
            args.output = output
            args.overwrite = False
            args.resume = True
            args.dry_run = False
            summary_path.write_text(
                json.dumps({"processing_signature": module.processing_signature(job, args)}),
                encoding="utf-8",
            )

            with (
                mock.patch.object(module, "ensure_importable", return_value=(None, None, None, None)),
                mock.patch.object(
                    module,
                    "export_sampled_patch_report",
                    side_effect=RuntimeError("simulated processing failure"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "simulated processing failure"):
                    module.run_slide(job, args, logger)

            self.assertFalse(summary_path.exists())

    def test_atomic_summary_write_preserves_old_marker_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary_path = Path(temporary) / "summary.json"
            old_payload = {"processing_signature": "old"}
            summary_path.write_text(json.dumps(old_payload), encoding="utf-8")

            with mock.patch.object(module.json, "dump", side_effect=RuntimeError("interrupted")):
                with self.assertRaisesRegex(RuntimeError, "interrupted"):
                    module.write_json_atomic(summary_path, {"processing_signature": "new"})

            self.assertEqual(json.loads(summary_path.read_text(encoding="utf-8")), old_payload)
            self.assertEqual(list(summary_path.parent.glob(f".{summary_path.name}.*.tmp")), [])

            new_payload = {"processing_signature": "new"}
            module.write_json_atomic(summary_path, new_payload)
            self.assertEqual(json.loads(summary_path.read_text(encoding="utf-8")), new_payload)


if __name__ == "__main__":
    unittest.main()
