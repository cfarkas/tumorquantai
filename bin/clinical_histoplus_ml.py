#!/usr/bin/env python3
"""Privacy-aware exploratory clinical + HistoPLUS classification.

The tool links a clinical workbook to validated HistoPLUS count/fraction
matrices, writes a linkage audit and merged analysis table, produces outcome
stratification, and compares prespecified clinical, HistoPLUS, and combined
feature sets with repeated nested cross-validation.

This is an association/classification workflow. A current vital-status field is
not a survival endpoint unless every subject has a common prediction origin,
fixed follow-up horizon, and complete censoring/last-contact information.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
from scipy.stats import chi2_contingency, fisher_exact, mannwhitneyu
import sklearn
from sklearn.calibration import calibration_curve
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import PCA
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    precision_score,
    precision_recall_curve,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import GridSearchCV, StratifiedGroupKFold, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


SCHEMA_VERSION = "clinical_histoplus_ml_v1"
FEATURE_SET_ORDER = (
    "clinical",
    "histoplus_fractions",
    "histoplus_log_counts",
    "combined_fractions",
)
METRIC_NAMES = (
    "roc_auc",
    "average_precision",
    "balanced_accuracy",
    "sensitivity",
    "specificity",
    "precision",
    "npv",
    "f1",
    "mcc",
    "brier",
)
INCREMENTAL_VALUE_COLUMNS = (
    "model",
    "candidate_feature_set",
    "reference_feature_set",
    "metric",
    "improvement_point_estimate",
    "bootstrap_ci_low",
    "bootstrap_ci_high",
    "direction",
)


class AnalysisError(RuntimeError):
    """Raised when an input or design choice would invalidate the analysis."""


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value)).strip())


def normalize_label(value: Any) -> str:
    return normalize_text(value).casefold()


def normalize_slide_id(value: Any) -> str:
    """Normalize separators and known technical suffixes without dropping specimen tokens."""

    text = unicodedata.normalize("NFKC", str(value)).strip().upper()
    text = re.sub(r"\.(TIF|TIFF|SVS)$", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(?:[ _-]+L0[ _-]*RGB)?[ _-]+HE[ _-]*1$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"[-_\s]+", "-", text).strip("-")
    if not text:
        raise AnalysisError(f"Could not normalize an empty sample ID from {value!r}")
    return text


def feature_slug(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
    return text or "FEATURE"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def parse_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None or pd.isna(value):
        raise AnalysisError(f"Missing boolean value for {field}")
    normalized = normalize_label(value)
    if normalized in {"true", "1", "yes", "y", "si", "sí"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise AnalysisError(f"Invalid boolean value for {field}: {value!r}")


def parse_csv_list(value: str | None, allowed: Iterable[str]) -> list[str]:
    allowed_set = set(allowed)
    selected = [part.strip() for part in str(value or "").split(",") if part.strip()]
    unknown = sorted(set(selected).difference(allowed_set))
    if unknown:
        raise AnalysisError("Unknown selection(s): " + ", ".join(unknown))
    if not selected:
        raise AnalysisError("At least one selection is required")
    return selected


def clinical_feature_type_map(
    clinical_features: list[str],
    numeric_features: list[str],
    categorical_features: list[str],
) -> dict[str, str]:
    for option_name, values in (
        ("--clinical-feature", clinical_features),
        ("--numeric-clinical-feature", numeric_features),
        ("--categorical-clinical-feature", categorical_features),
    ):
        duplicates = sorted(name for name, count in Counter(values).items() if count > 1)
        if duplicates:
            raise AnalysisError(
                f"{option_name} contains duplicate column(s): " + ", ".join(duplicates)
            )
    numeric = set(numeric_features)
    categorical = set(categorical_features)
    typed_twice = sorted(numeric.intersection(categorical))
    if typed_twice:
        raise AnalysisError(
            "Clinical predictors cannot be both numeric and categorical: "
            + ", ".join(typed_twice)
        )
    declared = set(clinical_features)
    unknown_typed = sorted((numeric | categorical) - declared)
    if unknown_typed:
        raise AnalysisError(
            "Typed clinical columns must also be supplied with --clinical-feature: "
            + ", ".join(unknown_typed)
        )
    untyped = sorted(declared - numeric - categorical)
    if untyped:
        raise AnalysisError(
            "Every --clinical-feature requires exactly one explicit type; add "
            "--numeric-clinical-feature or --categorical-clinical-feature for: "
            + ", ".join(untyped)
        )
    output = {column: "numeric" for column in numeric}
    output.update({column: "categorical" for column in categorical})
    return output


def read_clinical_workbook(path: Path, sheet: str | None) -> tuple[pd.DataFrame, str]:
    try:
        excel = pd.ExcelFile(path)
    except ImportError as exc:
        raise AnalysisError(
            "Reading XLSX requires openpyxl. Install requirements.txt or run the container built from this repository."
        ) from exc
    except Exception as exc:
        raise AnalysisError(f"Could not open clinical workbook {path}: {exc}") from exc
    selected_sheet = sheet or excel.sheet_names[0]
    if selected_sheet not in excel.sheet_names:
        raise AnalysisError(
            f"Clinical sheet {selected_sheet!r} not found; available: {excel.sheet_names}"
        )
    table = pd.read_excel(path, sheet_name=selected_sheet)
    excel.close()
    table.columns = [normalize_text(column) for column in table.columns]
    table = table.dropna(how="all").reset_index(drop=True)
    if table.columns.duplicated().any():
        duplicated = table.columns[table.columns.duplicated()].tolist()
        raise AnalysisError("Duplicate clinical column names: " + ", ".join(duplicated))
    return table, selected_sheet


def read_histoplus_matrix(path: Path, prefix: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        matrix = pd.read_csv(path)
    except Exception as exc:
        raise AnalysisError(f"Could not read HistoPLUS matrix {path}: {exc}") from exc
    required = {"class_id", "cell_type"}
    missing = sorted(required.difference(matrix.columns))
    if missing:
        raise AnalysisError(f"HistoPLUS matrix {path} lacks: {', '.join(missing)}")
    if matrix.duplicated(["class_id", "cell_type"]).any():
        raise AnalysisError(f"HistoPLUS matrix {path} contains duplicate cell-type rows")
    sample_columns = [column for column in matrix.columns if column not in required]
    if not sample_columns:
        raise AnalysisError(f"HistoPLUS matrix {path} has no sample columns")
    numeric = matrix.loc[:, sample_columns].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or (numeric < 0).any().any():
        raise AnalysisError(f"HistoPLUS matrix {path} contains missing, nonnumeric, or negative values")
    metadata = matrix.loc[:, ["class_id", "cell_type"]].copy()
    names: list[str] = []
    for row in metadata.itertuples(index=False):
        try:
            class_id = int(row.class_id)
        except (TypeError, ValueError) as exc:
            raise AnalysisError(f"Invalid class_id in {path}: {row.class_id!r}") from exc
        names.append(f"{prefix}__{class_id}__{feature_slug(row.cell_type)}")
    values = numeric.T
    values.index = values.index.astype(str)
    values.index.name = "sample_id"
    values.columns = names
    return values, metadata


def validate_histoplus_inputs(
    counts: pd.DataFrame,
    fractions: pd.DataFrame,
    count_meta: pd.DataFrame,
    fraction_meta: pd.DataFrame,
) -> None:
    if counts.index.tolist() != fractions.index.tolist():
        raise AnalysisError("Count and fraction matrices have different sample columns or ordering")
    left = count_meta.astype(str).reset_index(drop=True)
    right = fraction_meta.astype(str).reset_index(drop=True)
    if not left.equals(right):
        raise AnalysisError("Count and fraction matrices have different class mappings")
    totals = fractions.sum(axis=1)
    invalid = ~np.isclose(totals.to_numpy(), 1.0, atol=1e-6) & ~np.isclose(
        totals.to_numpy(), 0.0, atol=1e-12
    )
    if invalid.any():
        raise AnalysisError("Fraction-matrix sample columns must sum to 1 or to 0 for verified zero detections")
    count_values = counts.to_numpy(dtype=float)
    count_totals = count_values.sum(axis=1, keepdims=True)
    expected = np.divide(
        count_values,
        count_totals,
        out=np.zeros_like(count_values, dtype=float),
        where=count_totals != 0,
    )
    observed = fractions.to_numpy(dtype=float)
    if not np.allclose(observed, expected, rtol=1e-7, atol=1e-8):
        maximum_difference = float(np.max(np.abs(observed - expected)))
        raise AnalysisError(
            "Fraction matrix does not equal counts divided by each sample total; "
            f"maximum absolute difference={maximum_difference:.6g}. Verify that both "
            "matrices came from the same aggregation run."
        )


def benjamini_hochberg(p_values: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=p_values.index, dtype=float)
    valid = p_values.dropna().astype(float).sort_values()
    if valid.empty:
        return result
    m = len(valid)
    adjusted = np.empty(m, dtype=float)
    running = 1.0
    for reverse_index in range(m - 1, -1, -1):
        rank = reverse_index + 1
        running = min(running, float(valid.iloc[reverse_index]) * m / rank)
        adjusted[reverse_index] = running
    result.loc[valid.index] = np.clip(adjusted, 0.0, 1.0)
    return result


def clean_categorical(series: pd.Series, column_name: str) -> pd.Series:
    cleaned = series.map(lambda value: np.nan if pd.isna(value) else normalize_label(value))
    cleaned = cleaned.replace({"": np.nan, "nan": np.nan, "none": np.nan})
    normalized_name = feature_slug(column_name)
    if normalized_name in {"SEXO", "SEX", "GENDER"}:
        sex_map = {
            "f": "female",
            "female": "female",
            "femenino": "female",
            "mujer": "female",
            "m": "male",
            "male": "male",
            "masculino": "male",
            "hombre": "male",
        }
        cleaned = cleaned.map(lambda value: sex_map.get(value, value) if pd.notna(value) else value)
    return cleaned.astype("object").where(cleaned.notna(), np.nan)


def prepare_clinical_features(
    clinical: pd.DataFrame,
    columns: list[str],
    feature_types: dict[str, str],
    max_categorical_levels: int,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Prepare predictors using prespecified types, never cohort-wide type inference."""

    output = pd.DataFrame(index=clinical.index)
    manifest: list[dict[str, Any]] = []
    seen: Counter[str] = Counter()
    for source_column in columns:
        source = clinical[source_column]
        nonmissing = source.notna() & source.astype(str).str.strip().ne("")
        base_name = f"CLIN__{feature_slug(source_column)}"
        seen[base_name] += 1
        feature_name = base_name if seen[base_name] == 1 else f"{base_name}__{seen[base_name]}"
        variable_type = feature_types[source_column]
        if variable_type == "numeric":
            numeric = pd.to_numeric(source.where(nonmissing), errors="coerce")
            invalid = nonmissing & numeric.isna()
            if invalid.any():
                raise AnalysisError(
                    f"Clinical feature {source_column!r} was declared numeric but contains "
                    f"{int(invalid.sum())} nonnumeric nonmissing value(s)"
                )
            output[feature_name] = numeric.astype(float)
            levels = None
        elif variable_type == "categorical":
            categorical = clean_categorical(source, source_column)
            level_count = int(categorical.nunique(dropna=True))
            if level_count > max_categorical_levels:
                raise AnalysisError(
                    f"Clinical feature {source_column!r} has {level_count} categories; "
                    f"the limit is {max_categorical_levels}. Coarsen it explicitly before modeling."
                )
            output[feature_name] = categorical
            levels = level_count
        else:
            raise AnalysisError(
                f"Internal error: unsupported clinical type {variable_type!r} for {source_column!r}"
            )
        manifest.append(
            {
                "feature_name": feature_name,
                "source": "clinical",
                "source_column": source_column,
                "cell_type": "",
                "class_id": "",
                "transformation": variable_type,
                "n_levels": levels,
            }
        )
    return output, manifest


def clr_transform(fractions: pd.DataFrame, pseudocount: float) -> pd.DataFrame:
    if pseudocount <= 0:
        raise AnalysisError("--clr-pseudocount must be > 0")
    values = fractions.to_numpy(dtype=float)
    zero_rows = np.isclose(values.sum(axis=1), 0.0)
    logged = np.log(values + pseudocount)
    clr = logged - logged.mean(axis=1, keepdims=True)
    clr[zero_rows, :] = 0.0
    columns = [column.replace("HISTO_FRACTION__", "HISTO_CLR__", 1) for column in fractions.columns]
    return pd.DataFrame(clr, index=fractions.index, columns=columns)


def build_linkage(
    clinical: pd.DataFrame,
    sample_id_column: str,
    outcome_column: str,
    positive_label: str,
    negative_label: str,
    matrix_samples: list[str],
    audit: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    clinical = clinical.copy()
    clinical["_join_key"] = clinical[sample_id_column].map(normalize_slide_id)
    duplicates = clinical.loc[clinical["_join_key"].duplicated(keep=False), "_join_key"]
    if not duplicates.empty:
        raise AnalysisError("Clinical sample IDs are not unique after safe normalization")

    matrix_roster = pd.DataFrame({"sample_id": matrix_samples})
    matrix_roster["_join_key"] = matrix_roster["sample_id"].map(normalize_slide_id)
    if matrix_roster["_join_key"].duplicated().any():
        raise AnalysisError("HistoPLUS sample IDs are not unique after safe normalization")

    if "slide_id" not in audit.columns or "included" not in audit.columns:
        raise AnalysisError("Aggregation audit must contain slide_id and included columns")
    audit = audit.copy()
    audit["_slide_join_key"] = audit["slide_id"].map(normalize_slide_id)
    if audit["_slide_join_key"].duplicated().any():
        raise AnalysisError("Aggregation audit slide IDs are not unique after safe normalization")
    if "sample_id" in audit.columns:
        audit_link_ids = audit["sample_id"].where(
            audit["sample_id"].notna() & audit["sample_id"].astype(str).str.strip().ne(""),
            audit["slide_id"],
        )
    else:
        audit_link_ids = audit["slide_id"]
    audit["_join_key"] = audit_link_ids.map(normalize_slide_id)
    audit["_completed"] = [
        parse_bool(value, field=f"aggregation_audit.included row {index + 2}")
        for index, value in enumerate(audit["included"])
    ]
    mixed_pool_status = audit.groupby("_join_key")["_completed"].nunique()
    mixed_pool_status = mixed_pool_status[mixed_pool_status > 1]
    if not mixed_pool_status.empty:
        raise AnalysisError(
            "Aggregation audit maps both included and excluded slides to the same pooled "
            "sample_id after normalization. Regenerate the aggregation audit/sample map "
            "so each pooled matrix sample has an unambiguous completion status."
        )
    audit_samples = audit.groupby("_join_key", sort=False).agg(
        _completed=("_completed", "first"),
        aggregation_slide_count=("slide_id", "size"),
    )

    positive = normalize_label(positive_label)
    negative = normalize_label(negative_label)
    if positive == negative:
        raise AnalysisError("Positive and negative labels normalize to the same value")
    clinical["_outcome_normalized"] = clinical[outcome_column].map(
        lambda value: "" if pd.isna(value) else normalize_label(value)
    )
    clinical["outcome_binary"] = clinical["_outcome_normalized"].map(
        {negative: 0, positive: 1}
    )

    clinical_by_key = clinical.set_index("_join_key", drop=False)
    matrix_by_key = matrix_roster.set_index("_join_key", drop=False)
    all_keys = sorted(
        set(clinical_by_key.index) | set(matrix_by_key.index) | set(audit_samples.index)
    )
    rows: list[dict[str, Any]] = []
    for key in all_keys:
        in_clinical = key in clinical_by_key.index
        in_histoplus = key in matrix_by_key.index
        in_audit = key in audit_samples.index
        completed = bool(audit_samples.at[key, "_completed"]) if in_audit else False
        aggregation_slide_count = (
            int(audit_samples.at[key, "aggregation_slide_count"]) if in_audit else 0
        )
        outcome_valid = bool(
            in_clinical and pd.notna(clinical_by_key.at[key, "outcome_binary"])
        )
        included = in_clinical and in_histoplus and completed and outcome_valid
        reasons: list[str] = []
        if not in_clinical:
            reasons.append("missing_clinical_row")
        if not in_histoplus:
            reasons.append("missing_histoplus_matrix_column")
        if not in_audit:
            reasons.append("missing_aggregation_audit_row")
        elif not completed:
            reasons.append("slide_not_completed")
        if in_clinical and not outcome_valid:
            reasons.append("missing_or_unmapped_outcome")
        display_id = (
            str(matrix_by_key.at[key, "sample_id"])
            if in_histoplus
            else str(clinical_by_key.at[key, sample_id_column])
            if in_clinical
            else key
        )
        rows.append(
            {
                "sample_id": display_id,
                "join_key": key,
                "in_clinical": in_clinical,
                "in_histoplus": in_histoplus,
                "in_aggregation_audit": in_audit,
                "slide_completed": completed,
                "aggregation_slide_count": aggregation_slide_count,
                "pooled_slides": bool(aggregation_slide_count > 1),
                "outcome_valid": outcome_valid,
                "analysis_included": included,
                "exclusion_reason": ";".join(reasons),
            }
        )
    linkage = pd.DataFrame(rows)
    matrix_failures = linkage.loc[linkage["in_histoplus"] & ~linkage["analysis_included"]]
    if not matrix_failures.empty:
        counts = Counter(
            reason
            for value in matrix_failures["exclusion_reason"]
            for reason in str(value).split(";")
            if reason
        )
        raise AnalysisError(
            "One or more HistoPLUS matrix samples cannot enter analysis: "
            + ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        )
    eligible_keys = linkage.loc[linkage["analysis_included"], "join_key"].tolist()
    eligible = clinical_by_key.loc[eligible_keys].copy()
    sample_map = matrix_by_key.loc[eligible_keys, "sample_id"].astype(str).to_dict()
    eligible.index = [sample_map[key] for key in eligible_keys]
    eligible.index.name = "analysis_id"
    outcome_counts = {
        "negative": int((eligible["outcome_binary"] == 0).sum()),
        "positive": int((eligible["outcome_binary"] == 1).sum()),
    }
    return linkage, eligible, outcome_counts


def build_all_clinical_roster(
    clinical: pd.DataFrame,
    sample_id_column: str,
    linkage: pd.DataFrame,
    counts: pd.DataFrame,
    fractions: pd.DataFrame,
) -> pd.DataFrame:
    """Augment every clinical row; unavailable HistoPLUS values remain missing."""

    clinical_output = clinical.copy().reset_index(drop=True)
    clinical_keys = clinical_output[sample_id_column].map(normalize_slide_id)
    linkage_by_key = linkage.set_index("join_key")
    linkage_columns = [
        "in_histoplus",
        "in_aggregation_audit",
        "slide_completed",
        "aggregation_slide_count",
        "pooled_slides",
        "outcome_valid",
        "analysis_included",
        "exclusion_reason",
    ]
    linkage_flags = linkage_by_key.reindex(clinical_keys)[linkage_columns].reset_index(drop=True)
    linkage_flags.columns = [f"LINKAGE__{column}" for column in linkage_flags.columns]

    matrix_ids = counts.index.astype(str)
    matrix_keys = pd.Index([normalize_slide_id(value) for value in matrix_ids])
    if matrix_keys.duplicated().any():
        raise AnalysisError("HistoPLUS matrix IDs collide after normalization in all-roster merge")
    matrix_sample_ids = pd.Series(matrix_ids, index=matrix_keys, dtype="object")
    linked_matrix_ids = matrix_sample_ids.reindex(clinical_keys).reset_index(drop=True)
    linked_matrix_ids.name = "LINKAGE__matrix_sample_id"
    quantitative = pd.concat([counts, fractions], axis=1).copy()
    quantitative.index = matrix_keys
    quantitative = quantitative.reindex(clinical_keys).reset_index(drop=True)

    reserved = set(clinical_output.columns).intersection(
        {linked_matrix_ids.name, *linkage_flags.columns, *quantitative.columns}
    )
    if reserved:
        raise AnalysisError(
            "Clinical workbook columns collide with all-roster output fields: "
            + ", ".join(sorted(reserved))
        )
    return pd.concat(
        [clinical_output, linked_matrix_ids, linkage_flags, quantitative],
        axis=1,
    )


def make_preprocessor(frame: pd.DataFrame, min_category_frequency: int) -> ColumnTransformer:
    numeric_columns = frame.select_dtypes(include=[np.number, "bool"]).columns.tolist()
    categorical_columns = [column for column in frame.columns if column not in numeric_columns]
    transformers: list[tuple[str, Pipeline, list[str]]] = []
    if numeric_columns:
        numeric = Pipeline(
            [
                (
                    "imputer",
                    SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
                ),
                ("scaler", StandardScaler()),
            ]
        )
        transformers.append(("numeric", numeric, numeric_columns))
    if categorical_columns:
        categorical = Pipeline(
            [
                (
                    "imputer",
                    SimpleImputer(strategy="constant", fill_value="__MISSING__", keep_empty_features=True),
                ),
                (
                    "onehot",
                    OneHotEncoder(
                        handle_unknown="ignore",
                        min_frequency=min_category_frequency,
                    ),
                ),
            ]
        )
        transformers.append(("categorical", categorical, categorical_columns))
    if not transformers:
        raise AnalysisError("A feature set has no columns")
    return ColumnTransformer(transformers, remainder="drop")


def model_spec(name: str, seed: int) -> tuple[Any, dict[str, list[Any]]]:
    if name == "dummy":
        return DummyClassifier(strategy="prior"), {}
    if name == "elastic_net":
        model = LogisticRegression(
            penalty="elasticnet",
            solver="saga",
            class_weight="balanced",
            max_iter=10000,
            random_state=seed,
        )
        return model, {
            "model__C": [0.01, 0.1, 1.0, 10.0],
            "model__l1_ratio": [0.0, 0.5, 1.0],
        }
    if name == "random_forest":
        model = RandomForestClassifier(
            n_estimators=300,
            class_weight="balanced_subsample",
            random_state=seed,
            n_jobs=1,
        )
        return model, {
            "model__max_depth": [3, None],
            "model__min_samples_leaf": [2, 5],
            "model__max_features": ["sqrt", 0.5],
        }
    raise AnalysisError(f"Unknown model: {name}")


def calculate_metrics(y_true: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    probabilities = np.asarray(probabilities, dtype=float)
    predicted = (probabilities >= 0.5).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, predicted, labels=[0, 1]).ravel()

    def safe_divide(numerator: float, denominator: float) -> float:
        return float(numerator / denominator) if denominator else float("nan")

    return {
        "roc_auc": float(roc_auc_score(y_true, probabilities)),
        "average_precision": float(average_precision_score(y_true, probabilities)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, predicted)),
        "sensitivity": float(recall_score(y_true, predicted, pos_label=1, zero_division=0)),
        "specificity": safe_divide(tn, tn + fp),
        "precision": float(precision_score(y_true, predicted, pos_label=1, zero_division=0)),
        "npv": safe_divide(tn, tn + fn),
        "f1": float(f1_score(y_true, predicted, pos_label=1, zero_division=0)),
        "mcc": float(matthews_corrcoef(y_true, predicted)),
        "brier": float(brier_score_loss(y_true, probabilities)),
    }


def prepare_patient_groups(patient_values: pd.Series) -> pd.Series:
    if patient_values.isna().any() or patient_values.astype(str).str.strip().eq("").any():
        raise AnalysisError("Patient grouping column contains missing values")
    groups = patient_values.map(normalize_text)
    duplicate_groups = groups.duplicated(keep=False)
    if duplicate_groups.any():
        raise AnalysisError(
            f"Patient grouping column maps {int(duplicate_groups.sum())} analysis rows "
            "to repeated patient groups. Pool related slides upstream with "
            "bin/aggregate_histoplus_celltypes.py --sample-map so the clinical ML "
            "cohort contains exactly one matrix sample per patient."
        )
    return groups


def group_outcomes(
    y: np.ndarray,
    groups: np.ndarray,
    *,
    context: str,
) -> pd.Series:
    """Return one binary outcome per group, rejecting internally inconsistent groups."""

    if len(y) != len(groups):
        raise AnalysisError(f"{context}: outcome and group arrays have different lengths")
    table = pd.DataFrame({"outcome": np.asarray(y, dtype=int), "group": groups.astype(str)})
    outcomes_per_group = table.groupby("group")["outcome"].nunique()
    inconsistent = outcomes_per_group[outcomes_per_group > 1]
    if not inconsistent.empty:
        raise AnalysisError(
            f"{context}: {len(inconsistent)} patient group(s) contain conflicting outcome labels"
        )
    return table.groupby("group", sort=False)["outcome"].first()


def collapse_group_predictions(
    y: np.ndarray,
    probabilities: np.ndarray,
    groups: np.ndarray,
    *,
    context: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Average slide probabilities so each patient is one evaluation unit."""

    outcomes = group_outcomes(y, groups, context=context)
    mean_probability = (
        pd.DataFrame({"group": groups.astype(str), "probability": probabilities})
        .groupby("group", sort=False)["probability"]
        .mean()
        .reindex(outcomes.index)
    )
    return outcomes.to_numpy(dtype=int), mean_probability.to_numpy(dtype=float)


def validate_split_support(
    y: np.ndarray,
    groups: np.ndarray,
    n_splits: int,
    *,
    grouped: bool,
    context: str,
) -> None:
    class_counts = np.bincount(np.asarray(y, dtype=int), minlength=2)
    if np.unique(y).size != 2:
        raise AnalysisError(f"{context}: both outcome classes are required")
    if grouped:
        per_group = group_outcomes(y, groups, context=context)
        group_class_counts = per_group.value_counts().reindex([0, 1], fill_value=0)
        if int(group_class_counts.min()) < n_splits:
            raise AnalysisError(
                f"{context}: requested {n_splits} folds, but independent patient-group "
                f"counts by class are {group_class_counts.astype(int).tolist()}. Reduce "
                "the number of folds or obtain more independent groups in each class."
            )
    elif int(class_counts.min()) < n_splits:
        raise AnalysisError(
            f"{context}: requested {n_splits} folds, but sample counts by class are "
            f"{class_counts.tolist()}"
        )


def validate_generated_splits(
    splits: list[tuple[np.ndarray, np.ndarray]],
    y: np.ndarray,
    groups: np.ndarray,
    *,
    grouped: bool,
    context: str,
) -> None:
    for fold, (train_index, test_index) in enumerate(splits):
        if grouped and set(groups[train_index]).intersection(groups[test_index]):
            raise AnalysisError(f"{context} fold={fold}: a patient group crosses train and test")
        for split_name, indices in (("train", train_index), ("test", test_index)):
            if np.unique(y[indices]).size != 2:
                raise AnalysisError(
                    f"{context} fold={fold} produced a one-class {split_name} partition. "
                    "Reduce the number of folds or revise the patient grouping design."
                )


def build_outer_splits(
    y: np.ndarray,
    groups: np.ndarray,
    n_splits: int,
    n_repeats: int,
    seed: int,
    grouped: bool,
) -> list[tuple[int, int, np.ndarray, np.ndarray]]:
    validate_split_support(
        y,
        groups,
        n_splits,
        grouped=grouped,
        context="Outer CV",
    )
    output: list[tuple[int, int, np.ndarray, np.ndarray]] = []
    for repeat in range(n_repeats):
        if grouped:
            splitter = StratifiedGroupKFold(
                n_splits=n_splits,
                shuffle=True,
                random_state=seed + repeat,
            )
            iterator = splitter.split(np.zeros(len(y)), y, groups)
        else:
            splitter = StratifiedKFold(
                n_splits=n_splits,
                shuffle=True,
                random_state=seed + repeat,
            )
            iterator = splitter.split(np.zeros(len(y)), y)
        try:
            repeat_splits = list(iterator)
        except ValueError as exc:
            raise AnalysisError(f"Outer CV could not construct grouped folds: {exc}") from exc
        validate_generated_splits(
            repeat_splits,
            y,
            groups,
            grouped=grouped,
            context=f"Outer CV repeat={repeat}",
        )
        for fold, (train_index, test_index) in enumerate(repeat_splits):
            output.append((repeat, fold, train_index, test_index))
    return output


def build_inner_splits(
    y: np.ndarray,
    groups: np.ndarray,
    n_splits: int,
    seed: int,
    *,
    grouped: bool,
    context: str,
) -> list[tuple[np.ndarray, np.ndarray]]:
    validate_split_support(
        y,
        groups,
        n_splits,
        grouped=grouped,
        context=context,
    )
    if grouped:
        splitter = StratifiedGroupKFold(
            n_splits=n_splits,
            shuffle=True,
            random_state=seed,
        )
        iterator = splitter.split(np.zeros(len(y)), y, groups)
    else:
        splitter = StratifiedKFold(
            n_splits=n_splits,
            shuffle=True,
            random_state=seed,
        )
        iterator = splitter.split(np.zeros(len(y)), y)
    try:
        splits = list(iterator)
    except ValueError as exc:
        raise AnalysisError(f"{context} could not construct folds: {exc}") from exc
    validate_generated_splits(
        splits,
        y,
        groups,
        grouped=grouped,
        context=context,
    )
    return splits


def run_nested_cv(
    feature_frames: dict[str, pd.DataFrame],
    y: pd.Series,
    groups: pd.Series,
    models: list[str],
    outer_splits: int,
    outer_repeats: int,
    inner_splits: int,
    seed: int,
    n_jobs: int,
    permutation_repeats: int,
    min_category_frequency: int,
    grouped: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    y_values = y.astype(int).to_numpy()
    group_values = groups.astype(str).to_numpy()
    outer = build_outer_splits(
        y_values,
        group_values,
        outer_splits,
        outer_repeats,
        seed,
        grouped,
    )
    assignment_rows: list[dict[str, Any]] = []
    for repeat, fold, train_index, test_index in outer:
        for split_name, indices in (("train", train_index), ("test", test_index)):
            for index in indices:
                group_hash = hashlib.sha256(group_values[index].encode("utf-8")).hexdigest()[:12]
                assignment_rows.append(
                    {
                        "repeat": repeat,
                        "outer_fold": fold,
                        "analysis_id": str(y.index[index]),
                        "group_hash": group_hash,
                        "split": split_name,
                    }
                )

    prediction_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    importance_rows: list[dict[str, Any]] = []
    for feature_set, frame in feature_frames.items():
        frame = frame.copy()
        for column in frame.select_dtypes(exclude=[np.number, "bool"]).columns:
            frame[column] = frame[column].astype("object").where(frame[column].notna(), np.nan)
        for repeat, fold, train_index, test_index in outer:
            X_train = frame.iloc[train_index]
            X_test = frame.iloc[test_index]
            y_train = y_values[train_index]
            y_test = y_values[test_index]
            groups_train = group_values[train_index]
            groups_test = group_values[test_index]
            inner_cv = build_inner_splits(
                y_train,
                groups_train,
                inner_splits,
                seed + 1000 * repeat + fold,
                grouped=grouped,
                context=f"Inner CV for outer repeat={repeat} fold={fold}",
            )

            for model_name in models:
                estimator, parameter_grid = model_spec(
                    model_name, seed + 100000 * repeat + 100 * fold
                )
                pipeline = Pipeline(
                    [
                        ("preprocess", make_preprocessor(frame, min_category_frequency)),
                        ("model", estimator),
                    ]
                )
                if parameter_grid:
                    search = GridSearchCV(
                        pipeline,
                        parameter_grid,
                        scoring="roc_auc",
                        cv=inner_cv,
                        n_jobs=n_jobs,
                        refit=True,
                        error_score="raise",
                    )
                    search.fit(X_train, y_train)
                    fitted = search.best_estimator_
                    best_parameters = search.best_params_
                    inner_score = float(search.best_score_)
                else:
                    fitted = clone(pipeline).fit(X_train, y_train)
                    best_parameters = {}
                    inner_score = float("nan")
                probabilities = fitted.predict_proba(X_test)[:, 1]
                predicted = (probabilities >= 0.5).astype(int)
                if grouped:
                    metric_y, metric_probabilities = collapse_group_predictions(
                        y_test,
                        probabilities,
                        groups_test,
                        context=f"Outer repeat={repeat} fold={fold} evaluation",
                    )
                    train_outcomes = group_outcomes(
                        y_train,
                        groups_train,
                        context=f"Outer repeat={repeat} fold={fold} training",
                    ).to_numpy(dtype=int)
                else:
                    metric_y, metric_probabilities = y_test, probabilities
                    train_outcomes = y_train
                metrics = calculate_metrics(metric_y, metric_probabilities)
                metric_rows.append(
                    {
                        "repeat": repeat,
                        "outer_fold": fold,
                        "feature_set": feature_set,
                        "model": model_name,
                        "n_train": len(train_index),
                        "n_test": len(test_index),
                        "n_train_evaluation_units": int(len(train_outcomes)),
                        "n_test_evaluation_units": int(len(metric_y)),
                        "evaluation_unit": "patient_group" if grouped else "sample",
                        "n_positive_train": int(train_outcomes.sum()),
                        "n_positive_test": int(metric_y.sum()),
                        **metrics,
                    }
                )
                selection_rows.append(
                    {
                        "repeat": repeat,
                        "outer_fold": fold,
                        "feature_set": feature_set,
                        "model": model_name,
                        "selected_hyperparameters_json": json.dumps(
                            best_parameters, sort_keys=True
                        ),
                        "inner_roc_auc": inner_score,
                    }
                )
                for local_index, global_index in enumerate(test_index):
                    prediction_rows.append(
                        {
                            "analysis_id": str(y.index[global_index]),
                            "repeat": repeat,
                            "outer_fold": fold,
                            "feature_set": feature_set,
                            "model": model_name,
                            "y_true": int(y_test[local_index]),
                            "y_probability": float(probabilities[local_index]),
                            "y_predicted": int(predicted[local_index]),
                            "threshold": 0.5,
                        }
                    )
                if model_name != "dummy" and permutation_repeats > 0:
                    importance = permutation_importance(
                        fitted,
                        X_test,
                        y_test,
                        scoring="roc_auc",
                        n_repeats=permutation_repeats,
                        random_state=seed + 1000000 * repeat + 1000 * fold,
                        n_jobs=n_jobs,
                    )
                    for feature, mean, standard_deviation in zip(
                        frame.columns,
                        importance.importances_mean,
                        importance.importances_std,
                    ):
                        importance_rows.append(
                            {
                                "repeat": repeat,
                                "outer_fold": fold,
                                "feature_set": feature_set,
                                "model": model_name,
                                "feature": feature,
                                "importance_mean": float(mean),
                                "importance_std": float(standard_deviation),
                                "scoring": "roc_auc",
                            }
                        )
    return (
        pd.DataFrame(prediction_rows),
        pd.DataFrame(metric_rows),
        pd.DataFrame(selection_rows),
        pd.DataFrame(importance_rows),
        pd.DataFrame(assignment_rows),
    )


def stratified_bootstrap_indices(
    y: np.ndarray,
    groups: np.ndarray | None,
    rng: np.random.Generator,
) -> np.ndarray:
    """Sample independent groups within outcome strata and retain every group member."""

    y = np.asarray(y, dtype=int)
    group_values = (
        np.asarray(groups).astype(str)
        if groups is not None
        else np.asarray([f"__row_{index}" for index in range(len(y))])
    )
    outcomes = group_outcomes(y, group_values, context="Stratified bootstrap")
    group_indices: dict[str, np.ndarray] = {
        group: np.flatnonzero(group_values == group) for group in outcomes.index.astype(str)
    }
    sampled_groups: list[str] = []
    for outcome in (0, 1):
        eligible = outcomes.index[outcomes == outcome].astype(str).to_numpy()
        if len(eligible) == 0:
            raise AnalysisError("Stratified bootstrap requires independent groups in both classes")
        sampled_groups.extend(
            rng.choice(eligible, size=len(eligible), replace=True).astype(str).tolist()
        )
    return np.concatenate([group_indices[group] for group in sampled_groups])


def groups_for_analysis_ids(
    analysis_ids: pd.Series | pd.Index,
    groups: pd.Series | None,
) -> np.ndarray | None:
    if groups is None:
        return None
    normalized = groups.copy()
    normalized.index = normalized.index.astype(str)
    if normalized.index.duplicated().any():
        raise AnalysisError("Patient-group mapping contains duplicate analysis IDs")
    requested = pd.Index(analysis_ids).astype(str)
    mapped = normalized.reindex(requested)
    if mapped.isna().any():
        raise AnalysisError("Patient-group mapping does not cover every OOF analysis ID")
    return mapped.astype(str).to_numpy()


def collapse_evaluation_unit_predictions(
    averaged: pd.DataFrame,
    groups: pd.Series | None,
) -> pd.DataFrame:
    """Return one OOF probability per patient group, or per sample when ungrouped."""

    evaluation = averaged.copy()
    if groups is None:
        evaluation["evaluation_id"] = evaluation["analysis_id"].astype(str)
        return evaluation
    evaluation["evaluation_id"] = groups_for_analysis_ids(
        evaluation["analysis_id"], groups
    )
    group_outcomes(
        evaluation["y_true"].to_numpy(dtype=int),
        evaluation["evaluation_id"].to_numpy(dtype=str),
        context="Patient-level OOF evaluation",
    )
    return (
        evaluation.groupby(["evaluation_id", "feature_set", "model"], as_index=False)
        .agg(y_true=("y_true", "first"), y_probability=("y_probability", "mean"))
    )


def bootstrap_metric_intervals(
    predictions: pd.DataFrame,
    fold_metrics: pd.DataFrame,
    repeats: int,
    seed: int,
    groups: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    averaged = (
        predictions.groupby(["analysis_id", "feature_set", "model"], as_index=False)
        .agg(y_true=("y_true", "first"), y_probability=("y_probability", "mean"))
    )
    averaged["y_predicted"] = (averaged["y_probability"] >= 0.5).astype(int)
    evaluation = collapse_evaluation_unit_predictions(averaged, groups)
    summary_rows: list[dict[str, Any]] = []
    for group_index, ((feature_set, model), group) in enumerate(
        evaluation.groupby(["feature_set", "model"], sort=False)
    ):
        y_true = group["y_true"].to_numpy(dtype=int)
        probabilities = group["y_probability"].to_numpy(dtype=float)
        evaluation_ids = group["evaluation_id"].astype(str).to_numpy()
        point = calculate_metrics(y_true, probabilities)
        rng = np.random.default_rng(seed + group_index)
        distributions = {metric: [] for metric in METRIC_NAMES}
        for _ in range(repeats):
            sampled = stratified_bootstrap_indices(y_true, evaluation_ids, rng)
            values = calculate_metrics(y_true[sampled], probabilities[sampled])
            for metric in METRIC_NAMES:
                distributions[metric].append(values[metric])
        folds = fold_metrics.loc[
            (fold_metrics["feature_set"] == feature_set)
            & (fold_metrics["model"] == model)
        ]
        n_samples = len(
            averaged.loc[
                (averaged["feature_set"] == feature_set) & (averaged["model"] == model)
            ]
        )
        for metric in METRIC_NAMES:
            distribution = np.asarray(distributions[metric], dtype=float)
            finite = distribution[np.isfinite(distribution)]
            summary_rows.append(
                {
                    "feature_set": feature_set,
                    "model": model,
                    "metric": metric,
                    "point_estimate": point[metric],
                    "bootstrap_ci_low": float(np.quantile(finite, 0.025)) if finite.size else np.nan,
                    "bootstrap_ci_high": float(np.quantile(finite, 0.975)) if finite.size else np.nan,
                    "fold_mean": float(folds[metric].mean()),
                    "fold_std": float(folds[metric].std(ddof=1)),
                    "n_outer_folds": int(len(folds)),
                    "n_analysis_samples": int(n_samples),
                    "n_evaluation_units": int(len(group)),
                    "n_independent_groups": int(len(group)),
                    "evaluation_unit": "patient_group" if groups is not None else "sample",
                    "bootstrap_unit": "patient_group" if groups is not None else "sample",
                }
            )
    return pd.DataFrame(summary_rows), averaged


def paired_incremental_value(
    averaged: pd.DataFrame,
    bootstrap_repeats: int,
    seed: int,
    groups: pd.Series | None = None,
) -> pd.DataFrame:
    """Paired bootstrap deltas with one equally weighted probability per patient."""

    evaluation = collapse_evaluation_unit_predictions(averaged, groups)
    rows: list[dict[str, Any]] = []
    comparisons = (
        ("combined_fractions", "clinical"),
        ("histoplus_fractions", "clinical"),
        ("histoplus_log_counts", "clinical"),
    )
    for model_index, (model, model_table) in enumerate(evaluation.groupby("model", sort=False)):
        probability = model_table.pivot(
            index="evaluation_id", columns="feature_set", values="y_probability"
        )
        outcome = model_table.groupby("evaluation_id")["y_true"].first().reindex(probability.index)
        y_true = outcome.to_numpy(dtype=int)
        evaluation_ids = probability.index.astype(str).to_numpy()
        for comparison_index, (candidate, reference) in enumerate(comparisons):
            if candidate not in probability.columns or reference not in probability.columns:
                continue
            candidate_probability = probability[candidate].to_numpy(dtype=float)
            reference_probability = probability[reference].to_numpy(dtype=float)
            candidate_metrics = calculate_metrics(y_true, candidate_probability)
            reference_metrics = calculate_metrics(y_true, reference_probability)
            rng = np.random.default_rng(seed + 100 * model_index + comparison_index)
            distributions = {metric: [] for metric in ("roc_auc", "balanced_accuracy", "brier")}
            for _ in range(bootstrap_repeats):
                sampled = stratified_bootstrap_indices(y_true, evaluation_ids, rng)
                candidate_boot = calculate_metrics(y_true[sampled], candidate_probability[sampled])
                reference_boot = calculate_metrics(y_true[sampled], reference_probability[sampled])
                for metric in distributions:
                    delta = (
                        reference_boot[metric] - candidate_boot[metric]
                        if metric == "brier"
                        else candidate_boot[metric] - reference_boot[metric]
                    )
                    distributions[metric].append(delta)
            for metric, distribution in distributions.items():
                point = (
                    reference_metrics[metric] - candidate_metrics[metric]
                    if metric == "brier"
                    else candidate_metrics[metric] - reference_metrics[metric]
                )
                values = np.asarray(distribution, dtype=float)
                rows.append(
                    {
                        "model": model,
                        "candidate_feature_set": candidate,
                        "reference_feature_set": reference,
                        "metric": metric,
                        "improvement_point_estimate": point,
                        "bootstrap_ci_low": float(np.quantile(values, 0.025)),
                        "bootstrap_ci_high": float(np.quantile(values, 0.975)),
                        "direction": "positive_favors_candidate",
                    }
                )
    return pd.DataFrame(rows, columns=INCREMENTAL_VALUE_COLUMNS)


def univariate_stratification(
    clinical_raw: pd.DataFrame,
    clinical_columns: list[str],
    counts_raw: pd.DataFrame,
    fractions_raw: pd.DataFrame,
    y: pd.Series,
    inferential: bool = True,
) -> pd.DataFrame:
    features: list[tuple[str, str, pd.Series]] = []
    for column in clinical_columns:
        features.append(("clinical", column, clinical_raw[column]))
    for column in counts_raw.columns:
        features.append(("histoplus_count", column, counts_raw[column]))
    for column in fractions_raw.columns:
        features.append(("histoplus_fraction", column, fractions_raw[column]))
    rows: list[dict[str, Any]] = []
    for source, feature, series in features:
        nonmissing = series.notna() & series.astype(str).str.strip().ne("")
        numeric = pd.to_numeric(series.where(nonmissing), errors="coerce")
        numeric_ratio = float(numeric.notna().sum() / max(1, int(nonmissing.sum())))
        if numeric_ratio >= 0.8:
            negative = numeric[y == 0].dropna().astype(float)
            positive = numeric[y == 1].dropna().astype(float)
            if len(negative) and len(positive):
                statistic, p_value = mannwhitneyu(positive, negative, alternative="two-sided")
                effect = 2.0 * float(statistic) / (len(positive) * len(negative)) - 1.0
            else:
                statistic = p_value = effect = np.nan

            def numeric_summary(values: pd.Series) -> str:
                if values.empty:
                    return "n=0"
                return (
                    f"n={len(values)}; median={values.median():.6g}; "
                    f"IQR={values.quantile(0.25):.6g}-{values.quantile(0.75):.6g}"
                )

            rows.append(
                {
                    "source": source,
                    "feature": feature,
                    "variable_type": "numeric",
                    "negative_summary": numeric_summary(negative),
                    "positive_summary": numeric_summary(positive),
                    "missing_negative": int(numeric[y == 0].isna().sum()),
                    "missing_positive": int(numeric[y == 1].isna().sum()),
                    "test": "Mann-Whitney U",
                    "statistic": statistic,
                    "effect_size": effect,
                    "p_value": p_value,
                }
            )
        else:
            categorical = clean_categorical(series, feature)
            observed = pd.DataFrame({"value": categorical, "outcome": y}).dropna()
            contingency = pd.crosstab(observed["value"], observed["outcome"])
            if contingency.shape[0] >= 2 and contingency.shape[1] == 2:
                if contingency.shape == (2, 2):
                    statistic, p_value = fisher_exact(contingency.to_numpy())
                    test_name = "Fisher exact"
                    effect = float(math.log(statistic)) if statistic > 0 else np.nan
                else:
                    statistic, p_value, _, _ = chi2_contingency(contingency)
                    test_name = "Chi-square"
                    n = float(contingency.to_numpy().sum())
                    effect = math.sqrt(float(statistic) / (n * max(1, min(contingency.shape) - 1)))
            else:
                statistic = p_value = effect = np.nan
                test_name = "not_testable"
            summaries: dict[int, str] = {}
            for outcome in (0, 1):
                counts = categorical[y == outcome].value_counts(dropna=True)
                summaries[outcome] = json.dumps(counts.to_dict(), ensure_ascii=False, sort_keys=True)
            rows.append(
                {
                    "source": source,
                    "feature": feature,
                    "variable_type": "categorical",
                    "negative_summary": summaries[0],
                    "positive_summary": summaries[1],
                    "missing_negative": int(categorical[y == 0].isna().sum()),
                    "missing_positive": int(categorical[y == 1].isna().sum()),
                    "test": test_name,
                    "statistic": statistic,
                    "effect_size": effect,
                    "p_value": p_value,
                }
            )
    output = pd.DataFrame(
        rows,
        columns=[
            "source",
            "feature",
            "variable_type",
            "negative_summary",
            "positive_summary",
            "missing_negative",
            "missing_positive",
            "test",
            "statistic",
            "effect_size",
            "p_value",
        ],
    )
    output["analysis_unit"] = "sample"
    if not inferential:
        output["test"] = "not_tested_grouped_specimen_descriptive"
        output[["statistic", "effect_size", "p_value"]] = np.nan
        output["analysis_unit"] = "specimen_descriptive_grouped"
    output["fdr_bh_q_value"] = benjamini_hochberg(output["p_value"])
    return output.sort_values(["fdr_bh_q_value", "p_value", "source", "feature"], na_position="last")


def save_figure(fig: plt.Figure, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(base.with_suffix(".png"), dpi=220, bbox_inches="tight")
    fig.savefig(base.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def plot_cohort_flow(
    linkage: pd.DataFrame,
    outcome_counts: dict[str, int],
    output_dir: Path,
) -> None:
    labels = ["Clinical rows", "Completed HistoPLUS", "Analysis cohort", "Negative", "Positive"]
    values = [
        int(linkage["in_clinical"].sum()),
        int(linkage["slide_completed"].sum()),
        int(linkage["analysis_included"].sum()),
        outcome_counts["negative"],
        outcome_counts["positive"],
    ]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    colors = ["#4C78A8", "#59A14F", "#76B7B2", "#F28E2B", "#E15759"]
    bars = ax.bar(labels, values, color=colors)
    ax.bar_label(bars, padding=3)
    ax.set_ylabel("Samples")
    ax.set_title("Cohort linkage and outcome flow")
    ax.tick_params(axis="x", rotation=20)
    ax.spines[["top", "right"]].set_visible(False)
    save_figure(fig, output_dir / "figures" / "cohort_flow")


def plot_histoplus_composition(
    fractions: pd.DataFrame,
    metadata: pd.DataFrame,
    y: pd.Series,
    output_dir: Path,
) -> None:
    if fractions.shape[1] == 0 or metadata.empty:
        return
    medians = pd.DataFrame(
        {
            "Negative": fractions.loc[y == 0].median(axis=0),
            "Positive": fractions.loc[y == 1].median(axis=0),
        }
    )
    labels = metadata["cell_type"].astype(str).tolist()
    fig, ax = plt.subplots(figsize=(9, max(5, 0.35 * len(labels))))
    image = ax.imshow(medians.to_numpy(), aspect="auto", cmap="viridis")
    ax.set_yticks(np.arange(len(labels)), labels=labels)
    ax.set_xticks([0, 1], labels=medians.columns)
    ax.set_title("Median HistoPLUS cell-type fractions by outcome")
    fig.colorbar(image, ax=ax, label="Median fraction")
    save_figure(fig, output_dir / "figures" / "histoplus_fraction_stratification")


def plot_pca(clr: pd.DataFrame, y: pd.Series, output_dir: Path) -> None:
    if clr.shape[1] < 2:
        return
    coordinates = PCA(n_components=2).fit_transform(StandardScaler().fit_transform(clr))
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    for outcome, label, color in ((0, "Negative", "#F28E2B"), (1, "Positive", "#E15759")):
        mask = y.to_numpy() == outcome
        ax.scatter(coordinates[mask, 0], coordinates[mask, 1], label=label, color=color, alpha=0.8)
    ax.set_xlabel("PC1")
    ax.set_ylabel("PC2")
    ax.set_title("HistoPLUS CLR composition PCA (descriptive only)")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    save_figure(fig, output_dir / "figures" / "histoplus_clr_pca")


def plot_model_results(
    summary: pd.DataFrame,
    averaged: pd.DataFrame,
    output_dir: Path,
) -> None:
    key_metrics = ["roc_auc", "balanced_accuracy", "average_precision", "brier"]
    heat = summary.loc[summary["metric"].isin(key_metrics)].pivot_table(
        index=["feature_set", "model"], columns="metric", values="point_estimate"
    )
    if not heat.empty:
        fig, ax = plt.subplots(figsize=(8, max(4, 0.42 * len(heat))))
        image = ax.imshow(heat.to_numpy(), aspect="auto", cmap="magma", vmin=0, vmax=1)
        ax.set_yticks(np.arange(len(heat)), labels=[" / ".join(index) for index in heat.index])
        ax.set_xticks(np.arange(len(heat.columns)), labels=heat.columns, rotation=25, ha="right")
        for row in range(heat.shape[0]):
            for column in range(heat.shape[1]):
                ax.text(column, row, f"{heat.iloc[row, column]:.2f}", ha="center", va="center", color="white")
        ax.set_title("Repeated nested-CV out-of-fold performance")
        fig.colorbar(image, ax=ax)
        save_figure(fig, output_dir / "figures" / "model_performance")

    available_models = averaged["model"].unique().tolist()
    display_model = "elastic_net" if "elastic_net" in available_models else available_models[0]
    selected = averaged.loc[averaged["model"] == display_model]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for feature_set, group in selected.groupby("feature_set", sort=False):
        y_true = group["y_true"].to_numpy(dtype=int)
        probability = group["y_probability"].to_numpy(dtype=float)
        false_positive, true_positive, _ = roc_curve(y_true, probability)
        precision, recall, _ = precision_recall_curve(y_true, probability)
        axes[0].plot(false_positive, true_positive, label=f"{feature_set} ({roc_auc_score(y_true, probability):.2f})")
        axes[1].plot(recall, precision, label=f"{feature_set} ({average_precision_score(y_true, probability):.2f})")
    axes[0].plot([0, 1], [0, 1], "--", color="grey", linewidth=1)
    axes[0].set(xlabel="False-positive rate", ylabel="True-positive rate", title=f"OOF ROC — {display_model}")
    axes[1].set(xlabel="Recall", ylabel="Precision", title=f"OOF precision–recall — {display_model}")
    for ax in axes:
        ax.legend(fontsize=8, frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
    save_figure(fig, output_dir / "figures" / "oof_roc_pr_curves")


def plot_calibration(averaged: pd.DataFrame, output_dir: Path) -> None:
    """Write an OOF reliability diagram when at least one non-dummy model was run."""

    non_dummy = averaged.loc[averaged["model"] != "dummy"]
    if non_dummy.empty:
        return
    available_models = non_dummy["model"].unique().tolist()
    display_model = "elastic_net" if "elastic_net" in available_models else available_models[0]
    selected = non_dummy.loc[non_dummy["model"] == display_model]
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    for feature_set, group in selected.groupby("feature_set", sort=False):
        n_bins = min(10, max(2, len(group) // 5))
        observed, predicted = calibration_curve(
            group["y_true"].to_numpy(dtype=int),
            group["y_probability"].to_numpy(dtype=float),
            n_bins=n_bins,
            strategy="quantile",
        )
        ax.plot(predicted, observed, marker="o", label=feature_set)
    ax.plot([0, 1], [0, 1], "--", color="grey", linewidth=1, label="Ideal")
    ax.set(
        xlabel="Mean OOF predicted probability",
        ylabel="Observed positive fraction",
        title=f"OOF reliability — {display_model}",
        xlim=(0, 1),
        ylim=(0, 1),
    )
    ax.legend(fontsize=8, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    save_figure(fig, output_dir / "figures" / "oof_calibration")


def plot_importance(importances: pd.DataFrame, output_dir: Path) -> None:
    if importances.empty:
        return
    preferred = importances.loc[
        (importances["feature_set"] == "combined_fractions")
        & (importances["model"] == "elastic_net")
    ]
    if preferred.empty:
        preferred = importances.loc[importances["model"] != "dummy"]
    aggregate = (
        preferred.groupby("feature", as_index=False)["importance_mean"]
        .agg(["mean", "std"])
        .reset_index()
        .sort_values("mean", ascending=False)
        .head(20)
        .sort_values("mean")
    )
    if aggregate.empty:
        return
    fig, ax = plt.subplots(figsize=(8, max(5, 0.35 * len(aggregate))))
    ax.barh(aggregate["feature"], aggregate["mean"], xerr=aggregate["std"].fillna(0), color="#4C78A8")
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Held-out permutation importance (ROC-AUC decrease)")
    ax.set_title("Top raw features across outer test folds")
    ax.spines[["top", "right"]].set_visible(False)
    save_figure(fig, output_dir / "figures" / "heldout_permutation_importance")


def render_analysis_report(
    summary_metrics: pd.DataFrame,
    incremental_value: pd.DataFrame,
    stratification: pd.DataFrame,
    cohort: dict[str, int],
    args: argparse.Namespace,
) -> str:
    """Render a concise aggregate report without disclosing patient-level values."""

    preferred_model = "elastic_net" if "elastic_net" in summary_metrics["model"].unique() else summary_metrics["model"].iloc[0]

    def interval(feature_set: str, metric: str) -> str:
        selected = summary_metrics.loc[
            (summary_metrics["feature_set"] == feature_set)
            & (summary_metrics["model"] == preferred_model)
            & (summary_metrics["metric"] == metric)
        ]
        if selected.empty:
            return "not run"
        row = selected.iloc[0]
        return (
            f"{row.point_estimate:.3f} "
            f"(95% bootstrap CI {row.bootstrap_ci_low:.3f}–{row.bootstrap_ci_high:.3f})"
        )

    delta = pd.DataFrame()
    delta_columns = {
        "model",
        "candidate_feature_set",
        "reference_feature_set",
        "metric",
    }
    if delta_columns.issubset(incremental_value.columns):
        delta = incremental_value.loc[
            (incremental_value["model"] == preferred_model)
            & (incremental_value["candidate_feature_set"] == "combined_fractions")
            & (incremental_value["reference_feature_set"] == "clinical")
            & (incremental_value["metric"] == "roc_auc")
        ]
    if delta.empty:
        delta_text = "not available"
    else:
        row = delta.iloc[0]
        delta_text = (
            f"{row.improvement_point_estimate:+.3f} "
            f"(95% paired bootstrap CI {row.bootstrap_ci_low:+.3f} to {row.bootstrap_ci_high:+.3f})"
        )
    n_fdr_005 = int((stratification["fdr_bh_q_value"] < 0.05).sum())
    n_fdr_010 = int((stratification["fdr_bh_q_value"] < 0.10).sum())
    evaluation_unit = cohort.get("evaluation_unit", "sample")
    n_evaluation_units = cohort.get("n_evaluation_units", cohort["n_analysis_samples"])
    n_positive_units = cohort.get("n_positive_evaluation_units", cohort["n_positive"])
    n_negative_units = cohort.get("n_negative_evaluation_units", cohort["n_negative"])
    prevalence = n_positive_units / n_evaluation_units
    inference_suppressed = bool(
        len(stratification)
        and stratification["test"].eq("not_tested_grouped_specimen_descriptive").all()
    )
    if inference_suppressed:
        stratification_text = (
            f"- {len(stratification)} specimen-level comparisons were summarized descriptively.\n"
            "- Inferential p-values and FDR q-values were suppressed because repeated "
            "specimens are not independent patient observations.\n"
            "- No grouped univariate significance claims should be made from this table."
        )
    else:
        stratification_text = (
            f"- {len(stratification)} prespecified clinical/HistoPLUS comparisons were tested.\n"
            f"- FDR-BH q < 0.05: {n_fdr_005}; q < 0.10: {n_fdr_010}.\n"
            "- These full-cohort univariate tests are descriptive and were not used for feature selection."
        )
    return f"""# Clinical + HistoPLUS exploratory ML report

## Cohort and endpoint

- Analysis cohort: {cohort['n_analysis_samples']} linked samples.
- Evaluation unit: {evaluation_unit}; {n_evaluation_units} independent units ({n_positive_units} `{args.positive_label}`, {n_negative_units} `{args.negative_label}`; event prevalence {prevalence:.1%}).
- Linkage exclusions: {cohort['n_linkage_excluded']}; see `linkage_audit.csv`.
- Validation: {args.outer_splits}-fold outer CV × {args.outer_repeats} repeats with {args.inner_splits}-fold inner tuning.
- Primary interpretation: association with the supplied current status label, **not validated survival prediction**.

## Repeated nested-CV results ({preferred_model})

| Feature set | AUROC | Balanced accuracy | Brier score |
|---|---:|---:|---:|
| Clinical | {interval('clinical', 'roc_auc')} | {interval('clinical', 'balanced_accuracy')} | {interval('clinical', 'brier')} |
| HistoPLUS CLR fractions | {interval('histoplus_fractions', 'roc_auc')} | {interval('histoplus_fractions', 'balanced_accuracy')} | {interval('histoplus_fractions', 'brier')} |
| HistoPLUS log counts | {interval('histoplus_log_counts', 'roc_auc')} | {interval('histoplus_log_counts', 'balanced_accuracy')} | {interval('histoplus_log_counts', 'brier')} |
| Clinical + CLR fractions | {interval('combined_fractions', 'roc_auc')} | {interval('combined_fractions', 'balanced_accuracy')} | {interval('combined_fractions', 'brier')} |

Paired AUROC change for combined fractions versus clinical alone: **{delta_text}**.
Positive values favor adding HistoPLUS. Review `incremental_value.csv` for all
prespecified models and metrics.

## Descriptive stratification

{stratification_text}

## Interpretation guardrails

The merged `analysis_cohort.csv`, `linked_clinical_histoplus_full.csv`, linkage,
prediction, and fold files are specimen-level sensitive outputs. Keep this
directory private. Do not select and re-report the highest observed score as if
it came from an independent test cohort. Current status lacks a common fixed
follow-up horizon and censoring/last-contact data, so the results cannot be
described as a validated survival or prognostic model. External or temporal
validation and a clinically defined endpoint are required before clinical use.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Link clinical metadata to HistoPLUS matrices and run exploratory nested-CV classification."
    )
    parser.add_argument("--clinical-xlsx", type=Path, required=True)
    parser.add_argument("--clinical-sheet", default=None)
    parser.add_argument("--sample-id-column", required=True)
    parser.add_argument("--patient-id-column", default=None)
    parser.add_argument("--outcome-column", required=True)
    parser.add_argument("--positive-label", required=True)
    parser.add_argument("--negative-label", required=True)
    parser.add_argument(
        "--clinical-feature",
        action="append",
        default=[],
        help="Prespecified clinical predictor column; repeat for multiple predictors",
    )
    parser.add_argument(
        "--numeric-clinical-feature",
        action="append",
        default=[],
        help="Clinical predictor declared numeric; repeat and also list with --clinical-feature",
    )
    parser.add_argument(
        "--categorical-clinical-feature",
        action="append",
        default=[],
        help="Clinical predictor declared categorical; repeat and also list with --clinical-feature",
    )
    parser.add_argument(
        "--stratification-feature",
        action="append",
        default=[],
        help="Clinical column used only for descriptive outcome stratification; repeat as needed",
    )
    parser.add_argument("--counts-matrix", type=Path, required=True)
    parser.add_argument("--fractions-matrix", type=Path, required=True)
    parser.add_argument("--aggregation-audit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--feature-sets",
        default=",".join(FEATURE_SET_ORDER),
        help="Comma-separated subset of: " + ",".join(FEATURE_SET_ORDER),
    )
    parser.add_argument(
        "--models",
        default="dummy,elastic_net,random_forest",
        help="Comma-separated subset of: dummy,elastic_net,random_forest",
    )
    parser.add_argument("--outer-splits", type=int, default=5)
    parser.add_argument("--outer-repeats", type=int, default=5)
    parser.add_argument("--inner-splits", type=int, default=4)
    parser.add_argument("--bootstrap-repeats", type=int, default=1000)
    parser.add_argument("--permutation-repeats", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--n-jobs", type=int, default=1)
    parser.add_argument("--clr-pseudocount", type=float, default=1e-6)
    parser.add_argument("--min-category-frequency", type=int, default=3)
    parser.add_argument("--max-categorical-levels", type=int, default=20)
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    input_paths = {
        "clinical_xlsx": args.clinical_xlsx.expanduser().resolve(),
        "counts_matrix": args.counts_matrix.expanduser().resolve(),
        "fractions_matrix": args.fractions_matrix.expanduser().resolve(),
        "aggregation_audit": args.aggregation_audit.expanduser().resolve(),
    }
    for label, path in input_paths.items():
        if not path.is_file():
            raise AnalysisError(f"{label} does not exist: {path}")
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.outer_splits < 2 or args.inner_splits < 2 or args.outer_repeats < 1:
        raise AnalysisError("CV splits must be >=2 and repeats must be >=1")
    if args.bootstrap_repeats < 1 or args.permutation_repeats < 0:
        raise AnalysisError("Bootstrap repeats must be >=1 and permutation repeats must be >=0")
    feature_sets = parse_csv_list(args.feature_sets, FEATURE_SET_ORDER)
    models = parse_csv_list(args.models, ("dummy", "elastic_net", "random_forest"))
    clinical_feature_types = clinical_feature_type_map(
        args.clinical_feature,
        args.numeric_clinical_feature,
        args.categorical_clinical_feature,
    )

    clinical, sheet = read_clinical_workbook(input_paths["clinical_xlsx"], args.clinical_sheet)
    required_clinical = {
        args.sample_id_column, args.outcome_column, *args.clinical_feature, *args.stratification_feature
    }
    if args.patient_id_column:
        required_clinical.add(args.patient_id_column)
    missing_clinical = sorted(required_clinical.difference(clinical.columns))
    if missing_clinical:
        raise AnalysisError("Clinical workbook lacks column(s): " + ", ".join(missing_clinical))
    forbidden = {args.sample_id_column, args.outcome_column}
    if args.patient_id_column:
        forbidden.add(args.patient_id_column)
    overlap = sorted(set(args.clinical_feature).intersection(forbidden))
    if overlap:
        raise AnalysisError("Identifiers/outcome cannot be clinical predictors: " + ", ".join(overlap))
    if ("clinical" in feature_sets or "combined_fractions" in feature_sets) and not args.clinical_feature:
        raise AnalysisError("Clinical feature sets require at least one repeated --clinical-feature")
    stratification_features = args.stratification_feature or args.clinical_feature
    forbidden_stratification = sorted(set(stratification_features).intersection(forbidden))
    if forbidden_stratification:
        raise AnalysisError(
            "Identifiers/outcome cannot be stratification variables: "
            + ", ".join(forbidden_stratification)
        )

    counts, count_meta = read_histoplus_matrix(input_paths["counts_matrix"], "HISTO_COUNT")
    fractions, fraction_meta = read_histoplus_matrix(
        input_paths["fractions_matrix"], "HISTO_FRACTION"
    )
    validate_histoplus_inputs(counts, fractions, count_meta, fraction_meta)
    audit = pd.read_csv(input_paths["aggregation_audit"])
    linkage, eligible_clinical, outcome_counts = build_linkage(
        clinical,
        args.sample_id_column,
        args.outcome_column,
        args.positive_label,
        args.negative_label,
        counts.index.astype(str).tolist(),
        audit,
    )
    all_clinical_roster = build_all_clinical_roster(
        clinical,
        args.sample_id_column,
        linkage,
        counts,
        fractions,
    )
    analysis_ids = eligible_clinical.index.astype(str).tolist()
    counts = counts.loc[analysis_ids]
    fractions = fractions.loc[analysis_ids]
    y = eligible_clinical["outcome_binary"].astype(int)
    y.index = analysis_ids

    clinical_features, clinical_manifest = prepare_clinical_features(
        eligible_clinical,
        args.clinical_feature,
        clinical_feature_types,
        args.max_categorical_levels,
    )
    clinical_features.index = analysis_ids
    clr = clr_transform(fractions, args.clr_pseudocount)
    zero_indicator = pd.DataFrame(
        {"HISTO_QC__ZERO_DETECTIONS": np.isclose(counts.sum(axis=1), 0.0).astype(int)},
        index=analysis_ids,
    )
    log_counts = np.log1p(counts)
    log_counts.columns = [column.replace("HISTO_COUNT__", "HISTO_LOGCOUNT__", 1) for column in counts.columns]

    frames = {
        "clinical": clinical_features,
        "histoplus_fractions": pd.concat([clr, zero_indicator], axis=1),
        "histoplus_log_counts": pd.concat([log_counts, zero_indicator], axis=1),
        "combined_fractions": pd.concat([clinical_features, clr, zero_indicator], axis=1),
    }
    frames = {name: frames[name] for name in feature_sets}
    for name, frame in frames.items():
        if frame.index.tolist() != analysis_ids:
            raise AnalysisError(f"Feature frame {name} lost deterministic sample ordering")

    if args.patient_id_column:
        groups = prepare_patient_groups(eligible_clinical[args.patient_id_column])
    else:
        groups = pd.Series(analysis_ids, index=analysis_ids)
    groups.index = analysis_ids
    evaluation_outcomes = group_outcomes(
        y.to_numpy(dtype=int),
        groups.to_numpy(dtype=str),
        context="Analysis evaluation units",
    )
    evaluation_outcome_counts = {
        "negative": int((evaluation_outcomes == 0).sum()),
        "positive": int((evaluation_outcomes == 1).sum()),
    }

    feature_manifest = list(clinical_manifest)
    for row, clr_name, count_name, fraction_name in zip(
        count_meta.itertuples(index=False), clr.columns, log_counts.columns, fractions.columns
    ):
        feature_manifest.extend(
            [
                {
                    "feature_name": clr_name,
                    "source": "histoplus_fraction",
                    "source_column": fraction_name,
                    "cell_type": str(row.cell_type),
                    "class_id": int(row.class_id),
                    "transformation": f"CLR(pseudocount={args.clr_pseudocount:g})",
                    "n_levels": "",
                },
                {
                    "feature_name": count_name,
                    "source": "histoplus_count",
                    "source_column": fraction_name.replace("HISTO_FRACTION__", "HISTO_COUNT__", 1),
                    "cell_type": str(row.cell_type),
                    "class_id": int(row.class_id),
                    "transformation": "log1p",
                    "n_levels": "",
                },
            ]
        )
    feature_manifest.append(
        {
            "feature_name": "HISTO_QC__ZERO_DETECTIONS",
            "source": "histoplus_qc",
            "source_column": "",
            "cell_type": "",
            "class_id": "",
            "transformation": "total_count_equals_zero",
            "n_levels": 2,
        }
    )

    raw_clinical = eligible_clinical.loc[:, args.clinical_feature].copy()
    raw_clinical.index = analysis_ids
    merged = pd.DataFrame(
        {
            "sample_id": analysis_ids,
            "outcome_label": eligible_clinical[args.outcome_column].map(normalize_text).to_numpy(),
            "outcome_binary": y.to_numpy(),
        }
    ).set_index("sample_id")
    merged = pd.concat([merged, raw_clinical, counts, fractions], axis=1)
    merged.index.name = "analysis_id"
    merged.reset_index().to_csv(output_dir / "analysis_cohort.csv", index=False)
    full_clinical = eligible_clinical.loc[:, clinical.columns].copy()
    full_clinical.index = analysis_ids
    full_linked = pd.concat([full_clinical, counts, fractions], axis=1)
    full_linked.insert(0, "analysis_id", analysis_ids)
    full_linked.to_csv(output_dir / "linked_clinical_histoplus_full.csv", index=False)
    all_clinical_roster.to_csv(
        output_dir / "linked_clinical_histoplus_all.csv", index=False
    )
    linkage.to_csv(output_dir / "linkage_audit.csv", index=False)
    pd.DataFrame(feature_manifest).drop_duplicates("feature_name").to_csv(
        output_dir / "feature_manifest.csv", index=False
    )
    missingness = pd.DataFrame(
        {
            "clinical_feature": args.clinical_feature,
            "n_missing": [int(raw_clinical[column].isna().sum()) for column in args.clinical_feature],
            "fraction_missing": [float(raw_clinical[column].isna().mean()) for column in args.clinical_feature],
        }
    ).sort_values("fraction_missing", ascending=False)
    missingness.to_csv(output_dir / "clinical_missingness.csv", index=False)

    stratification = univariate_stratification(
        eligible_clinical.loc[:, stratification_features].set_axis(analysis_ids),
        stratification_features,
        counts,
        fractions,
        y,
        inferential=not bool(args.patient_id_column and groups.nunique() < len(groups)),
    )
    stratification.to_csv(output_dir / "univariate_stratification.csv", index=False)

    predictions, fold_metrics, selections, importances, assignments = run_nested_cv(
        frames,
        y,
        groups,
        models,
        args.outer_splits,
        args.outer_repeats,
        args.inner_splits,
        args.seed,
        args.n_jobs,
        args.permutation_repeats,
        args.min_category_frequency,
        grouped=bool(args.patient_id_column),
    )
    summary_metrics, averaged_predictions = bootstrap_metric_intervals(
        predictions,
        fold_metrics,
        args.bootstrap_repeats,
        args.seed,
        groups=groups if args.patient_id_column else None,
    )
    incremental_value = paired_incremental_value(
        averaged_predictions, args.bootstrap_repeats, args.seed,
        groups=groups if args.patient_id_column else None,
    )
    predictions.to_csv(output_dir / "oof_predictions.csv", index=False)
    averaged_predictions.to_csv(output_dir / "oof_predictions_averaged.csv", index=False)
    fold_metrics.to_csv(output_dir / "fold_metrics.csv", index=False)
    summary_metrics.to_csv(output_dir / "summary_metrics.csv", index=False)
    incremental_value.to_csv(output_dir / "incremental_value.csv", index=False)
    selections.to_csv(output_dir / "model_selection.csv", index=False)
    importances.to_csv(output_dir / "heldout_permutation_importance.csv", index=False)
    assignments.to_csv(output_dir / "fold_assignments.csv", index=False)

    plot_cohort_flow(linkage, outcome_counts, output_dir)
    plot_histoplus_composition(fractions, count_meta, y, output_dir)
    plot_pca(clr, y, output_dir)
    evaluation_predictions = collapse_evaluation_unit_predictions(
        averaged_predictions, groups if args.patient_id_column else None
    )
    plot_model_results(summary_metrics, evaluation_predictions, output_dir)
    plot_calibration(evaluation_predictions, output_dir)
    plot_importance(importances, output_dir)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_type": "exploratory_binary_vital_status_classification",
        "clinical_sheet": sheet,
        "sample_id_column": args.sample_id_column,
        "patient_id_column": args.patient_id_column,
        "outcome_column": args.outcome_column,
        "outcome_mapping": {
            normalize_label(args.negative_label): 0,
            normalize_label(args.positive_label): 1,
        },
        "clinical_features": args.clinical_feature,
        "clinical_feature_types": clinical_feature_types,
        "stratification_features": stratification_features,
        "stratification_inferential": not bool(
            args.patient_id_column and groups.nunique() < len(groups)
        ),
        "feature_sets": feature_sets,
        "models": models,
        "cv": {
            "outer_splits": args.outer_splits,
            "outer_repeats": args.outer_repeats,
            "inner_splits": args.inner_splits,
            "grouped_by_patient": bool(args.patient_id_column),
            "n_independent_groups": int(groups.nunique()),
            "bootstrap_unit": "patient_group" if args.patient_id_column else "sample",
            "selection_scoring": "roc_auc",
            "classification_threshold": 0.5,
            "bootstrap_repeats": args.bootstrap_repeats,
            "permutation_repeats": args.permutation_repeats,
            "seed": args.seed,
        },
        "cohort": {
            "n_clinical_rows": int(len(clinical)),
            "n_histoplus_samples": int(len(counts)),
            "n_analysis_samples": int(len(y)),
            "evaluation_unit": "patient_group" if args.patient_id_column else "sample",
            "n_evaluation_units": int(len(evaluation_outcomes)),
            "n_negative_evaluation_units": evaluation_outcome_counts["negative"],
            "n_positive_evaluation_units": evaluation_outcome_counts["positive"],
            "n_negative": outcome_counts["negative"],
            "n_positive": outcome_counts["positive"],
            "n_linkage_excluded": int((~linkage["analysis_included"]).sum()),
        },
        "input_checksums_sha256": {
            label: sha256_file(path) for label, path in input_paths.items()
        },
        "dependency_versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy.__version__,
            "scikit_learn": sklearn.__version__,
            "matplotlib": matplotlib.__version__,
        },
        "limitations": [
            "Current vital status without a common fixed follow-up horizon is not a validated survival endpoint.",
            "No validated patient grouping key was used unless patient_id_column is recorded above.",
            "This small single-cohort analysis requires external or temporal validation before clinical use.",
            "Univariate p-values are descriptive and FDR-adjusted; they are not model feature-selection criteria.",
            "Raw sampled-tile counts are not full-slide extrapolations.",
        ],
        "privacy": {
            "patient_level_outputs": [
                "analysis_cohort.csv",
                "linked_clinical_histoplus_full.csv",
                "linked_clinical_histoplus_all.csv",
                "linkage_audit.csv",
                "oof_predictions.csv",
                "oof_predictions_averaged.csv",
                "fold_assignments.csv",
            ],
            "instruction": "Keep the output directory private and do not commit patient-level artifacts.",
        },
    }
    write_json(output_dir / "run_manifest.json", manifest)
    report = render_analysis_report(
        summary_metrics,
        incremental_value,
        stratification,
        manifest["cohort"],
        args,
    )
    (output_dir / "REPORT.md").write_text(report, encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        manifest = run(args)
    except AnalysisError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    cohort = manifest["cohort"]
    print("Clinical + HistoPLUS exploratory ML complete")
    print(
        f"  analysis samples: {cohort['n_analysis_samples']} "
        f"(positive={cohort['n_positive']}, negative={cohort['n_negative']})"
    )
    print(f"  output: {args.output_dir.expanduser().resolve()}")
    print("  WARNING: current status without fixed follow-up is not validated survival prediction")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
