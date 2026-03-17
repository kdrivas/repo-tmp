"""I/O helpers for saving and loading datasets and models."""

from pathlib import Path

import joblib
import pandas as pd


def save_parquet(df: pd.DataFrame, path: str) -> str:
    """Save a DataFrame to a Parquet file.

    Args:
        df: DataFrame to save.
        path: Destination file path.

    Returns:
        The path the file was saved to.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def load_parquet(path: str) -> pd.DataFrame:
    """Load a DataFrame from a Parquet file.

    Args:
        path: Source file path.

    Returns:
        Loaded DataFrame.
    """
    return pd.read_parquet(path)


def save_model(model: object, path: str) -> str:
    """Serialize a model to disk with joblib.

    Args:
        model: Model object to serialize.
        path: Destination file path.

    Returns:
        The path the file was saved to.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    return path


def load_model(path: str) -> object:
    """Deserialize a model from disk with joblib.

    Args:
        path: Source file path.

    Returns:
        Deserialized model object.
    """
    return joblib.load(path)
