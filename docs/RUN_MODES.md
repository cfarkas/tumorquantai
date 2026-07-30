# Smoke, fast, and full

The preset guide moved to
[Choose smoke, fast, or full](how-to/choose-preset.md).

| Preset | Processed tissue tiles |
| --- | --- |
| `smoke` | One selected slide, seeded 1%, fail fast |
| `fast` | Seeded 10% by default |
| `full` | 100% of detected tissue tiles |

Sampled raw counts are not whole-slide counts and must not be multiplied by
`100 / percent_slide`. Keep each preset in a separate output/work pair.
