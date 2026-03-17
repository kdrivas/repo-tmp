"""Complete pipeline with all steps using LinearRegression."""

from typing import Any

from mlops_lib.client.mlflow import MLflowContext
from mlops_lib.pipelines import (
    EvalConfig,
    IngestionConfig,
    MLDataset,
    MLMetric,
    MLModel,
    ModelSelectionConfig,
    PostprocessConfig,
    PreprocessConfig,
    SplitConfig,
    TrainConfig,
)
from mlops_lib.pipelines.base.types import DatasetSplit
from mlops_lib.pipelines.flyte import FlytePipeline
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error

from src.data import generate_regression_dataset
from src.utils import load_model, load_parquet, save_model, save_parquet


class CompletePipeline(FlytePipeline):
    """Complete pipeline with all steps.

    Steps: ingestion, preprocess, split, postprocess, model_selection, train, and evaluate.
    """

    def __init__(self) -> None:
        super().__init__(
            name="dummy_complete",
            container_image="src:latest",
            experiment_name="dummy-regression",
            run_name="dummy-regression-run",
            ingestion_config=IngestionConfig(),
            preprocess_config=PreprocessConfig(target_column="target"),
            split_config=SplitConfig(test_size=0.2, val_size=0.1, random_state=42),
            model_selection_config=ModelSelectionConfig(),
            train_config=TrainConfig(),
            eval_config=EvalConfig(),
        )

    def ingestion(self, _config: IngestionConfig) -> MLDataset:
        """Generate a synthetic regression dataset and persist it.

        Returns:
            MLDataset pointing to the raw data file.
        """
        df = generate_regression_dataset(n_samples=300, n_features=5)
        path = save_parquet(df, "/tmp/regression/raw.parquet")
        return MLDataset(path=path)

    def preprocess(self, data: MLDataset, config: PreprocessConfig) -> MLDataset:
        """Apply z-score normalization to all feature columns.

        Args:
            data: Raw MLDataset as returned by :meth:`ingestion`.
            config: Preprocessing configuration with ``target_column``.

        Returns:
            MLDataset pointing to the normalized data file.
        """
        df = load_parquet(data.path)
        feature_cols = [c for c in df.columns if c != config.target_column]
        df[feature_cols] = (df[feature_cols] - df[feature_cols].mean()) / df[feature_cols].std()
        path = save_parquet(df, "/tmp/regression/preprocessed.parquet")
        return MLDataset(path=path)

    def split(self, data: MLDataset, config: SplitConfig) -> dict[str, MLDataset]:
        """Split the dataset into train, val, and test sets.

        Args:
            data: Preprocessed MLDataset as returned by :meth:`preprocess`.
            config: Split configuration with ``test_size``, ``val_size``, and ``random_state``.

        Returns:
            Dict with ``train``, ``val``, and ``test`` MLDataset entries.
        """
        df = (
            load_parquet(data.path)
            .sample(frac=1, random_state=config.random_state)
            .reset_index(drop=True)
        )
        n = len(df)
        n_test = int(n * config.test_size)
        n_val = int(n * config.val_size)

        return {
            "train": MLDataset(
                path=save_parquet(df.iloc[n_test + n_val :], "/tmp/regression/train.parquet"),
                data_split=DatasetSplit.TRAIN,
            ),
            "val": MLDataset(
                path=save_parquet(df.iloc[n_test : n_test + n_val], "/tmp/regression/val.parquet"),
                data_split=DatasetSplit.VAL,
            ),
            "test": MLDataset(
                path=save_parquet(df.iloc[:n_test], "/tmp/regression/test.parquet"),
                data_split=DatasetSplit.TEST,
            ),
        }

    def postprocess(
        self, data_splits: dict[str, MLDataset], _config: PostprocessConfig
    ) -> dict[str, MLDataset]:
        """Pass-through step — no additional postprocessing needed.

        Args:
            data_splits: Dict of MLDatasets as returned by :meth:`split`.

        Returns:
            The same data splits unchanged.
        """
        return data_splits

    def model_selection(
        self,
        data_splits: dict[str, MLDataset],
        _config: ModelSelectionConfig,
        _mlflow_context: MLflowContext,
    ) -> dict[str, Any]:
        """Select the best ``fit_intercept`` flag using the validation set.

        Args:
            data_splits: Dict of MLDatasets as returned by :meth:`postprocess`.

        Returns:
            Dict with the best hyperparameters found.
        """
        train_df = load_parquet(data_splits["train"].path)
        val_df = load_parquet(data_splits["val"].path)

        x_train = train_df.drop(columns=["target"]).to_numpy()
        y_train = train_df["target"].to_numpy()
        x_val = val_df.drop(columns=["target"]).to_numpy()
        y_val = val_df["target"].to_numpy()

        best_params: dict[str, Any] = {}
        best_mse = float("inf")

        for fit_intercept in [True, False]:
            model = LinearRegression(fit_intercept=fit_intercept)
            model.fit(x_train, y_train)
            mse = float(mean_squared_error(y_val, model.predict(x_val)))
            if mse < best_mse:
                best_mse = mse
                best_params = {"fit_intercept": fit_intercept}

        return best_params

    def train(
        self,
        data_splits: dict[str, MLDataset],
        ml_best_parameters: dict[str, Any],
        _config: TrainConfig,
        _mlflow_context: MLflowContext,
    ) -> MLModel:
        """Fit a linear regression model using the best hyperparameters.

        Args:
            data_splits: Dict of MLDatasets as returned by :meth:`postprocess`.
            ml_best_parameters: Best parameters from :meth:`model_selection`.

        Returns:
            MLModel pointing to the saved model artifact.
        """
        df = load_parquet(data_splits["train"].path)
        X = df.drop(columns=["target"]).to_numpy()
        y = df["target"].to_numpy()

        params = ml_best_parameters or {"fit_intercept": True}
        model = LinearRegression(**params)
        model.fit(X, y)

        path = save_model(model, "/tmp/regression/model.joblib")
        return MLModel(path=path, name="linear_regression", flavor="sklearn", params=params)

    def evaluate(
        self,
        data_splits: dict[str, MLDataset],
        model: MLModel,
        _config: EvalConfig,
        _mlflow_context: MLflowContext,
    ) -> list[MLMetric]:
        """Compute MSE on train, val, and test splits.

        Args:
            data_splits: Dict of MLDatasets as returned by :meth:`postprocess`.
            model: Trained MLModel as returned by :meth:`train`.

        Returns:
            List of MLMetric with MSE per split.
        """
        reg = load_model(model.path)
        split_enum = {
            "train": DatasetSplit.TRAIN,
            "val": DatasetSplit.VAL,
            "test": DatasetSplit.TEST,
        }
        metrics = []
        for name, dataset in data_splits.items():
            df = load_parquet(dataset.path)
            X = df.drop(columns=["target"]).to_numpy()
            y = df["target"].to_numpy()
            mse = float(mean_squared_error(y, reg.predict(X)))
            metrics.append(MLMetric(name=f"mse_{name}", value=mse, data_split=split_enum[name]))
        return metrics


complete_pipeline = CompletePipeline()
