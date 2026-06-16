# Building the PDF reports

From the repository root:

```bash
cd docs/reports
pdflatex trading_agent_research_report.tex
pdflatex trading_agent_research_report.tex
```

Output: `trading_agent_research_report.pdf`

Requires a LaTeX distribution with `booktabs`, `hyperref`, `csquotes`,
`cleveref`, and `xcolor` (e.g. TinyTeX, MacTeX, TeX Live).
