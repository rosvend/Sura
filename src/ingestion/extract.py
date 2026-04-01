import polars as pl
from pathlib import Path
import argparse
import csv
import io
import gcsfs
import time


def detect_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="|~;\t,")
        return dialect.delimiter
    except csv.Error:
        pass

    candidates = ["\t", "|", "~", ";", ","]
    lines = [l for l in sample.splitlines() if l.strip()]
    if not lines:
        return ","

    scores = {}
    for sep in candidates:
        counts = [line.count(sep) for line in lines]
        if counts and counts[0] > 0:
            avg = sum(counts) / len(counts)
            variance = sum((c - avg) ** 2 for c in counts) / len(counts)
            scores[sep] = (avg, -variance)

    if scores:
        return max(scores, key=lambda s: (scores[s][0], scores[s][1]))

    return ","


def is_gcs_path(path: str) -> bool:
    return path.startswith("gs://") or path.startswith("gcs://")


def read_sample_gcs(path: str, n_bytes: int = 8192) -> tuple[str, str]:
    fs = gcsfs.GCSFileSystem()
    for enc in ["utf-8-sig", "utf-8", "latin-1", "cp1252"]:
        try:
            with fs.open(path, "rb") as f:
                raw = f.read(n_bytes)
            return raw.decode(encoding=enc), enc
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Encoding detection failed: {path}")


def read_sample_local(path: Path, n_bytes: int = 8192) -> tuple[str, str]:
    for enc in ["utf-8-sig", "utf-8", "latin-1", "cp1252"]:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read(n_bytes), enc
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Encoding detection failed: {path}")


def load_data(path: str) -> pl.DataFrame:
    if is_gcs_path(path):
        return _load_gcs(path)
    return _load_local(Path(path))


def _read_all_sheets(source: "io.BytesIO | Path") -> pl.DataFrame:
    """Read all sheets from an Excel file, tag each row with _RED_ORIGEN and concatenate."""
    import openpyxl

    # For BytesIO we need the raw bytes so we can re-read the source multiple times
    if isinstance(source, io.BytesIO):
        raw = source.getvalue()
        get_source = lambda: io.BytesIO(raw)
    else:
        get_source = lambda: source

    wb = openpyxl.load_workbook(get_source(), read_only=True)
    sheet_names = wb.sheetnames
    wb.close()

    frames = []
    for sheet in sheet_names:
        df = pl.read_excel(get_source(), sheet_name=sheet, infer_schema_length=0)
        df = df.with_columns(pl.lit(sheet).alias("_RED_ORIGEN"))
        frames.append(df)
    return pl.concat(frames, how="diagonal_relaxed")


def _load_gcs(path: str) -> pl.DataFrame:
    suffix = path.rsplit(".", 1)[-1].lower()
    fs = gcsfs.GCSFileSystem()

    if suffix == "xlsx":
        with fs.open(path, "rb") as f:
            raw = io.BytesIO(f.read())
        return _read_all_sheets(raw)

    if suffix in ("txt", "csv"):
        sample, encoding = read_sample_gcs(path)
        sep = detect_delimiter(sample)
        print(f"Detected delimiter: {repr(sep)}, encoding: {encoding}")
        with fs.open(path, "rb") as f:
            raw = f.read()                      # read full file into memory
        return pl.read_csv(
            io.BytesIO(raw),
            separator=sep,
            encoding=encoding,
            infer_schema_length=0,              # all columns as strings
            ignore_errors=True,
        )

    raise ValueError(f"Unsupported file type: .{suffix}")


def _load_local(path: Path) -> pl.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")

    if path.suffix == ".xlsx":
        return _read_all_sheets(path)

    if path.suffix in (".txt", ".csv"):
        sample, encoding = read_sample_local(path)
        sep = detect_delimiter(sample)
        print(f"Detected delimiter: {repr(sep)}, encoding: {encoding}")
        return pl.read_csv(
            path,
            separator=sep,
            encoding=encoding,
            infer_schema_length=0,
            ignore_errors=True,
        )

    raise ValueError(f"Unsupported file type: {path.suffix}")


def main():
    parser = argparse.ArgumentParser(description="Load a dataset (local or GCS)")
    parser.add_argument("file", type=str, help="Local path or gs://bucket/file.csv")
    args = parser.parse_args()

    try:
        start_time = time.time()
        df = load_data(args.file)
        print(f"\nLoaded {df.shape[0]} rows and {df.shape[1]} columns.")
        print("\nSample data:")
        print(df.sample(n=min(5, df.shape[0])))
        print(f"\nExecution time: {time.time() - start_time:.2f} seconds")
    except Exception as e:
        print(f"Error loading data: {e}")


if __name__ == "__main__":
    main()