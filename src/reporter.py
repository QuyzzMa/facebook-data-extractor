from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import pandas as pd


def generate_markdown_report(
    df: pd.DataFrame,
    output_path: str | Path,
    source_url: str,
    csv_path: str | Path | None = None,
    xlsx_path: str | Path | None = None,
    notices: list[str] | None = None,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Facebook Data Extraction Report",
        "",
        f"- Source URL: `{source_url}`",
        f"- Generated at UTC: `{datetime.now(timezone.utc).isoformat()}`",
        f"- Rows: **{len(df):,}**",
        f"- Columns: **{len(df.columns):,}**",
        "",
    ]
    if notices:
        lines += ["## Access Notices", ""]
        lines += [f"- {notice}" for notice in notices]
        lines += [""]
    lines += [
        "## Data Schema",
        "",
        "| Column | Data Type | Missing |",
        "|---|---|---:|",
    ]
    for col in df.columns:
        lines.append(f"| `{col}` | `{df[col].dtype}` | {int(df[col].isna().sum()):,} |")

    lines += ["", "## Sample Records", ""]
    if df.empty:
        lines.append("> No records were parsed. Review the raw HTML and parser selectors before using the exports.")
    else:
        sample = df.head(5).copy()
        for col in sample.columns:
            sample[col] = sample[col].astype(str).str.replace("|", "\\|", regex=False).str.slice(0, 180)
        lines.append(sample.to_markdown(index=False))

    lines += [
        "",
        "## Output Files",
        "",
        f"- CSV: `{csv_path}`" if csv_path else "- CSV: not generated",
        f"- XLSX: `{xlsx_path}`" if xlsx_path else "- XLSX: not generated",
        f"- Markdown report: `{output_path}`",
        "",
        "## Data Quality Notes",
        "",
        "- Facebook DOM structures can change, so selectors may require maintenance.",
        "- A zero-record result is not evidence that the source has no posts; inspect the raw HTML.",
        "- Only collect data you are authorized to access and use.",
        "- Do not store passwords or authentication secrets in source code.",
    ]

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
