# Workflow parameters

`nextflow_schema.json` is the authoritative machine-readable contract. This
page describes all 54 public workflow parameters and the three fields reserved
for launcher plumbing or tests. The committed
[`examples/parameters.yml`](https://github.com/cfarkas/tumorquantai/blob/main/examples/parameters.yml) enumerates every
public key and deliberately starts in discovery-only mode.

In this reference, central processing unit (CPU) and graphics processing unit
(GPU) identify execution devices. L0 and L2 are image-pyramid levels, with
L0 the highest-resolution level. TIFF means Tagged Image File Format; CSV
means comma-separated values; JSON means JavaScript Object Notation.

Use the main command-line interface when possible. It validates the same
settings, supplies storage and provenance safeguards, and prints the expanded
workflow command. Direct `run.sh` and Nextflow remain available for established
automation.

## Use a parameter file

Copy the example to a reviewed location, set the input and output paths, and
change only values needed for the run:

~~~bash
cp examples/parameters.yml /mounted/storage/tumorquantai-parameters.yml

tumorquantai run /mounted/storage/slides \
  --output /mounted/storage/tumorquantai-results \
  --params-file /mounted/storage/tumorquantai-parameters.yml \
  --cpu
~~~

Explicit command-line options take precedence over the parameter file. Review
the printed command before inference. The example pairs the CPU container with
the CPU device and a conservative HistoPLUS batch size. Never place token
values in YAML; use a private token file or an authorized local HistoPLUS
weight.

For direct Nextflow use, select an appropriate profile and keep the work
directory on verified mounted storage:

~~~bash
nextflow run . \
  -params-file /mounted/storage/tumorquantai-parameters.yml \
  -profile docker_cpu \
  -work-dir /mounted/storage/tumorquantai-work
~~~

The defaults below come from the schema. Profiles and named presets can replace
some execution defaults; the final command and run manifest record the resolved
values.

## Input and sample selection

| Parameter | Main CLI | Type, constraint, and default | Meaning |
| --- | --- | --- | --- |
| `input_dir` | positional `INPUT` | path or null; default `null` | Root containing exported primary slides. Required for a run. |
| `output_dir` | `--output` | path or null; default `null` | Published result root. Required and distinct from the input root. |
| `sample_sheet` | `--sample-sheet` | path or null; default `null` | Optional CSV/TSV with `sample_id` and `slide_path`. |
| `slide_patterns` | repeat `--pattern` | string or non-empty list; default `*_L0_rgb.tif`, `*_L0_rgb.tiff` | Primary-slide glob or globs. |
| `include` | `--include` | string; default `*` | Include filter over inferred sample identifiers. |
| `exclude` | `--exclude` | string; default empty | Exclude filter over inferred sample identifiers. |
| `dry_run` | `--dry-run` | boolean; default `false` | Publish discovery manifests without HistoPLUS inference. |

## Container, resources, and failure handling

| Parameter | Main CLI | Type, constraint, and default | Meaning |
| --- | --- | --- | --- |
| `container_image` | `--container-image` | non-empty string; default is the pinned digest in the schema | Reviewed task container. Profiles may select the immutable CPU or GPU identity. |
| `docker_shm_size` | `--shm-size` | size string; default `2g` | Docker `/dev/shm` allocation for data-loader workers. |
| `cpus` | `--cpus` | integer ≥1; default `8` | CPU cores requested for each slide task. |
| `memory` | `--memory` | non-empty size string; default `32 GB` | Memory requested for each slide task. |
| `time` | `--time` | non-empty duration; default `120h` | Time limit for each slide task. |
| `max_retries` | `--max-retries` | integer ≥0; default `1` | Retry attempts after the first failed attempt. |
| `max_parallel_slides` | `--max-parallel-slides` | integer ≥1; default `1` | Maximum slide tasks running concurrently. Increase only after measuring resources. |
| `continue_on_error` | `--continue-on-error` / `--fail-fast` | boolean; default `true` | Continue the cohort after a slide exhausts retries, or stop immediately. |

## Sampling, scale, and tiling

| Parameter | Main CLI | Type, constraint, and default | Meaning |
| --- | --- | --- | --- |
| `mpp` | `--mpp`, `--target-mpp` | number >0; default `0.5` | Target micrometres per pixel used to form model tiles. |
| `slide_mpp` | `--source-mpp`, `--slide-mpp` | number >0 or null; default `null` | Verified physical MPP of source L0. Required when embedded metadata is absent or unreliable. |
| `tile_px` | `--tile-px` | integer ≥1; default `840` | Requested tile edge; the worker adjusts values that are not multiples of 14. |
| `overlap` | `--overlap` | number from 0 to 1; default `0.2` | Tile-overlap ratio. |
| `background_fraction` | `--background-fraction` | number from 0 to 1; default `0.95` | Maximum background fraction for a retained tile. |
| `percent_slide` | `--percent-slide` | number >0 and ≤100; default `100.0` | Percentage of detected tissue tiles processed. |
| `patch_random_seed` | `--seed`, `--patch-random-seed` | integer; default `20260709` | Seed for deterministic sampled-tile selection. |
| `max_sampled_patches` | `--max-sampled-patches` | integer ≥0; default `0` | Maximum sampled patches exported; zero means no cap. |
| `collage` | `--collage` | `NxN` string or null; default `null` | Optional square patch collage, for example `4x4`. |

Source MPP and target MPP are different quantities. A 1% or 10% result
describes only sampled tissue tiles; never extrapolate it by multiplying by
`100 / percent_slide`.

## Execution and HistoPLUS

| Parameter | Main CLI | Type, constraint, and default | Meaning |
| --- | --- | --- | --- |
| `device` | `--device` | `auto`, `cpu`, `gpu`, `cuda`, or `cuda:N`; schema default `cuda` | Worker inference device. Execution profiles normally resolve this setting. |
| `num_workers` | `--num-workers` | integer ≥0; default `2` | Data-loader worker processes in each slide task. |
| `run_cells_stage` | `--run-cells-stage` / `--no-run-cells-stage` | boolean; default `false` | Enable the optional cell-segmentation stage. |
| `cells_model` | `--cells-model` | non-empty string; default `instanseg` | Model name for optional cell segmentation. |
| `cells_batch_size` | `--cells-batch-size` | integer ≥1; default `4` | Batch size for optional cell segmentation. |
| `celltypes_batch_size` | `--celltypes-batch-size` | integer ≥1; default `2` | HistoPLUS typing batch size. |
| `histoplus_magnification` | `--histoplus-magnification` | `20x` or `40x`; default `20x` | HistoPLUS model magnification. |
| `histoplus_revision` | `--histoplus-revision` | 40 hexadecimal characters; pinned default `cde2eee81af9e39b03802fc33d4f284733b5ee5e` | Immutable reviewed HistoPLUS revision. |
| `histoplus_weight_file` | `--local-weight`, `--histoplus-weight-file` | path or null; default `null` | Existing authorized gated weight mounted read-only and never published. |
| `histoplus_cache_dir` | `--histoplus-cache-dir` | non-empty path; default `/home/lazyslide/.cache/histoplus` | Weight-cache path inside the task environment. |
| `amp` | `--amp` / `--no-amp` | boolean; default `false` | Enable automatic mixed precision. |

Keep the pinned model revision and container identities unchanged unless a
separately reviewed reproducibility change requires a new result root and
regression evidence.

## Pyramidal TIFF conversion

| Parameter | Main CLI | Type, constraint, and default | Meaning |
| --- | --- | --- | --- |
| `convert_to_pyramidal` | `--convert-to-pyramidal` / `--no-convert-to-pyramidal` | boolean; default `true` | Convert non-pyramidal inputs before inference. |
| `pyramidal_tile` | `--pyramidal-tile` | integer ≥1; default `512` | Pyramidal BigTIFF tile edge. |
| `pyramidal_compression` | `--pyramidal-compression` | `none`, `lzw`, `deflate`, `zstd`, or `jpeg`; default `lzw` | Pyramidal BigTIFF compression. |
| `pyramidal_jpeg_q` | `--pyramidal-jpeg-q` | integer 1–100; default `90` | JPEG quality when pyramidal compression is JPEG. |

## Overlays, exports, and aggregation

| Parameter | Main CLI | Type, constraint, and default | Meaning |
| --- | --- | --- | --- |
| `zoom_size` | `--zoom-size` | integer ≥1; default `2000` | Automatic zoom-window edge in level-0 pixels. |
| `overlay_alpha` | `--overlay-alpha` | number from 0 to 1; default `0.35` | Opacity for filled cell-type polygons. |
| `overlay_style` | `--overlay-style` | `filled`, `outline`, `centroid`, `outline_centroid`, `filled_outline`, or `filled-outline`; default `outline_centroid` | Cell-type overlay style. |
| `overlay_outline_width` | `--overlay-outline-width` | integer ≥1; default `2` | Color-outline width in pixels. |
| `overlay_halo_width` | `--overlay-halo-width` | integer ≥0; default `4` | Black-halo width in pixels. |
| `overlay_draw_order` | `--overlay-draw-order` | `input`, `small-last`, or `large-last`; default `small-last` | Polygon drawing order. |
| `cell_marker_radius` | `--cell-marker-radius` | integer ≥0; default `3` | Centroid-marker radius; zero disables markers. |
| `figure_dpi` | `--figure-dpi` | integer ≥1; default `300` | Raster figure resolution in dots per inch. |
| `qc_patch_count` | `--qc-patch-count` | integer ≥0; default `0` | Dense quality-control patch overlays per slide. |
| `qc_patch_size` | `--qc-patch-size` | integer ≥1; default `1024` | Quality-control patch edge in level-0 pixels. |
| `plain_csv` | `--plain-csv` / `--compressed-coordinates` | boolean; default `true` | Write plain coordinate CSV rather than gzip-compressed CSV. |
| `export_qupath` | `--export-qupath` / `--no-export-qupath` | boolean; default `false` | Write QuPath-compatible annotations. |
| `save_json` | `--save-json` / `--no-save-json` | boolean; default `false` | Write the optional per-cell JSON export. |
| `log_level` | `--log-level` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`; default `INFO` | Worker log verbosity. |
| `allow_mixed_sampling` | `--allow-mixed-sampling` / `--no-allow-mixed-sampling` | boolean; default `false` | Permit aggregation across different sampling percentages or seeds. |

Leave mixed-sampling aggregation disabled for ordinary runs. A failed or
incomplete sample remains excluded from numeric matrices and must never be
converted to a biological zero.

## Internal classifications

These three schema fields are intentionally not public parameters and are
omitted from `examples/parameters.yml`:

| Internal parameter | Classification | Why it is internal |
| --- | --- | --- |
| `worker_script` | Executable-code override | Retained for workflow tests and compatible direct automation. The main CLI must not accept an arbitrary worker. |
| `docker_run_options` | Trusted launcher plumbing | Constructed by `run.sh` from validated bind mounts and environment settings. Unreviewed text could inject Docker options. |
| `histoplus_weight_sha256` | Computed provenance identity | Calculated from an authorized local weight by `run.sh`; user input could falsify model provenance. |

Do not add these keys to a public parameter file. Preserve per-slide isolation,
resume behavior, source fingerprints, deterministic sampling, and explicit
included/failed/incomplete/excluded/pending sample states.
