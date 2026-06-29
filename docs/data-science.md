# Data science with qcell

qcell is an integrated environment for working with data: a fast, keyboard-first
spreadsheet with statistics, analysis, visualization, and scripting built in. You
can take a dataset from raw file to finished analysis without leaving the window —
and drop into Python or pandas the moment you want to. This page walks the
end-to-end workflow and maps common R/spreadsheet habits onto qcell.

Everything here works with qcell's **pure-stdlib core**; heavier libraries
(`scipy`, `statsmodels`, `pandas`, …) make some tools richer but are never
required — qcell degrades gracefully when they're absent.

## The workflow

### 1. Import

Open or import data in almost any tabular format — CSV/TSV, Excel `.xlsx`,
LibreOffice `.ods`, Parquet/Feather, SQLite, JSON / JSON Lines, R `data.frame`,
Jupyter notebooks, Markdown tables, or the native `.qcell` workbook. Large CSVs
stream in with type inference and an optional row cap. See
[file formats](file-formats.md). From the shell, `qcell data.csv` opens it
straight in the GUI.

### 2. Explore

- **Selection statistics** — select a range and the status bar shows Sum,
  Average, Min, Max, and Count instantly (see the [GUI guide](gui-guide.md)).
- **Formula functions** — ~150 of them, including the full aggregate and
  statistics families (`AVERAGE`, `MEDIAN`, `STDEV`, `VAR`, `PERCENTILE`,
  `QUARTILE`, `CORREL`, `COVAR`, `SKEW`, `KURT`, `RANK`, …) and statistical
  distributions (`NORMDIST`, `TDIST`, `FDIST`, `CHIDIST` and their inverses,
  `CONFIDENCE`). See the [formula reference](formula-reference.md).

### 3. Analyze

- The **Statistics / analysis tool** (Data → Analyze) runs descriptive statistics,
  linear regression, one- and two-sample t-tests, one-way ANOVA, correlation, and
  normality checks on the selected columns.
- **Distribution formulas** give you critical values and p-values directly in
  cells — e.g. `=TINV(0.05,10)` for a t critical value, `=CHIDIST(x,df)` for a
  chi-square tail probability.
- The **calculators** (RPN, graphing, and algebraic) sit beside the grid with a
  two-way value bridge — pull a cell into the calculator and send a result back.
  See [calculators](calculators.md).

### 4. Reshape & clean

- **Pivot / group-by** — summarize and cross-tabulate.
- **Recode / clean column** — normalize, map, and transform values.
- **Sort, filter, fill, and conditional formatting** for fast tidying.

See [data & analysis](data-analysis.md) for each tool.

### 5. Visualize

The built-in grapher renders scatter plots, histograms, regression lines, FFT and
spectrograms, PCA projections, clustering, and ROC curves — no matplotlib
required. The ML tool adds PCA, k-means, GMM, regression, decision trees/forests,
and naive Bayes.

### 6. Script & extend

- **Open selection in pandas** hands a range to a pandas `DataFrame` when you want
  the full library.
- The **embedded Python console** is wired to the live workbook.
- **Macros and UDFs** (`@macro`, `@register_function`) automate workflows and add
  your own formula functions; the **recorder** captures edits as a runnable macro.
  See [macros & scripting](macros-and-scripting.md). *(Macros and the console run
  untrusted code — only run scripts you trust.)*

### 7. Export & share

Save to any supported format (computed values or formulas), or convert headlessly
with `qcell convert in.csv out.parquet`. See the [CLI](cli.md).

## Coming from R or a spreadsheet?

| You want… | In qcell |
|-----------|----------|
| `mean`, `sd`, `median`, `quantile` | `AVERAGE`, `STDEV`, `MEDIAN`, `PERCENTILE`/`QUARTILE` |
| `lm()` / trendline | Analysis tool → regression, or `SLOPE`/`INTERCEPT`/`RSQ`/`FORECAST` |
| `t.test`, `aov`, `cor.test` | Analysis tool (t-tests, ANOVA, correlation), or `TTEST` |
| `pnorm`/`qnorm`, `pt`/`qt`, `pf`, `pchisq` | `NORMDIST`/`NORMINV`, `TDIST`/`TINV`, `FDIST`, `CHIDIST` |
| a data frame | Open selection in pandas, or the embedded Python console |
| `dplyr` group/summarize | Pivot / group-by |
| `ggplot`-style quick plots | The grapher (scatter/histogram/regression/…) |
| scripting a pipeline | Macros + UDFs, or the Python console |

## Optional dependencies

qcell works headless and offline with nothing but the standard library. Installing
`scipy`/`statsmodels`/`pingouin` deepens the analysis tool, `pandas` enables the
DataFrame hand-off and Parquet, and `openpyxl` enables Excel — but each is
optional, and qcell tells you (and falls back) when one is missing. Run
`qcell --deps` to see what's available. See [configuration](configuration.md).
