from __future__ import annotations

from pathlib import Path
import pandas as pd


def export_csv(df: pd.DataFrame, path: str | Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def export_xlsx(df: pd.DataFrame, path: str | Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    export_df = df.copy()

    for column in export_df.columns:
        series = export_df[column]
        if isinstance(series.dtype, pd.DatetimeTZDtype):
            export_df[column] = series.astype(str)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="facebook_posts")
        ws = writer.book["facebook_posts"]
        for column_cells in ws.columns:
            max_length = 0
            column_letter = column_cells[0].column_letter
            for cell in column_cells[:1000]:
                value = "" if cell.value is None else str(cell.value)
                max_length = max(max_length, len(value))
            ws.column_dimensions[column_letter].width = min(max(max_length + 2, 10), 60)
    return path
