# Running, resume, and failures

Use:

- [Inspect and run your own slide](start-here/own-slides.md)
- [Resume an interrupted run](how-to/resume.md)
- [Failed sample versus biological zero](explanation/failed-vs-zero.md)
- [Troubleshooting](troubleshooting/index.md)

```bash
tumorquantai status /data/results
tumorquantai status /data/results --json
```

Resume is enabled by default. A failed or incomplete sample has no numeric
matrix column and remains in `sample_aggregation_audit.csv`; it is never
converted into a biological zero.
