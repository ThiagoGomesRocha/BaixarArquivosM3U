#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M3U Downloader e Organizador para Jellyfin
Módulo de inicialização do pacote
"""

__version__ = "1.0.0"
__author__ = "M3U Organizer"
__description__ = "Aplicativo de download e organização de listas M3U com interface gráfica para Jellyfin"

# Importa módulos principais
from m3u_organizer.m3u_parser import M3UParser, M3UEntry
from m3u_organizer.downloader import Downloader, DownloadResult
from m3u_organizer.organizer import Organizer, OrganizationResult
from m3u_organizer.state_manager import StateManager
from m3u_organizer.gui import M3UOrganizerGUI
from m3u_organizer.utils import (
    sanitize_filename,
    extract_id_from_url,
    calculate_file_hash,
    get_supported_video_extensions
)
from m3u_organizer.config_validator import (
    ConfigValidator,
    validate_and_normalize_config,
    get_default_config
)

__all__ = [
    "M3UParser", "M3UEntry",
    "Downloader", "DownloadResult",
    "Organizer", "OrganizationResult",
    "StateManager",
    "M3UOrganizerGUI",
    "sanitize_filename",
    "extract_id_from_url",
    "calculate_file_hash",
    "get_supported_video_extensions",
    "ConfigValidator",
    "validate_and_normalize_config",
    "get_default_config"
]