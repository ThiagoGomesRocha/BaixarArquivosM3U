#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M3U Downloader e Organizador para Jellyfin
Ponto de entrada principal
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Tuple

# Adiciona o diretório atual ao path
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from m3u_organizer.gui import M3UOrganizerGUI
from m3u_organizer.config_validator import (
    ConfigValidator,
    validate_and_normalize_config,
    get_default_config
)


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """
    Configura o sistema de logging.

    Args:
        log_level: Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Returns:
        Logger configurado
    """
    # Criar diretório de logs
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)

    # Nível de log
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Configurar log básico
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_dir / f"m3u_organizer_{datetime.now().strftime('%Y%m%d')}.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )

    return logging.getLogger(__name__)


def load_config() -> Tuple[dict, dict]:
    """
    Carrega e valida configurações do arquivo config.json.

    Returns:
        Tupla (config_normalizada, resultados_validacao)
    """
    config_path = Path(__file__).parent / "config.json"

    # Carregar configuração existente ou criar padrão
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            print(f"[CONFIG] Carregado de {config_path}")
        except json.JSONDecodeError as e:
            print(f"[WARN] Erro ao decodificar config.json: {e}. Usando configuração padrão.")
            user_config = {}
        except IOError as e:
            print(f"[WARN] Erro ao ler config.json: {e}. Usando configuração padrão.")
            user_config = {}
    else:
        # Cria config.json padrão
        default_config = get_default_config()
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)
        print(f"[CONFIG] Criado config.json padrão em {config_path}")
        user_config = {}

    # Validar e normalizar configuração
    normalized_config, validation = validate_and_normalize_config(user_config)

    # Relatar problemas de validação
    if not validation.is_valid:
        print(f"[ERROR] Configuração inválida:")
        for error in validation.errors:
            print(f"  - {error}")

    if validation.warnings:
        print(f"[WARN] Avisos de validação:")
        for warning in validation.warnings:
            print(f"  - {warning}")

    # Salvar configuração corrigida
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(normalized_config, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"[WARN] Não foi possível salvar config.json atualizado: {e}")

    return normalized_config, {
        "is_valid": validation.is_valid,
        "errors": validation.errors,
        "warnings": validation.warnings
    }


def main() -> int:
    """
    Função principal de entrada.

    Returns:
        Código de saída (0 para sucesso)
    """
    # Carregar configuração primeiro (para configurar log_level)
    config = load_config()[0]

    # Configurar logging após carregar config
    log_level = config.get("log_level", "INFO")
    logger = setup_logging(log_level)

    logger.info("=" * 50)
    logger.info("Iniciando M3U Organizer")
    logger.info("=" * 50)

    # Inicializar aplicação Qt
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Criar janela principal
    try:
        main_window = M3UOrganizerGUI(config)
        main_window.show()
        logger.info("Janela principal criada com sucesso")
    except Exception as e:
        logger.error(f"Erro ao criar janela principal: {e}")
        return 1

    logger.info("Aplicação iniciada com sucesso")

    # Executar loop de eventos
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())