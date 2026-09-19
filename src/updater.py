"""
Sistema de auto-actualización para Vibesbot.

Verifica actualizaciones en GitHub y las aplica automáticamente.
"""
import asyncio
import aiohttp
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from .utils.logger import get_logger

logger = get_logger("updater")

# Configuración
GITHUB_REPO = "knull66/Vibesbot"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"
VERSION_FILE = "VERSION"
CURRENT_VERSION = "1.0.0"


@dataclass
class UpdateInfo:
    """Información sobre una actualización disponible."""
    available: bool
    current_version: str
    latest_version: str
    download_url: Optional[str] = None
    release_notes: Optional[str] = None
    published_at: Optional[str] = None


class Updater:
    """
    Gestor de actualizaciones automáticas.
    
    Verifica y aplica actualizaciones desde GitHub.
    """
    
    def __init__(self, app_path: Optional[str] = None):
        self.app_path = Path(app_path) if app_path else self._find_app_path()
        self.version_file = self.app_path / VERSION_FILE
        self.current_version = self._get_current_version()
    
    def _find_app_path(self) -> Path:
        """Encuentra la ruta de la aplicación."""
        # Buscar en varios lugares
        possible_paths = [
            Path(__file__).parent.parent,  # Desde src/
            Path.home() / "Downloads" / "Vibesbot",
            Path("/Applications/Vibesbot.app/Contents/Resources/vibesbot"),
        ]
        
        for path in possible_paths:
            if path.exists() and (path / "src").exists():
                return path
        
        return Path(__file__).parent.parent
    
    def _get_current_version(self) -> str:
        """Obtiene la versión actual instalada."""
        if self.version_file.exists():
            return self.version_file.read_text().strip()
        return CURRENT_VERSION
    
    def _save_version(self, version: str):
        """Guarda la versión actual."""
        self.version_file.write_text(version)
    
    async def check_for_updates(self) -> UpdateInfo:
        """
        Verifica si hay actualizaciones disponibles.
        
        Returns:
            UpdateInfo con información de la actualización
        """
        try:
            async with aiohttp.ClientSession() as session:
                # Intentar obtener releases
                async with session.get(
                    f"{GITHUB_API}/releases/latest",
                    headers={"Accept": "application/vnd.github.v3+json"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        latest_version = data.get("tag_name", "").lstrip("v")
                        
                        return UpdateInfo(
                            available=self._is_newer_version(latest_version),
                            current_version=self.current_version,
                            latest_version=latest_version,
                            download_url=data.get("zipball_url"),
                            release_notes=data.get("body"),
                            published_at=data.get("published_at")
                        )
                
                # Si no hay releases, verificar commits
                async with session.get(
                    f"{GITHUB_API}/commits/main",
                    headers={"Accept": "application/vnd.github.v3+json"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        commit_sha = data.get("sha", "")[:7]
                        commit_date = data.get("commit", {}).get("committer", {}).get("date", "")
                        
                        # Comparar con el último commit conocido
                        latest_version = f"dev-{commit_sha}"
                        
                        return UpdateInfo(
                            available=self.current_version != latest_version,
                            current_version=self.current_version,
                            latest_version=latest_version,
                            download_url=f"https://github.com/{GITHUB_REPO}/archive/refs/heads/main.zip",
                            release_notes=f"Commit: {commit_sha}\n{data.get('commit', {}).get('message', '')}",
                            published_at=commit_date
                        )
        
        except Exception as e:
            logger.error(f"Error checking for updates: {e}")
        
        return UpdateInfo(
            available=False,
            current_version=self.current_version,
            latest_version=self.current_version
        )
    
    def _is_newer_version(self, latest: str) -> bool:
        """Compara versiones."""
        try:
            current_parts = [int(x) for x in self.current_version.split(".")]
            latest_parts = [int(x) for x in latest.split(".")]
            return latest_parts > current_parts
        except:
            return latest != self.current_version
    
    async def download_update(self, url: str, progress_callback=None) -> Optional[Path]:
        """
        Descarga una actualización.
        
        Args:
            url: URL del archivo zip
            progress_callback: Función para reportar progreso (0-100)
        
        Returns:
            Path al archivo descargado o None si falla
        """
        try:
            temp_dir = Path(tempfile.mkdtemp())
            zip_path = temp_dir / "update.zip"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as response:
                    if response.status != 200:
                        logger.error(f"Download failed: {response.status}")
                        return None
                    
                    total_size = int(response.headers.get("Content-Length", 0))
                    downloaded = 0
                    
                    with open(zip_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            if progress_callback and total_size > 0:
                                progress = int((downloaded / total_size) * 100)
                                progress_callback(progress)
            
            logger.info(f"Update downloaded to {zip_path}")
            return zip_path
            
        except Exception as e:
            logger.error(f"Error downloading update: {e}")
            return None
    
    async def apply_update(self, zip_path: Path, new_version: str) -> bool:
        """
        Aplica una actualización descargada.
        
        Args:
            zip_path: Path al archivo zip
            new_version: Nueva versión a guardar
        
        Returns:
            True si se aplicó correctamente
        """
        try:
            # Extraer a directorio temporal
            extract_dir = zip_path.parent / "extracted"
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            # Encontrar el directorio del proyecto (GitHub añade un prefijo)
            project_dirs = list(extract_dir.iterdir())
            if not project_dirs:
                logger.error("Empty zip file")
                return False
            
            source_dir = project_dirs[0]
            
            # Archivos y directorios a actualizar
            items_to_update = ['src', 'web', 'assets']
            
            for item in items_to_update:
                source = source_dir / item
                dest = self.app_path / item
                
                if source.exists():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(source, dest)
                    logger.info(f"Updated: {item}")
            
            # Guardar nueva versión
            self._save_version(new_version)
            
            # Limpiar
            shutil.rmtree(zip_path.parent)
            
            logger.info(f"Update applied: {new_version}")
            return True
            
        except Exception as e:
            logger.error(f"Error applying update: {e}")
            return False
    
    async def update(self, progress_callback=None) -> Tuple[bool, str]:
        """
        Proceso completo de actualización.
        
        Returns:
            (éxito, mensaje)
        """
        # Verificar actualizaciones
        if progress_callback:
            progress_callback(5)
        
        update_info = await self.check_for_updates()
        
        if not update_info.available:
            return (False, "No hay actualizaciones disponibles")
        
        if not update_info.download_url:
            return (False, "URL de descarga no disponible")
        
        # Descargar
        def download_progress(p):
            if progress_callback:
                progress_callback(10 + int(p * 0.7))
        
        zip_path = await self.download_update(update_info.download_url, download_progress)
        
        if not zip_path:
            return (False, "Error descargando actualización")
        
        if progress_callback:
            progress_callback(85)
        
        # Aplicar
        success = await self.apply_update(zip_path, update_info.latest_version)
        
        if progress_callback:
            progress_callback(100)
        
        if success:
            return (True, f"Actualizado a versión {update_info.latest_version}")
        else:
            return (False, "Error aplicando actualización")


# Singleton para acceso global
_updater: Optional[Updater] = None

def get_updater() -> Updater:
    """Obtiene la instancia del updater."""
    global _updater
    if _updater is None:
        _updater = Updater()
    return _updater


async def check_updates_on_startup():
    """Verifica actualizaciones al iniciar."""
    updater = get_updater()
    info = await updater.check_for_updates()
    
    if info.available:
        logger.info(f"Update available: {info.current_version} -> {info.latest_version}")
    
    return info
