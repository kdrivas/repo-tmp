"""Dummy dataset generators for the example pipelines."""

import numpy as np
import pandas as pd


def generate_classification_dataset(
    n_samples: int = 200, n_features: int = 5, seed: int = 42
) -> pd.DataFrame:
    """Generate a synthetic binary classification dataset.

    Args:
        n_samples: Number of samples.
        n_features: Number of input features.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with feature columns and a binary ``target`` column.
    """
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n_samples, n_features))
    y = (X[:, 0] + X[:, 1] > 0).astype(int)
    df = pd.DataFrame(X, columns=[f"feature_{i}" for i in range(n_features)])
    df["target"] = y
    return df


def generate_regression_dataset(
    n_samples: int = 200, n_features: int = 5, seed: int = 42
) -> pd.DataFrame:
    """Generate a synthetic regression dataset.

    Args:
        n_samples: Number of samples.
        n_features: Number of input features.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with feature columns and a continuous ``target`` column.
    """
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n_samples, n_features))
    y = X[:, 0] * 2.5 + X[:, 1] * -1.0 + rng.standard_normal(n_samples) * 0.5
    df = pd.DataFrame(X, columns=[f"feature_{i}" for i in range(n_features)])
    df["target"] = y
    return df
