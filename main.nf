nextflow.enable.dsl = 2


def shellQuote(value) {
    if (value == null) return "''"
    return "'" + value.toString().replace("'", "'\"'\"'") + "'"
}


def enabled(value) {
    if (value instanceof Boolean) return value
    return value != null && value.toString().toLowerCase() in ['true', '1', 'yes', 'on']
}


def option(name, value) {
    return value == null || value.toString() == '' ? '' : "${name} ${shellQuote(value)}"
}


def flag(name, value) {
    return enabled(value) ? name : ''
}


process DISCOVER_SLIDES {
    tag 'discover primary slides'
    cache false

    container params.container_image
    cpus 1
    memory '1 GB'
    time '1h'

    publishDir "${params.output_dir}/workflow_metadata", mode: 'copy', overwrite: true

    input:
    path discover_script
    val l2_policy

    output:
    path 'slides.tsv', emit: manifest
    path 'slides.json', emit: manifest_json

    script:
    def patterns = params.slide_patterns instanceof Collection
        ? params.slide_patterns
        : params.slide_patterns.toString().split(',').collect { it.trim() }.findAll { it }
    def patternArgs = patterns.collect { "--pattern ${shellQuote(it)}" }.join(' ')
    def sampleSheet = option('--sample-sheet', params.sample_sheet)
    """
    set -Eeuo pipefail
    python ${discover_script} \
      --input-root ${shellQuote(params.input_dir)} \
      --output slides.tsv \
      --json slides.json \
      --include ${shellQuote(params.include)} \
      --exclude ${shellQuote(params.exclude)} \
      --exclude-root ${shellQuote(params.output_dir)} \
      --l2-policy ${shellQuote(l2_policy)} \
      ${patternArgs} \
      ${sampleSheet}
    """
}


process PROCESS_SLIDE {
    tag { sample_id }

    container params.container_image
    cpus { params.cpus as int }
    memory { params.memory }
    time { params.time }
    maxRetries { params.max_retries as int }
    maxForks params.max_parallel_slides as int
    errorStrategy {
        task.attempt <= (params.max_retries as int)
            ? 'retry'
            : (enabled(params.continue_on_error) ? 'ignore' : 'terminate')
    }

    publishDir params.output_dir, mode: 'copy', overwrite: true

    input:
    tuple val(sample_id), path(cache_identity_inputs), val(slide_path), val(input_fingerprint), val(l2_path), val(l2_fingerprint), val(model_identity)
    path worker_script, name: "workflow_bin/worker.py"

    output:
    tuple val(sample_id), path("${sample_id}"), emit: results

    script:
    def cli = [
        option('--slide-id', sample_id),
        option('--mpp', params.mpp),
        option('--slide-mpp', params.slide_mpp),
        option('--tile-px', params.tile_px),
        option('--overlap', params.overlap),
        option('--background-fraction', params.background_fraction),
        option('--percent-slide', params.percent_slide),
        option('--patch-random-seed', params.patch_random_seed),
        option('--max-sampled-patches', params.max_sampled_patches),
        option('--collage', params.collage),
        option('--device', params.device),
        option('--num-workers', params.num_workers),
        option('--cells-model', params.cells_model),
        option('--cells-batch-size', params.cells_batch_size),
        option('--celltypes-batch-size', params.celltypes_batch_size),
        option('--histoplus-magnification', params.histoplus_magnification),
        option('--histoplus-repo-id', 'Owkin-Bioptimus/histoplus'),
        option('--histoplus-revision', params.histoplus_revision),
        option('--histoplus-weight-file', params.histoplus_weight_file),
        option('--histoplus-cache-dir', params.histoplus_cache_dir),
        option('--zoom-size', params.zoom_size),
        option('--overlay-alpha', params.overlay_alpha),
        option('--overlay-style', params.overlay_style),
        option('--overlay-outline-width', params.overlay_outline_width),
        option('--overlay-halo-width', params.overlay_halo_width),
        option('--overlay-draw-order', params.overlay_draw_order),
        option('--cell-marker-radius', params.cell_marker_radius),
        option('--figure-dpi', params.figure_dpi),
        option('--qc-patch-count', params.qc_patch_count),
        option('--qc-patch-size', params.qc_patch_size),
        flag('--convert-to-pyramidal', params.convert_to_pyramidal),
        option('--pyramidal-tile', params.pyramidal_tile),
        option('--pyramidal-compression', params.pyramidal_compression),
        option('--pyramidal-jpeg-q', params.pyramidal_jpeg_q),
        flag('--run-cells-stage', params.run_cells_stage),
        flag('--amp', params.amp),
        flag('--plain-csv', params.plain_csv),
        flag('--export-qupath', params.export_qupath),
        flag('--save-geojson-like-json', params.save_json),
        option('--log-level', params.log_level)
    ].findAll { it }.join(' \\\n      ')

    """
    set -Eeuo pipefail
    printf 'sample_id=%s input_fingerprint=%s l2_path=%s l2_fingerprint=%s model_identity=%s\n' \
      ${shellQuote(sample_id)} \
      ${shellQuote(input_fingerprint)} \
      ${shellQuote(l2_path)} \
      ${shellQuote(l2_fingerprint)} \
      ${shellQuote(model_identity)}
    python ${worker_script} \
      --input-slide ${shellQuote(slide_path)} \
      --output ${shellQuote(sample_id)} \
      ${cli}

    test -s ${shellQuote(sample_id)}/summary/summary.json
    test -s ${shellQuote(sample_id)}/cell_types/class_counts.csv
    """
}


process AGGREGATE_COUNTS {
    tag 'aggregate cohort cell types'

    container params.container_image
    cpus 1
    memory '4 GB'
    time '1h'

    publishDir params.output_dir, mode: 'copy', overwrite: true

    input:
    path discovery_manifest
    path result_dirs
    path workflow_manifest_script, name: "workflow_bin/build_workflow_manifest.py"
    path aggregate_script, name: "workflow_bin/aggregate_histoplus_celltypes.py"

    output:
    path 'aggregated_celltypes', emit: matrices
    path 'workflow_aggregation_manifest.csv', emit: audit_manifest

    script:
    def expectedPercent = option('--expected-percent-slide', params.percent_slide)
    def allowMixed = flag('--allow-mixed-sampling', params.allow_mixed_sampling)
    """
    set -Eeuo pipefail
    python ${workflow_manifest_script} \
      --discovery ${discovery_manifest} \
      --results-root . \
      --output workflow_aggregation_manifest.csv

    python ${aggregate_script} \
      --input-root . \
      --manifest workflow_aggregation_manifest.csv \
      --output-dir aggregated_celltypes \
      ${expectedPercent} \
      ${allowMixed}
    """
}


workflow {
    def percentSlide
    try {
        percentSlide = new BigDecimal(params.percent_slide.toString())
    } catch (Exception ignored) {
        error "percent_slide must be numeric in the interval (0, 100]"
    }
    if (percentSlide <= 0 || percentSlide > 100) {
        error "percent_slide must be numeric in the interval (0, 100]"
    }

    def histoplusRevision = params.histoplus_revision?.toString()
    if (histoplusRevision == null || !(histoplusRevision ==~ /[0-9a-fA-F]{40}/)) {
        error "histoplus_revision must be an immutable full 40-hex commit SHA"
    }

    def collageEnabled = params.collage != null && params.collage.toString().trim()
    def usesL2 = collageEnabled || percentSlide < 100
    def l2Policy = usesL2 ? 'required' : 'ignore'
    def histoplusRepo = 'Owkin-Bioptimus/histoplus'
    def localWeightFile = params.histoplus_weight_file?.toString()?.trim()
    def localWeightSha256 = params.histoplus_weight_sha256?.toString()?.trim()?.toLowerCase()
    if (localWeightFile && (localWeightSha256 == null || !(localWeightSha256 ==~ /[0-9a-f]{64}/))) {
        error "histoplus_weight_sha256 must be the 64-hex content identity computed by run.sh"
    }
    if (!localWeightFile && localWeightSha256) {
        error "histoplus_weight_sha256 requires histoplus_weight_file"
    }
    def histoplusFilename = "histoplus_cellvit_segmentor_${params.histoplus_magnification}.pt"
    def modelIdentityParts = [
        "repo=${histoplusRepo}",
        "revision=${histoplusRevision}",
        "filename=${histoplusFilename}",
        "magnification=${params.histoplus_magnification}"
    ]
    if (localWeightFile) {
        modelIdentityParts << "local_weight_sha256=${localWeightSha256}"
    }
    def modelIdentity = modelIdentityParts.join(';')

    discovered = DISCOVER_SLIDES(
        file("${projectDir}/bin/discover_slides.py"),
        l2Policy
    )

    if (!enabled(params.dry_run)) {
        slide_jobs = discovered.manifest
            .splitCsv(header: true, sep: '\t')
            .map { row ->
                def cacheIdentityInputs = [file(row.slide_path)]
                if (localWeightFile) {
                    cacheIdentityInputs << file(localWeightFile, checkIfExists: true)
                }
                if (usesL2) {
                    if (row.l2_fingerprint == null || !row.l2_fingerprint.startsWith('sha256:')) {
                        error "Required companion L2 fingerprint is missing for sample ${row.sample_id}"
                    }
                    cacheIdentityInputs << file(row.l2_path)
                }
                tuple(
                    row.sample_id,
                    cacheIdentityInputs,
                    row.slide_path,
                    row.fingerprint,
                    row.l2_path ?: 'not_used',
                    row.l2_fingerprint,
                    modelIdentity
                )
            }

        processed = PROCESS_SLIDE(
            slide_jobs,
            file(params.worker_script ?: "${projectDir}/lazyslide_histoplus_wsi_celltype.py")
        )

        result_dirs = processed.results
            .map { sample_id, result_dir -> result_dir }
            .mix(discovered.manifest_json)
            .collect()

        AGGREGATE_COUNTS(
            discovered.manifest,
            result_dirs,
            file("${projectDir}/bin/build_workflow_manifest.py"),
            file("${projectDir}/bin/aggregate_histoplus_celltypes.py")
        )
    }
}
