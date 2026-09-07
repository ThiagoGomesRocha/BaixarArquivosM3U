#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M3U Downloader e Organizador para Jellyfin
Ponto de entrada principal
"""

import os
import sys
import json
from pathlib import Path

# Adiciona o diretório atual ao path
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from m3u_organizer.gui import M3UOrganizerGUI


def load_config() -> dict:
    """Carrega configurações do arquivo config.json."""
    config_path = Path(__file__).parent / "config.json"
    
    default_config = {
        "base_dir": "",
        "last_m3u_url": "",
        "regex_serie": r"^(.*?)\s+S(\d+)E(\d+)",
        "retries": 3,
        "duplicate_policy": "skip",
        "auto_organize": True,
        "theme": "dark",
        "download_dir": "temp",
        "log_level": "INFO",
        "yt_dlp_path": "yt-dlp",
        "cookies_file": "",
        "max_concurrent_downloads": 3,
    }
    
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
                default_config.update(user_config)
                print(f"[CONFIG] Carregado de {config_path}")
        except (json.JSONDecodeError, IOError) as e:
            print(f"[WARN] Erro ao carregar config.json: {e}. Usando configuração padrão.")
    else:
        # Cria config.json padrão
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)
        print(f"[CONFIG] Criado config.json padrão em {config_path}")
    
    return default_config


def main():
    """Função principal de entrada."""
    # Configura log
    from datetime import datetime
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / f"m3u_organizer_{datetime.now().strftime('%Y%m%d')}.log"
    
    print(f"[INFO] Iniciando M3U Organizer")
    print(f"[INFO] Log: {log_file}")
    
    # Carrega configurações
    config = load_config()
    
    # Inicializa aplicação Qt
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Cria janela principal
    window = M3UOrganizerGUI(config)
    window.show()
    
    # Log de inicialização
    print(f"[INFO] Aplicação iniciada com sucesso")
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
