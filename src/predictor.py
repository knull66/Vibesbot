"""
Módulo de predicción con IA para señales de trading.

Implementa generación de features financieras y modelos de clasificación
(XGBoost/LightGBM) para predecir la dirección del precio.
"""
import asyncio
import pickle
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Union
import numpy as np
import pandas as pd

try:
    import xgboost as xgb
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

try:
    import ta
    HAS_TA = True
except ImportError:
    HAS_TA = False

from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

from .config import PredictionConfig
from .data_stream import DataStream, OrderBook
from .utils.logger import get_logger


logger = get_logger("predictor")


class Signal(Enum):
    """Señales de trading posibles."""
    UP = "UP"
    DOWN = "DOWN"
    WAIT = "WAIT"


class ModelType(Enum):
    """Tipos de modelo soportados."""
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"


@dataclass
class Prediction:
    """Resultado de una predicción."""
    
    signal: Signal
    confidence: float
    probability_up: float
    probability_down: float
    features: Optional[dict] = None
    timestamp: int = 0
    
    @property
    def is_tradeable(self) -> bool:
        """True si la predicción tiene suficiente confianza para operar."""
        return self.signal != Signal.WAIT


class FeatureGenerator:
    """
    Generador de features financieras para el modelo de predicción.
    
    Incluye:
    - Indicadores técnicos de alta frecuencia
    - Métricas de order flow y liquidez
    - Features de microestructura de mercado
    """
    
    def __init__(self, config: Optional[PredictionConfig] = None):
        self.config = config or PredictionConfig()
        
    def generate_features(
        self,
        df_1m: pd.DataFrame,
        df_5m: pd.DataFrame,
        order_book: Optional[OrderBook] = None,
        trade_flow: Optional[dict] = None
    ) -> pd.DataFrame:
        """
        Genera todas las features para la predicción.
        
        Args:
            df_1m: DataFrame con velas de 1 minuto
            df_5m: DataFrame con velas de 5 minutos
            order_book: Estado actual del order book
            trade_flow: Métricas de flujo de transacciones
            
        Returns:
            DataFrame con una fila conteniendo todas las features
        """
        features = {}
        
        if self.config.use_technical_indicators and HAS_TA:
            features.update(self._generate_technical_features(df_1m, "1m"))
            features.update(self._generate_technical_features(df_5m, "5m"))
        
        features.update(self._generate_price_features(df_1m, "1m"))
        features.update(self._generate_price_features(df_5m, "5m"))
        
        features.update(self._generate_volume_features(df_1m, "1m"))
        features.update(self._generate_volume_features(df_5m, "5m"))
        
        if self.config.use_order_book and order_book:
            features.update(self._generate_orderbook_features(order_book))
        
        if self.config.use_trade_flow and trade_flow:
            features.update(self._generate_tradeflow_features(trade_flow))
        
        features.update(self._generate_momentum_features(df_1m, df_5m))
        
        features.update(self._generate_time_features())
        
        return pd.DataFrame([features])
    
    def _generate_technical_features(self, df: pd.DataFrame, suffix: str) -> dict:
        """Genera features de indicadores técnicos."""
        features = {}
        
        if len(df) < 30:
            return features
        
        try:
            close = df["close"].astype(float)
            high = df["high"].astype(float)
            low = df["low"].astype(float)
            volume = df["volume"].astype(float)
            
            rsi_14 = ta.momentum.RSIIndicator(close, window=14).rsi()
            if len(rsi_14.dropna()) > 0:
                features[f"rsi_14_{suffix}"] = rsi_14.iloc[-1]
            
            rsi_7 = ta.momentum.RSIIndicator(close, window=7).rsi()
            if len(rsi_7.dropna()) > 0:
                features[f"rsi_7_{suffix}"] = rsi_7.iloc[-1]
            
            macd = ta.trend.MACD(close)
            macd_line = macd.macd()
            macd_signal = macd.macd_signal()
            macd_hist = macd.macd_diff()
            
            if len(macd_line.dropna()) > 0:
                features[f"macd_{suffix}"] = macd_line.iloc[-1]
            if len(macd_signal.dropna()) > 0:
                features[f"macd_signal_{suffix}"] = macd_signal.iloc[-1]
            if len(macd_hist.dropna()) > 0:
                features[f"macd_hist_{suffix}"] = macd_hist.iloc[-1]
                if len(macd_hist.dropna()) >= 2:
                    features[f"macd_hist_delta_{suffix}"] = macd_hist.dropna().iloc[-1] - macd_hist.dropna().iloc[-2]
            
            bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
            bb_high = bb.bollinger_hband()
            bb_low = bb.bollinger_lband()
            bb_mid = bb.bollinger_mavg()
            bb_width = bb.bollinger_wband()
            bb_pband = bb.bollinger_pband()
            
            if len(bb_high.dropna()) > 0:
                features[f"bb_high_{suffix}"] = bb_high.iloc[-1]
                features[f"bb_low_{suffix}"] = bb_low.iloc[-1]
                features[f"bb_mid_{suffix}"] = bb_mid.iloc[-1]
                features[f"bb_width_{suffix}"] = bb_width.iloc[-1]
                features[f"bb_pband_{suffix}"] = bb_pband.iloc[-1]
            
            if len(df) >= 14:
                stoch = ta.momentum.StochasticOscillator(high, low, close, window=14, smooth_window=3)
                stoch_k = stoch.stoch()
                stoch_d = stoch.stoch_signal()
                if len(stoch_k.dropna()) > 0:
                    features[f"stoch_k_{suffix}"] = stoch_k.iloc[-1]
                    features[f"stoch_d_{suffix}"] = stoch_d.iloc[-1]
            
            atr = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
            if len(atr.dropna()) > 0:
                features[f"atr_{suffix}"] = atr.iloc[-1]
            
            if len(df) >= 14:
                adx = ta.trend.ADXIndicator(high, low, close, window=14).adx()
                if len(adx.dropna()) > 0:
                    features[f"adx_{suffix}"] = adx.iloc[-1]
            
            if len(df) >= 20:
                cci = ta.trend.CCIIndicator(high, low, close, window=20).cci()
                if len(cci.dropna()) > 0:
                    features[f"cci_{suffix}"] = cci.iloc[-1]
            
            if len(df) >= 14:
                mfi = ta.volume.MFIIndicator(high, low, close, volume, window=14).money_flow_index()
                if len(mfi.dropna()) > 0:
                    features[f"mfi_{suffix}"] = mfi.iloc[-1]
                    
        except Exception as e:
            pass
        
        return features
    
    def _generate_price_features(self, df: pd.DataFrame, suffix: str) -> dict:
        """Genera features basadas en precio."""
        features = {}
        
        if len(df) < 2:
            return features
        
        for period in [1, 3, 5, 10, 20]:
            if len(df) >= period + 1:
                returns = (df["close"].iloc[-1] - df["close"].iloc[-period-1]) / df["close"].iloc[-period-1]
                features[f"return_{period}_{suffix}"] = returns
        
        for period in [5, 10, 20, 50]:
            if len(df) >= period:
                sma = df["close"].rolling(period).mean().iloc[-1]
                features[f"sma_{period}_{suffix}"] = sma
                features[f"price_sma_{period}_ratio_{suffix}"] = df["close"].iloc[-1] / sma
        
        for period in [5, 10, 20]:
            if len(df) >= period:
                ema = df["close"].ewm(span=period).mean().iloc[-1]
                features[f"ema_{period}_{suffix}"] = ema
                features[f"price_ema_{period}_ratio_{suffix}"] = df["close"].iloc[-1] / ema
        
        if len(df) >= 2:
            features[f"body_size_{suffix}"] = abs(df["close"].iloc[-1] - df["open"].iloc[-1])
            features[f"upper_shadow_{suffix}"] = df["high"].iloc[-1] - max(df["close"].iloc[-1], df["open"].iloc[-1])
            features[f"lower_shadow_{suffix}"] = min(df["close"].iloc[-1], df["open"].iloc[-1]) - df["low"].iloc[-1]
            features[f"candle_range_{suffix}"] = df["high"].iloc[-1] - df["low"].iloc[-1]
        
        if len(df) >= 20:
            high_20 = df["high"].rolling(20).max().iloc[-1]
            low_20 = df["low"].rolling(20).min().iloc[-1]
            features[f"price_position_{suffix}"] = (df["close"].iloc[-1] - low_20) / (high_20 - low_20 + 1e-10)
        
        return features
    
    def _generate_volume_features(self, df: pd.DataFrame, suffix: str) -> dict:
        """Genera features basadas en volumen."""
        features = {}
        
        if len(df) < 2:
            return features
        
        for period in [5, 10, 20]:
            if len(df) >= period:
                vol_sma = df["volume"].rolling(period).mean().iloc[-1]
                features[f"vol_sma_{period}_{suffix}"] = vol_sma
                features[f"vol_ratio_{period}_{suffix}"] = df["volume"].iloc[-1] / (vol_sma + 1e-10)
        
        if "taker_buy_base" in df.columns and len(df) >= 1:
            buy_ratio = df["taker_buy_base"].iloc[-1] / (df["volume"].iloc[-1] + 1e-10)
            features[f"taker_buy_ratio_{suffix}"] = buy_ratio
        
        if "quote_volume" in df.columns and len(df) >= 5:
            features[f"avg_trade_size_{suffix}"] = df["quote_volume"].iloc[-1] / (df["trades"].iloc[-1] + 1)
        
        if len(df) >= 5:
            obv = (np.sign(df["close"].diff()) * df["volume"]).cumsum()
            features[f"obv_change_{suffix}"] = obv.iloc[-1] - obv.iloc[-5]
        
        return features
    
    def _generate_orderbook_features(self, order_book: OrderBook) -> dict:
        """Genera features del libro de órdenes."""
        features = {}
        
        for levels in [5, 10, 20]:
            imbalance = order_book.calculate_imbalance(levels)
            features[f"obi_{levels}"] = imbalance
        
        if order_book.spread:
            features["spread_abs"] = order_book.spread
            features["spread_pct"] = order_book.spread_percent
        
        if order_book.mid_price:
            features["mid_price"] = order_book.mid_price
            
            weighted_mid = order_book.calculate_weighted_mid_price()
            if weighted_mid:
                features["weighted_mid_price"] = weighted_mid
                features["mid_price_skew"] = (weighted_mid - order_book.mid_price) / order_book.mid_price
        
        bid_depth = sum(b.quantity for b in order_book.bids[:10])
        ask_depth = sum(a.quantity for a in order_book.asks[:10])
        features["total_depth"] = bid_depth + ask_depth
        features["depth_imbalance"] = (bid_depth - ask_depth) / (bid_depth + ask_depth + 1e-10)
        
        return features
    
    def _generate_tradeflow_features(self, trade_flow: dict) -> dict:
        """Genera features del flujo de transacciones."""
        return {
            "tf_buy_volume": trade_flow.get("buy_volume", 0),
            "tf_sell_volume": trade_flow.get("sell_volume", 0),
            "tf_net_flow": trade_flow.get("net_flow", 0),
            "tf_flow_imbalance": trade_flow.get("flow_imbalance", 0),
            "tf_buy_count": trade_flow.get("buy_count", 0),
            "tf_sell_count": trade_flow.get("sell_count", 0),
            "tf_vwap": trade_flow.get("vwap", 0),
        }
    
    def _generate_momentum_features(self, df_1m: pd.DataFrame, df_5m: pd.DataFrame) -> dict:
        """Genera features de momentum cruzado entre timeframes."""
        features = {}
        
        if len(df_1m) >= 5 and len(df_5m) >= 2:
            mom_1m = (df_1m["close"].iloc[-1] - df_1m["close"].iloc[-5]) / df_1m["close"].iloc[-5]
            mom_5m = (df_5m["close"].iloc[-1] - df_5m["close"].iloc[-2]) / df_5m["close"].iloc[-2]
            
            features["momentum_1m"] = mom_1m
            features["momentum_5m"] = mom_5m
            features["momentum_alignment"] = 1 if np.sign(mom_1m) == np.sign(mom_5m) else -1
            features["momentum_divergence"] = mom_1m - mom_5m
        
        return features
    
    def _generate_time_features(self) -> dict:
        """Genera features temporales."""
        now = datetime.utcnow()
        
        return {
            "hour": now.hour,
            "minute": now.minute,
            "day_of_week": now.weekday(),
            "is_weekend": 1 if now.weekday() >= 5 else 0,
            "is_asia_session": 1 if 0 <= now.hour < 8 else 0,
            "is_london_session": 1 if 7 <= now.hour < 16 else 0,
            "is_ny_session": 1 if 13 <= now.hour < 22 else 0,
        }


class PredictionModel:
    """
    Modelo de clasificación para predecir dirección del precio.
    
    Soporta XGBoost y LightGBM con entrenamiento y predicción en tiempo real.
    """
    
    def __init__(
        self,
        config: Optional[PredictionConfig] = None,
        model_type: ModelType = ModelType.LIGHTGBM
    ):
        self.config = config or PredictionConfig()
        self.model_type = model_type
        
        self.model: Optional[Any] = None
        self.scaler: Optional[StandardScaler] = None
        self.feature_names: list[str] = []
        
        self._is_trained = False
    
    def train(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        validation_split: float = 0.2
    ) -> dict:
        """
        Entrena el modelo con los datos proporcionados.
        
        Args:
            X: Features de entrenamiento
            y: Labels (1 para UP, 0 para DOWN)
            validation_split: Proporción de datos para validación
            
        Returns:
            Diccionario con métricas de entrenamiento
        """
        self.feature_names = list(X.columns)
        
        X_clean = X.replace([np.inf, -np.inf], np.nan).fillna(0)
        
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X_clean)
        
        split_idx = int(len(X) * (1 - validation_split))
        X_train, X_val = X_scaled[:split_idx], X_scaled[split_idx:]
        y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]
        
        if self.model_type == ModelType.LIGHTGBM and HAS_LIGHTGBM:
            self.model = lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.05,
                num_leaves=31,
                min_child_samples=20,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=0.1,
                reg_lambda=0.1,
                random_state=42,
                verbosity=-1
            )
        elif self.model_type == ModelType.XGBOOST and HAS_XGBOOST:
            self.model = xgb.XGBClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=0.1,
                reg_lambda=0.1,
                random_state=42,
                use_label_encoder=False,
                eval_metric="logloss"
            )
        else:
            raise ValueError(f"Model type {self.model_type} not available")
        
        self.model.fit(X_train, y_train)
        self._is_trained = True
        
        train_pred = self.model.predict(X_train)
        val_pred = self.model.predict(X_val)
        val_proba = self.model.predict_proba(X_val)[:, 1]
        
        metrics = {
            "train_accuracy": accuracy_score(y_train, train_pred),
            "val_accuracy": accuracy_score(y_val, val_pred),
            "val_precision": precision_score(y_val, val_pred, zero_division=0),
            "val_recall": recall_score(y_val, val_pred, zero_division=0),
            "val_f1": f1_score(y_val, val_pred, zero_division=0),
            "samples_train": len(y_train),
            "samples_val": len(y_val),
        }
        
        logger.info(f"Model trained - Train Acc: {metrics['train_accuracy']:.4f}, Val Acc: {metrics['val_accuracy']:.4f}")
        
        return metrics
    
    def predict(self, X: pd.DataFrame) -> Prediction:
        """
        Realiza una predicción con el modelo.
        
        Args:
            X: DataFrame con features (una fila)
            
        Returns:
            Objeto Prediction con la señal y confianza
        """
        if not self._is_trained:
            logger.warning("Model not trained, returning WAIT signal")
            return Prediction(
                signal=Signal.WAIT,
                confidence=0.0,
                probability_up=0.5,
                probability_down=0.5
            )
        
        X_aligned = X.reindex(columns=self.feature_names, fill_value=0)
        X_clean = X_aligned.replace([np.inf, -np.inf], np.nan).fillna(0)
        X_scaled = self.scaler.transform(X_clean)
        
        proba = self.model.predict_proba(X_scaled)[0]
        prob_down = proba[0]
        prob_up = proba[1]
        
        confidence = max(prob_up, prob_down)
        
        if confidence < self.config.confidence_threshold:
            signal = Signal.WAIT
        else:
            signal = Signal.UP if prob_up > prob_down else Signal.DOWN
        
        return Prediction(
            signal=signal,
            confidence=confidence,
            probability_up=prob_up,
            probability_down=prob_down,
            features=X.to_dict(orient="records")[0] if len(X) > 0 else None,
            timestamp=int(datetime.utcnow().timestamp() * 1000)
        )
    
    def save(self, model_path: Optional[str] = None, scaler_path: Optional[str] = None) -> None:
        """Guarda el modelo y scaler a disco."""
        model_path = model_path or self.config.model_path
        scaler_path = scaler_path or self.config.scaler_path
        
        Path(model_path).parent.mkdir(parents=True, exist_ok=True)
        Path(scaler_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(model_path, "wb") as f:
            pickle.dump({
                "model": self.model,
                "feature_names": self.feature_names,
                "model_type": self.model_type,
            }, f)
        
        with open(scaler_path, "wb") as f:
            pickle.dump(self.scaler, f)
        
        logger.info(f"Model saved to {model_path}")
    
    def load(self, model_path: Optional[str] = None, scaler_path: Optional[str] = None) -> bool:
        """Carga el modelo y scaler desde disco."""
        model_path = model_path or self.config.model_path
        scaler_path = scaler_path or self.config.scaler_path
        
        if not Path(model_path).exists() or not Path(scaler_path).exists():
            logger.warning("Model files not found")
            return False
        
        try:
            with open(model_path, "rb") as f:
                data = pickle.load(f)
                self.model = data["model"]
                self.feature_names = data["feature_names"]
                self.model_type = data.get("model_type", ModelType.LIGHTGBM)
            
            with open(scaler_path, "rb") as f:
                self.scaler = pickle.load(f)
            
            self._is_trained = True
            logger.info(f"Model loaded from {model_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            return False
    
    def get_feature_importance(self, top_n: int = 20) -> dict:
        """Retorna las features más importantes del modelo."""
        if not self._is_trained:
            return {}
        
        if hasattr(self.model, "feature_importances_"):
            importances = self.model.feature_importances_
            importance_dict = dict(zip(self.feature_names, importances))
            sorted_importance = sorted(importance_dict.items(), key=lambda x: x[1], reverse=True)
            return dict(sorted_importance[:top_n])
        
        return {}


class Predictor:
    """
    Clase principal del sistema de predicción.
    
    Orquesta la generación de features y las predicciones del modelo.
    """
    
    def __init__(
        self,
        config: Optional[PredictionConfig] = None,
        model_type: ModelType = ModelType.LIGHTGBM
    ):
        self.config = config or PredictionConfig()
        
        self.feature_generator = FeatureGenerator(self.config)
        self.model = PredictionModel(self.config, model_type)
        
        self._last_prediction: Optional[Prediction] = None
        self._prediction_count = 0
    
    async def initialize(self) -> bool:
        """
        Inicializa el predictor cargando el modelo pre-entrenado.
        
        Returns:
            True si el modelo se cargó correctamente
        """
        return self.model.load()
    
    async def predict(self, data_stream: DataStream) -> Prediction:
        """
        Genera una predicción basada en los datos actuales.
        
        Args:
            data_stream: Stream de datos con información del mercado
            
        Returns:
            Objeto Prediction con la señal y confianza
        """
        df_1m = data_stream.get_candles_df("1m")
        df_5m = data_stream.get_candles_df("5m")
        
        if len(df_1m) < 30 or len(df_5m) < 10:
            logger.warning("Insufficient candle data for prediction")
            return Prediction(
                signal=Signal.WAIT,
                confidence=0.0,
                probability_up=0.5,
                probability_down=0.5
            )
        
        order_book = data_stream.get_order_book() if self.config.use_order_book else None
        trade_flow = data_stream.calculate_trade_flow(60) if self.config.use_trade_flow else None
        
        features = self.feature_generator.generate_features(
            df_1m, df_5m, order_book, trade_flow
        )
        
        prediction = self.model.predict(features)
        
        self._last_prediction = prediction
        self._prediction_count += 1
        
        logger.info(
            f"Prediction #{self._prediction_count}: {prediction.signal.value} "
            f"(confidence: {prediction.confidence:.2%}, "
            f"P(UP): {prediction.probability_up:.2%}, P(DOWN): {prediction.probability_down:.2%})"
        )
        
        return prediction
    
    def train_model(
        self,
        historical_data_1m: pd.DataFrame,
        historical_data_5m: pd.DataFrame,
        forward_returns: pd.Series
    ) -> dict:
        """
        Entrena el modelo con datos históricos.
        
        Args:
            historical_data_1m: Velas históricas de 1 minuto
            historical_data_5m: Velas históricas de 5 minutos
            forward_returns: Serie con labels (1 = UP, 0 = DOWN)
            
        Returns:
            Métricas de entrenamiento
        """
        features_list = []
        
        for i in range(max(self.config.feature_window_1m, self.config.feature_window_5m * 5), len(historical_data_5m)):
            window_1m = historical_data_1m.iloc[max(0, i*5 - self.config.feature_window_1m):i*5]
            window_5m = historical_data_5m.iloc[max(0, i - self.config.feature_window_5m):i]
            
            if len(window_1m) < 30 or len(window_5m) < 10:
                continue
            
            features = self.feature_generator.generate_features(
                window_1m, window_5m, None, None
            )
            features["index"] = i
            features_list.append(features)
        
        if not features_list:
            raise ValueError("No se pudieron generar features suficientes")
        
        X = pd.concat(features_list, ignore_index=True)
        indices = X["index"].values
        X = X.drop(columns=["index"])
        
        y = forward_returns.iloc[indices].reset_index(drop=True)
        
        return self.model.train(X, y)
    
    def save_model(self) -> None:
        """Guarda el modelo entrenado."""
        self.model.save()
    
    def get_last_prediction(self) -> Optional[Prediction]:
        """Retorna la última predicción realizada."""
        return self._last_prediction
    
    @property
    def is_ready(self) -> bool:
        """True si el predictor está listo para hacer predicciones."""
        return self.model._is_trained
