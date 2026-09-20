"""
Data Exporter - Exportación de datos de trading.

Permite exportar historial de trades y análisis en diferentes formatos.
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import io

from .utils.logger import get_logger

logger = get_logger("data_exporter")


class DataExporter:
    """Exportador de datos de trading."""
    
    def __init__(self):
        self.export_dir = Path(__file__).parent.parent / "exports"
        self.export_dir.mkdir(exist_ok=True)
    
    def export_trades_csv(self, trades: List[Dict], filename: Optional[str] = None) -> str:
        """Exporta trades a CSV."""
        
        if not filename:
            filename = f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        filepath = self.export_dir / filename
        
        if not trades:
            return ""
        
        # Obtener headers de las keys del primer trade
        headers = list(trades[0].keys())
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(trades)
        
        logger.info(f"Exported {len(trades)} trades to {filepath}")
        return str(filepath)
    
    def export_trades_json(self, trades: List[Dict], filename: Optional[str] = None) -> str:
        """Exporta trades a JSON."""
        
        if not filename:
            filename = f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        filepath = self.export_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({
                "exported_at": datetime.now().isoformat(),
                "total_trades": len(trades),
                "trades": trades
            }, f, indent=2)
        
        logger.info(f"Exported {len(trades)} trades to {filepath}")
        return str(filepath)
    
    def generate_csv_content(self, trades: List[Dict]) -> str:
        """Genera contenido CSV como string (para descarga directa)."""
        
        if not trades:
            return ""
        
        output = io.StringIO()
        headers = list(trades[0].keys())
        
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(trades)
        
        return output.getvalue()
    
    def generate_report(
        self,
        trades: List[Dict],
        stats: Dict[str, Any],
        strategy_name: str = "Unknown"
    ) -> Dict[str, Any]:
        """Genera un reporte completo de trading."""
        
        if not trades:
            return {"error": "No trades to analyze"}
        
        # Análisis por hora del día
        hourly_stats = {}
        for trade in trades:
            timestamp = trade.get('timestamp', '')
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    hour = dt.hour
                    if hour not in hourly_stats:
                        hourly_stats[hour] = {"wins": 0, "losses": 0, "pnl": 0}
                    
                    if trade.get('result') == 'WIN':
                        hourly_stats[hour]["wins"] += 1
                    else:
                        hourly_stats[hour]["losses"] += 1
                    hourly_stats[hour]["pnl"] += trade.get('pnl', 0)
                except:
                    pass
        
        # Mejor y peor hora
        best_hour = None
        worst_hour = None
        best_pnl = float('-inf')
        worst_pnl = float('inf')
        
        for hour, data in hourly_stats.items():
            if data["pnl"] > best_pnl:
                best_pnl = data["pnl"]
                best_hour = hour
            if data["pnl"] < worst_pnl:
                worst_pnl = data["pnl"]
                worst_hour = hour
        
        # Análisis de rachas
        current_streak = 0
        best_streak = 0
        worst_streak = 0
        
        for trade in trades:
            if trade.get('result') == 'WIN':
                if current_streak >= 0:
                    current_streak += 1
                else:
                    current_streak = 1
                best_streak = max(best_streak, current_streak)
            else:
                if current_streak <= 0:
                    current_streak -= 1
                else:
                    current_streak = -1
                worst_streak = min(worst_streak, current_streak)
        
        # Análisis de señales
        up_trades = [t for t in trades if t.get('signal') == 'UP']
        down_trades = [t for t in trades if t.get('signal') == 'DOWN']
        
        up_win_rate = (len([t for t in up_trades if t.get('result') == 'WIN']) / len(up_trades) * 100) if up_trades else 0
        down_win_rate = (len([t for t in down_trades if t.get('result') == 'WIN']) / len(down_trades) * 100) if down_trades else 0
        
        return {
            "generated_at": datetime.now().isoformat(),
            "strategy": strategy_name,
            "summary": {
                "total_trades": len(trades),
                "wins": stats.get("wins", 0),
                "losses": stats.get("losses", 0),
                "win_rate": stats.get("win_rate", 0),
                "total_pnl": stats.get("total_pnl", 0),
                "profit_factor": stats.get("profit_factor", 0)
            },
            "analysis": {
                "best_hour": best_hour,
                "worst_hour": worst_hour,
                "best_streak": best_streak,
                "worst_streak": worst_streak,
                "up_signal_win_rate": up_win_rate,
                "down_signal_win_rate": down_win_rate,
                "avg_win": sum(t.get('pnl', 0) for t in trades if t.get('result') == 'WIN') / max(1, stats.get("wins", 1)),
                "avg_loss": sum(t.get('pnl', 0) for t in trades if t.get('result') == 'LOSS') / max(1, stats.get("losses", 1))
            },
            "hourly_breakdown": hourly_stats
        }


# Singleton
_exporter: Optional[DataExporter] = None

def get_exporter() -> DataExporter:
    """Obtiene el exportador de datos."""
    global _exporter
    if _exporter is None:
        _exporter = DataExporter()
    return _exporter
