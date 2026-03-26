import pandas as pd
from pathlib import Path
import argparse
import csv
from collections import Counter
import gcsfs


def detect_delimiter(sample: str) -> str:
    """
    Infer delimiter using csv.Sniffer first, then fall back to
    frequency analysis across lines for robustness.
    """
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="|~;\t,")
        return dialect.delimiter
    except csv.Error:
        pass

    # Fallback: count candidate delimiters per line and pick the most consistent one
    candidates = ["\t", "|", "~", ";", ","]
    lines = [l for l in sample.splitlines() if l.strip()]
    if not lines:
        return ","
 
    scores = {}
    for sep in candidates:
        counts = [line.count(sep) for line in lines]
        if counts and counts[0] > 0:
            # Score = consistency (low variance) + frequency
            avg = sum(counts) / len(counts)
            variance = sum((c - avg) ** 2 for c in counts) / len(counts)
            scores[sep] = (avg, -variance)  # higher avg + lower variance = better

    if scores:
        return max(scores, key=lambda s: (scores[s][0], scores[s][1]))

    return ","  # last resort



def is_gcs_path(path: str) -> bool:
    return path.startswith("gs://") or path.startswith("gsc://")


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
    """Try common encodings and return (sample_text, encoding)."""
    for enc in ["utf-8-sig", "utf-8", "latin-1", "cp1252"]:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read(n_bytes), enc
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Encoding detection failed: {path}")



def load_data(path: str) -> pd.DataFrame:
    if is_gcs_path(path):
        return _load_gcs(path)
    return _load_local(Path(path))


def _load_gcs(path: str) -> pd.DataFrame:

    suffix = path.rsplit(".", 1)[-1].lower()
    if suffix == "xlsx":
        fs = gcsfs.GCSFileSystem()
        with fs.open(path, "rb") as f:
            return pd.read_excel(f)

    if suffix in ("txt", "csv"):
        sample, encoding = read_sample_gcs(path)
        sep = detect_delimiter(sample)
        print(f"Detected delimiter: {repr(sep)}, encoding: {encoding}")
        fs = gcsfs.GCSFileSystem()
        with fs.open(path, "rb") as f:
            return pd.read_csv(
                f,
                sep=sep,
                decimal=",",
                encoding=encoding,
                low_memory=False,
                dtype=str,
                on_bad_lines="warn",
            )

    raise ValueError(f"Unsupported file type: .{suffix}")



def _load_local(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")
    if path.suffix == ".xlsx":
        return pd.read_excel(path)
    if path.suffix in (".txt", ".csv"):
        sample, encoding = read_sample_local(path)
        sep = detect_delimiter(sample)
        print(f"Detected delimiter: {repr(sep)}, encoding: {encoding}")
        return pd.read_csv(
            path,
            sep=sep,
            decimal=",",
            encoding=encoding,
            low_memory=False,
            dtype=str,
            on_bad_lines="warn",
        )
    raise ValueError(f"Unsupported file type: {path.suffix}")


def main():
    parser = argparse.ArgumentParser(description="Load a dataset (local or GCS)")
    parser.add_argument("file", type=str, help="Local path or gs://bucket/file.csv")
    args = parser.parse_args()

    try:
        df = load_data(args.file)
        print(f"\nLoaded {len(df)} rows and {len(df.columns)} columns.")
        print("\nSample data:")
        print(df.sample(min(5, len(df))))
    except Exception as e:
        print(f"Error loading data: {e}")


if __name__ == "__main__":
    main()