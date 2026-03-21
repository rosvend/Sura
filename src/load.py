import pandas as pd
from pathlib import Path


def detect_delimiter(sample: str) -> str:
    """Infer delimiter based on first line."""
    if '\t' in sample:
        return '\t'
    elif '~' in sample:
        return '~'
    else:
        raise ValueError("Unknown delimiter")


def load_data(path: str) -> pd.DataFrame:
    """Data loader with delimiter detection and validation."""

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")

    if path.suffix == ".xlsx":
        return pd.read_excel(path)

    elif path.suffix == ".txt":
        # Read a small sample to detect delimiter
        with open(path, "r", encoding="utf-8") as f:
            sample = f.readline()

        sep = detect_delimiter(sample)

        df = pd.read_csv(
            path,
            sep=sep,
            decimal=",", 
            encoding="utf-8"
        )

        # Basic validation
        if df.shape[1] < 10:
            raise ValueError("Too few columns detected — likely wrong delimiter")

        return df

    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")