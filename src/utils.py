"""I/O helpers for saving and loading artifacts."""

from pathlib import Path

import joblib
import pandas as pd


def save_parquet(df: pd.DataFrame, path: str) -> Path:
    """Persist a DataFrame as a Parquet file.

    Args:
        df: DataFrame to save.
        path: Destination file path.

    Returns:
        Resolved path of the saved file.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(dest, index=False)
    return dest


def load_parquet(path: str | Path) -> pd.DataFrame:
    """Load a DataFrame from a Parquet file.

    Args:
        path: Source file path.

    Returns:
        Loaded DataFrame.
    """
    return pd.read_parquet(path)


def save_model(model: object, path: str) -> Path:
    """Serialize a model to disk with joblib.

    Args:
        model: Fitted model object to serialize.
        path: Destination file path.

    Returns:
        Resolved path of the saved file.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, dest)
    return dest


def load_model(path: str | Path) -> object:
    """Deserialize a model from disk.

    Args:
        path: Source file path.

    Returns:
        Deserialized model object.
    """
    return joblib.load(path)
