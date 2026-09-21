"""
Gestión de configuración de usuario para Vibesbot.

Maneja la configuración personal, credenciales de Binance,
y preferencias del bot.
"""
import asyncio
import json
import os
import shutil
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from enum import Enum
import hashlib
import base64

import aiohttp

from .utils.logger import get_logger

logger = get_logger("user_settings")


def is_kept_secret(value: Optional[str]) -> bool:
    """Empty or masked fields must not overwrite a saved key."""
    text = (value or "").strip()
    if not text:
        return True
    if set(text) <= set("*•·"):
        return True
    lowered = text.lower()
    return "saved" in lowered or "leave blank" in lowered


def default_settings_path(legacy_root: Optional[Path] = None) -> Path:
    if sys.platform == "darwin":
        folder = Path.home() / "Library" / "Application Support" / "Vibesbot"
    else:
        folder = Path.home() / ".vibesbot"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "user_settings.json"
    if not target.exists() and legacy_root:
        old = Path(legacy_root) / "user_settings.json"
        if old.exists():
            try:
                shutil.copy2(old, target)
            except OSError:
                pass
    return target


def binance_testnet_from_payload(data: Optional[dict]) -> bool:
    """JS sends testnet; older clients sent use_testnet or is_testnet."""
    if not data:
        return False
    for key in ("is_testnet", "use_testnet", "testnet"):
        if key in data:
            return bool(data.get(key))
    return False


def describe_binance_error(status: int, payload: dict, is_testnet: bool) -> str:
    msg = str(payload.get("msg") or payload.get("message") or f"HTTP {status}")
    code = payload.get("code")
    if is_testnet and code in (-2008, -2014, -2015):
        return msg + " Uncheck Use Testnet: this key is from live Binance, not testnet.binance.vision."
    if not is_testnet and code == -2015:
        return msg + " Enable Reading on the key, or add this Mac's IP to the whitelist."
    return msg


_CEX_WALLET_NOISE = (
    "spot",
    "funding",
    "margin",
    "future",
    "earn",
    "option",
    "cedefi",
    "copy",
    "trading bot",
    "cross",
    "isolated",
)


def pick_live_wallet(wallets: Dict[str, float]) -> tuple:
    """Only Prediction BSC USDT counts. CEX wallets (Spot, Funding, CeDefi) are ignored."""
    if not wallets:
        return "Prediction BSC", 0.0
    prediction: Dict[str, float] = {}
    for name, amount in wallets.items():
        lowered = name.lower()
        is_bsc = "0x" in lowered or "bsc" in lowered or "prediction" in lowered
        if any(token in lowered for token in _CEX_WALLET_NOISE) and not is_bsc:
            continue
        prediction[name] = float(amount)
    if not prediction:
        return "Prediction BSC", 0.0
    name = max(prediction, key=lambda item: float(prediction[item]))
    return name, float(prediction[name])


class TradingMode(Enum):
    """Modos de trading disponibles."""
    SIMULATION = "simulation"  # Paper trading con dinero virtual
    LIVE = "live"              # Trading real


@dataclass
class BinanceCredentials:
    """Credenciales de Binance."""
    api_key: str = ""
    api_secret: str = ""
    is_testnet: bool = False
    
    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)
    
    def to_dict(self) -> dict:
        return {
            "configured": self.is_configured,
            "api_key": self._mask_secret(self.api_key) if self.api_key else "",
            "api_secret": "",
            "has_secret": bool(self.api_secret),
            "is_testnet": self.is_testnet
        }
    
    def _mask_secret(self, secret: str) -> str:
        if len(secret) <= 8:
            return "*" * len(secret)
        return secret[:4] + "*" * (len(secret) - 8) + secret[-4:]


class TradingStyle(Enum):
    """Estilos de trading disponibles."""
    HOLD = "hold"        # Solo comprar, esperar al final
    ACTIVE = "active"    # Comprar y vender según condiciones


@dataclass
class TradingSettings:
    """Configuración de trading."""
    mode: TradingMode = TradingMode.SIMULATION
    style: TradingStyle = TradingStyle.HOLD  # HOLD o ACTIVE
    symbol: str = "BTCUSDT"
    bet_amount: float = 1.0  # USD por apuesta
    max_daily_loss: float = 50.0  # USD
    max_trades_per_day: int = 50
    confidence_threshold: float = 0.62  # 62% mínimo
    auto_trade: bool = False  # Si ejecuta trades automáticamente
    
    # Configuración para modo ACTIVE
    take_profit_pct: float = 30.0   # Vender si ganancia > 30%
    stop_loss_pct: float = 40.0     # Vender si pérdida > 40%
    
    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "style": self.style.value,
            "symbol": self.symbol,
            "bet_amount": self.bet_amount,
            "max_daily_loss": self.max_daily_loss,
            "max_trades_per_day": self.max_trades_per_day,
            "confidence_threshold": self.confidence_threshold,
            "auto_trade": self.auto_trade,
            "take_profit_pct": self.take_profit_pct,
            "stop_loss_pct": self.stop_loss_pct
        }


@dataclass
class SimulationAccount:
    """Cuenta de simulación (paper trading)."""
    balance: float = 1000.0  # Balance inicial en USD
    starting_balance: float = 1000.0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    history: List[Dict] = field(default_factory=list)
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.wins / self.total_trades
    
    def record_trade(self, direction: str, amount: float, result: str, pnl: float, price: float):
        """Registra un trade en el historial."""
        self.total_trades += 1
        if result == "WIN":
            self.wins += 1
        else:
            self.losses += 1
        
        self.total_pnl += pnl
        self.balance += pnl
        
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "direction": direction,
            "amount": amount,
            "result": result,
            "pnl": pnl,
            "price": price,
            "balance_after": self.balance
        })
        
        # Mantener solo últimos 100 trades
        if len(self.history) > 100:
            self.history = self.history[-100:]
    
    def reset(self):
        """Reinicia la cuenta de simulación."""
        self.balance = self.starting_balance
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.total_pnl = 0.0
        self.history = []
    
    def to_dict(self) -> dict:
        return {
            "balance": self.balance,
            "starting_balance": self.starting_balance,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "total_pnl": self.total_pnl,
            "win_rate": self.win_rate,
            "history": self.history[-20:]  # Últimos 20 trades
        }


@dataclass
class UserSettings:
    """Configuración completa del usuario."""
    binance: BinanceCredentials = field(default_factory=BinanceCredentials)
    trading: TradingSettings = field(default_factory=TradingSettings)
    simulation: SimulationAccount = field(default_factory=SimulationAccount)
    
    # UI Preferences
    theme: str = "dark"
    sound_enabled: bool = True
    notifications_enabled: bool = True
    
    # Auto-update
    auto_update: bool = True
    last_update_check: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "binance": self.binance.to_dict(),
            "trading": self.trading.to_dict(),
            "simulation": self.simulation.to_dict(),
            "theme": self.theme,
            "sound_enabled": self.sound_enabled,
            "notifications_enabled": self.notifications_enabled,
            "auto_update": self.auto_update,
            "last_update_check": self.last_update_check
        }


class BinanceConnector:
    """
    Conector para la API de Binance.
    
    Soporta tanto la API real como el testnet.
    """
    
    MAINNET_API = "https://api.binance.com"
    TESTNET_API = "https://testnet.binance.vision"
    
    def __init__(self, credentials: BinanceCredentials):
        self.credentials = credentials
        self.base_url = self.TESTNET_API if credentials.is_testnet else self.MAINNET_API
    
    async def test_connection(self) -> Dict[str, Any]:
        """
        Prueba la conexión con Binance.
        
        Returns:
            {"success": bool, "message": str, "account_info": dict}
        """
        if not self.credentials.is_configured:
            return {
                "success": False,
                "message": "API Key and Secret are required",
                "error": "API Key and Secret are required",
            }
        
        try:
            import hmac
            import time
            
            timestamp = int(time.time() * 1000)
            query_string = f"timestamp={timestamp}&recvWindow=5000"
            
            signature = hmac.new(
                self.credentials.api_secret.encode('utf-8'),
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            url = f"{self.base_url}/api/v3/account?{query_string}&signature={signature}"
            
            headers = {
                "X-MBX-APIKEY": self.credentials.api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Extraer balances relevantes
                        balances = {}
                        for asset in data.get("balances", []):
                            free = float(asset.get("free", 0))
                            if free > 0:
                                balances[asset["asset"]] = free
                        
                        return {
                            "success": True,
                            "message": "Connected to live Binance" if not self.credentials.is_testnet else "Connected to Binance Testnet",
                            "error": "",
                            "account_info": {
                                "can_trade": data.get("canTrade", False),
                                "balances": balances,
                                "account_type": "Testnet" if self.credentials.is_testnet else "Real"
                            }
                        }
                    try:
                        error_data = await response.json()
                    except Exception:
                        error_data = {"msg": (await response.text())[:180] or f"HTTP {response.status}"}
                    detail = describe_binance_error(response.status, error_data, self.credentials.is_testnet)
                    return {
                        "success": False,
                        "message": detail,
                        "error": detail,
                    }
        
        except aiohttp.ClientError as e:
            return {
                "success": False,
                "message": f"Connection error: {str(e)}",
                "error": f"Connection error: {str(e)}",
            }
        except Exception as e:
            logger.error(f"Error testing Binance connection: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "error": f"Error: {str(e)}",
            }
    
    async def get_current_price(self, symbol: str = "BTCUSDT") -> Optional[float]:
        """Obtiene el precio actual de un símbolo."""
        try:
            # Usar API pública (no requiere autenticación)
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        return float(data.get("price", 0))
        except Exception as e:
            logger.error(f"Error getting price: {e}")
        
        return None

    def _signed_query(self, extra: Optional[Dict[str, Any]] = None) -> str:
        import hmac
        import time

        params = dict(extra or {})
        params["timestamp"] = int(time.time() * 1000)
        params.setdefault("recvWindow", 5000)
        query = "&".join(f"{key}={params[key]}" for key in params)
        signature = hmac.new(
            self.credentials.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{query}&signature={signature}"

    async def _signed_request(self, method: str, path: str, extra: Optional[Dict[str, Any]] = None) -> tuple:
        if not self.credentials.is_configured:
            return 400, {"msg": "API Key and Secret are required"}
        query = self._signed_query(extra)
        url = f"{self.base_url}{path}?{query}"
        headers = {"X-MBX-APIKEY": self.credentials.api_key}
        async with aiohttp.ClientSession() as session:
            request = session.get if method.upper() == "GET" else session.post
            async with request(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                try:
                    payload = await response.json()
                except Exception:
                    payload = {"msg": (await response.text())[:180]}
                return response.status, payload

    async def _signed_get(self, path: str, extra: Optional[Dict[str, Any]] = None) -> tuple:
        return await self._signed_request("GET", path, extra)

    async def _signed_post(self, path: str, extra: Optional[Dict[str, Any]] = None) -> tuple:
        return await self._signed_request("POST", path, extra)

    def _merge_usdt_wallet(self, wallets: Dict[str, float], name: str, payload: Any) -> None:
        amount = 0.0
        rows = payload if isinstance(payload, list) else []
        if isinstance(payload, dict):
            rows = payload.get("balances") or payload.get("assets") or [payload]
        for row in rows:
            if not isinstance(row, dict):
                continue
            asset = str(row.get("asset") or row.get("coin") or "").upper()
            if asset and asset != "USDT":
                continue
            try:
                amount += float(row.get("free") or 0) + float(row.get("locked") or 0) + float(row.get("freeze") or 0)
            except (TypeError, ValueError):
                continue
        if name not in wallets or amount > 0:
            wallets[name] = amount

    async def fetch_live_balances(self) -> Dict[str, Any]:
        """USDT on BNB Smart Chain in Binance Wallet — not Spot, Funding, or CeDefi."""
        empty = {
            "success": False,
            "wallets": {},
            "display_wallet": "Prediction BSC",
            "display_balance": 0.0,
            "wallet_address": "",
            "network": "BNB Smart Chain",
            "error": "",
        }
        if self.credentials.is_testnet:
            empty["error"] = "Testnet has no Binance Wallet Prediction. Uncheck Use Testnet."
            return empty
        if not self.credentials.is_configured:
            empty["error"] = "API Key and Secret are required"
            return empty
        try:
            from .wallet_prediction import WalletPredictionClient
            client = WalletPredictionClient(self.credentials.api_key, self.credentials.api_secret)
            picked = await client.fetch_prediction_wallet()
        except Exception as exc:
            logger.warning(f"Prediction BSC read failed: {exc}")
            empty["error"] = f"Wallet API: {exc}"
            return empty
        label = str(picked.get("label") or "Prediction BSC")
        amount = float(picked.get("usdt") or 0)
        address = str(picked.get("wallet_address") or "")
        wallets = {label: amount} if address else {}
        return {
            "success": bool(address),
            "wallets": wallets,
            "display_wallet": label,
            "display_balance": amount,
            "wallet_address": address,
            "network": "BNB Smart Chain",
            "error": picked.get("error") or "",
        }


class SettingsManager:
    """
    Gestor de configuración de usuario.
    
    Maneja persistencia, validación y acceso a la configuración.
    """
    
    SETTINGS_FILE = "user_settings.json"
    
    def __init__(self, app_path: Optional[Path] = None):
        if app_path is not None:
            self.app_path = Path(app_path)
            self.settings_path = self.app_path / self.SETTINGS_FILE
        else:
            self.app_path = Path(__file__).parent.parent
            self.settings_path = default_settings_path(self.app_path)
        self.settings = UserSettings()
        self._binance_connector: Optional[BinanceConnector] = None
        
        self.load()
    
    def load(self):
        """Carga la configuración desde el archivo."""
        if not self.settings_path.exists():
            logger.info("No settings file found, using defaults")
            return
        
        try:
            with open(self.settings_path, 'r') as f:
                data = json.load(f)
            
            # Binance
            if "binance" in data:
                b = data["binance"]
                self.settings.binance = BinanceCredentials(
                    api_key=b.get("api_key", ""),
                    api_secret=b.get("api_secret_encrypted", ""),  # Guardamos encriptado
                    is_testnet=b.get("is_testnet", False)
                )
            
            # Trading
            if "trading" in data:
                t = data["trading"]
                self.settings.trading = TradingSettings(
                    mode=TradingMode(t.get("mode", "simulation")),
                    symbol=t.get("symbol", "BTCUSDT"),
                    bet_amount=t.get("bet_amount", 1.0),
                    max_daily_loss=t.get("max_daily_loss", 50.0),
                    max_trades_per_day=t.get("max_trades_per_day", 50),
                    confidence_threshold=t.get("confidence_threshold", 0.62),
                    auto_trade=t.get("auto_trade", False)
                )
            
            # Simulation
            if "simulation" in data:
                s = data["simulation"]
                self.settings.simulation = SimulationAccount(
                    balance=s.get("balance", 1000.0),
                    starting_balance=s.get("starting_balance", 1000.0),
                    total_trades=s.get("total_trades", 0),
                    wins=s.get("wins", 0),
                    losses=s.get("losses", 0),
                    total_pnl=s.get("total_pnl", 0.0),
                    history=s.get("history", [])
                )
            
            # Preferences
            self.settings.theme = data.get("theme", "dark")
            self.settings.sound_enabled = data.get("sound_enabled", True)
            self.settings.notifications_enabled = data.get("notifications_enabled", True)
            self.settings.auto_update = data.get("auto_update", True)
            self.settings.last_update_check = data.get("last_update_check")
            
            logger.info("Settings loaded successfully")
            
        except Exception as e:
            logger.error(f"Error loading settings: {e}")
    
    def save(self):
        """Guarda la configuración en el archivo."""
        try:
            data = {
                "binance": {
                    "api_key": self.settings.binance.api_key,
                    "api_secret_encrypted": self.settings.binance.api_secret,
                    "is_testnet": self.settings.binance.is_testnet
                },
                "trading": self.settings.trading.to_dict(),
                "simulation": {
                    "balance": self.settings.simulation.balance,
                    "starting_balance": self.settings.simulation.starting_balance,
                    "total_trades": self.settings.simulation.total_trades,
                    "wins": self.settings.simulation.wins,
                    "losses": self.settings.simulation.losses,
                    "total_pnl": self.settings.simulation.total_pnl,
                    "history": self.settings.simulation.history
                },
                "theme": self.settings.theme,
                "sound_enabled": self.settings.sound_enabled,
                "notifications_enabled": self.settings.notifications_enabled,
                "auto_update": self.settings.auto_update,
                "last_update_check": self.settings.last_update_check
            }
            
            with open(self.settings_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info("Settings saved successfully")
            
        except Exception as e:
            logger.error(f"Error saving settings: {e}")
    
    def update_binance_credentials(self, api_key: str, api_secret: str, is_testnet: bool = False):
        """Actualiza las credenciales de Binance."""
        key = (api_key or "").strip()
        secret = (api_secret or "").strip()
        if is_kept_secret(key):
            key = self.settings.binance.api_key
        if is_kept_secret(secret):
            secret = self.settings.binance.api_secret
        self.settings.binance = BinanceCredentials(
            api_key=key,
            api_secret=secret,
            is_testnet=is_testnet
        )
        self._binance_connector = None  # Reset connector
        self.save()
    
    def update_trading_settings(self, **kwargs):
        """Actualiza la configuración de trading."""
        if "mode" in kwargs:
            kwargs["mode"] = TradingMode(kwargs["mode"])
        
        for key, value in kwargs.items():
            if hasattr(self.settings.trading, key):
                setattr(self.settings.trading, key, value)
        
        self.save()
    
    def get_binance_connector(self) -> BinanceConnector:
        """Obtiene el conector de Binance."""
        if self._binance_connector is None:
            self._binance_connector = BinanceConnector(self.settings.binance)
        return self._binance_connector
    
    async def test_binance_connection(self) -> Dict[str, Any]:
        """Prueba la conexión con Binance."""
        connector = self.get_binance_connector()
        result = await connector.test_connection()
        if not result.get("success") or self.settings.binance.is_testnet:
            return result
        try:
            from .wallet_prediction import WalletPredictionClient
            client = WalletPredictionClient(
                self.settings.binance.api_key,
                self.settings.binance.api_secret,
            )
            picked = await client.fetch_prediction_wallet()
            if picked.get("wallet_address"):
                result["message"] = (
                    (result.get("message") or "Connected")
                    + f" | Prediction BSC {picked.get('label')} "
                    + f"${float(picked.get('usdt') or 0):.2f} USDT on BNB Smart Chain"
                )
            else:
                result["message"] = (
                    (result.get("message") or "Connected")
                    + " | Wallet API: "
                    + (picked.get("error") or "no BSC address")
                )
            result["wallet"] = picked
        except Exception as exc:
            result["message"] = (result.get("message") or "Connected") + f" | Wallet API error: {exc}"
        return result

    async def fetch_live_balances(self) -> Dict[str, Any]:
        connector = self.get_binance_connector()
        return await connector.fetch_live_balances()
    
    def record_simulation_trade(self, direction: str, amount: float, result: str, pnl: float, price: float):
        """Registra un trade en la cuenta de simulación."""
        self.settings.simulation.record_trade(direction, amount, result, pnl, price)
        self.save()
    
    def reset_simulation(self, starting_balance: float = 1000.0):
        """Reinicia la cuenta de simulación."""
        self.settings.simulation.starting_balance = starting_balance
        self.settings.simulation.reset()
        self.save()
    
    def get_settings_for_frontend(self) -> dict:
        """Retorna la configuración formateada para el frontend."""
        return self.settings.to_dict()


# Singleton
_settings_manager: Optional[SettingsManager] = None

def get_settings_manager() -> SettingsManager:
    """Obtiene el gestor de configuración."""
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager
