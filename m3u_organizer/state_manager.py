#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M3U Downloader e Organizador para Jellyfin
Sistema de gerenciamento de estado persistente (state.json)
"""

import json
import re
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

# Configura logger
logger = logging.getLogger(__name__)


class StateManager:
    """
    Gerencia o estado persistente dos downloads e organização.

    Mantém um arquivo state.json com:
    - Mapeamento de IDs para caminhos de arquivos
    - Metadados de downloads (título, série, etc.)
    - Hashes para detecção de duplicatas
    - Timestamps de download
    """

    # Padrões para extração de metadados
    SERIE_PATTERN = re.compile(r"^(.*?)\s*-\s*S(\d+)E(\d+)\s*-?\s*(.+)$")
    FILME_PATTERN = re.compile(r"^(.+)\.mp4$")

    def __init__(self, base_dir: str):
        """
        Inicializa o gerenciador de estado.

        Args:
            base_dir: Diretório base para o arquivo state.json
        """
        self.base_dir = Path(base_dir)
        self.state_file = self.base_dir / "state.json"
        self.state: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Carrega o estado do arquivo state.json."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self.state = json.load(f)
                logger.info(f"Carregado {len(self.state)} itens do state.json")
            except json.JSONDecodeError as e:
                logger.error(f"Erro ao decodificar state.json: {e}")
                self.state = {}
            except IOError as e:
                logger.error(f"Erro ao ler state.json: {e}")
                self.state = {}
        else:
            self.state = {}
            logger.debug("state.json não encontrado, criando novo estado vazio")

    def _save(self) -> bool:
        """
        Salva o estado no arquivo state.json.

        Returns:
            True se salvo com sucesso
        """
        try:
            # Garantir que o diretório existe
            self.base_dir.mkdir(parents=True, exist_ok=True)

            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            return True

        except IOError as e:
            logger.error(f"Não foi possível salvar state.json: {e}")
            return False
        except json.JSONEncodeError as e:
            logger.error(f"Não foi possível codificar estado como JSON: {e}")
            return False

    def add_item(self, item_id: str, data: dict) -> bool:
        """
        Adiciona ou atualiza um item no estado.

        Args:
            item_id: ID único do item
            data: Dicionário com dados do item

        Returns:
            True se adicionado com sucesso
        """
        if not item_id:
            logger.warning("Tentativa de adicionar item sem ID")
            return False

        try:
            data["updated_at"] = datetime.now().isoformat()
            self.state[str(item_id)] = data
            return self._save()
        except Exception as e:
            logger.error(f"Erro ao adicionar item {item_id} ao estado: {e}")
            return False

    def get_item(self, item_id: str) -> Optional[dict]:
        """
        Retorna os dados de um item pelo ID.

        Args:
            item_id: ID do item

        Returns:
            Dicionário com dados do item ou None
        """
        return self.state.get(str(item_id))

    def item_exists(self, item_id: str, base_dir_check: bool = True) -> bool:
        """
        Verifica se um item já foi baixado.

        Args:
            item_id: ID do item
            base_dir_check: Se True, também verifica se o arquivo existe

        Returns:
            True se o item existir
        """
        item = self.state.get(str(item_id))
        if not item:
            return False

        if base_dir_check and item.get("caminho_atual"):
            return Path(item["caminho_atual"]).exists()

        return True

    def update_path(self, item_id: str, new_path: str) -> bool:
        """
        Atualiza o caminho de um item após reorganização.

        Args:
            item_id: ID do item
            new_path: Novo caminho do arquivo

        Returns:
            True se atualizado com sucesso
        """
        str_id = str(item_id)
        if str_id in self.state:
            self.state[str_id]["caminho_atual"] = new_path
            self.state[str_id]["updated_at"] = datetime.now().isoformat()
            return self._save()
        return False

    def get_all_downloaded(self) -> list[dict]:
        """
        Retorna lista de todos os itens baixados.

        Returns:
            Lista de dicionários com ID e dados de cada item
        """
        return [
            {"id": k, **v}
            for k, v in self.state.items()
            if v.get("data_download")
        ]

    def get_missing_items(self, items: list[dict]) -> list[dict]:
        """
        Filtra a lista, retornando apenas itens que ainda não foram baixados.

        Args:
            items: Lista de itens a verificar

        Returns:
            Lista de itens que ainda não foram baixados
        """
        missing = []
        for item in items:
            item_id = str(item.get("id", ""))
            if not self.item_exists(item_id, base_dir_check=False):
                missing.append(item)
        return missing

    def remove_item(self, item_id: str) -> bool:
        """
        Remove um item do estado.

        Args:
            item_id: ID do item a remover

        Returns:
            True se removido com sucesso
        """
        str_id = str(item_id)
        if str_id in self.state:
            del self.state[str_id]
            return self._save()
        return False

    def clear_state(self) -> bool:
        """
        Limpa todo o estado (útil para reset).

        Returns:
            True se limpo com sucesso
        """
        self.state = {}
        return self._save()

    def rebuild_from_directory(self, directory: str) -> int:
        """
        Auto-detect: lê arquivos existentes e preenche o state.json.

        Útil para reconstruir o estado a partir de arquivos já organizados.

        Args:
            directory: Diretório para escanear

        Returns:
            Número de itens encontrados e adicionados
        """
        base_path = Path(directory)
        if not base_path.exists():
            logger.warning(f"Diretório não encontrado: {directory}")
            return 0

        count = 0
        for root, dirs, files in os.walk(base_path):
            for filename in files:
                if filename.lower().endswith(('.mp4', '.mkv', '.avi', '.mov')):
                    filepath = Path(root) / filename
                    size = filepath.stat().st_size

                    # Tentar identificar série
                    match = self.SERIE_PATTERN.match(filename)
                    if match:
                        serie, season, episode, title = match.groups()
                        data = {
                            "id": filename.stem,
                            "url": "",
                            "titulo": f"{serie} - S{season}E{episode} - {title}" if title else filename.stem,
                            "serie": serie,
                            "temporada": int(season),
                            "episodio": int(episode),
                            "is_filme": False,
                            "caminho_atual": str(filepath),
                            "tamanho": size,
                            "data_download": datetime.now().isoformat(),
                            "hash": self._file_hash(filepath),
                        }
                    else:
                        # Considerar como filme
                        data = {
                            "id": filename.stem,
                            "url": "",
                            "titulo": filename.stem,
                            "serie": "Filmes",
                            "temporada": None,
                            "episodio": None,
                            "is_filme": True,
                            "caminho_atual": str(filepath),
                            "tamanho": size,
                            "data_download": datetime.now().isoformat(),
                            "hash": self._file_hash(filepath),
                        }

                    self.add_item(filename.stem, data)
                    count += 1

        logger.info(f"Auto-detect concluído: {count} itens encontrados")
        return count

    def _file_hash(self, filepath: Path) -> str:
        """
        Calcula hash MD5 de um arquivo (para detecção de duplicatas).

        Args:
            filepath: Caminho do arquivo

        Returns:
            Hash MD5 em formato hexadecimal
        """
        try:
            hash_md5 = hashlib.md5()
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except IOError as e:
            logger.warning(f"Não foi possível calcular hash de {filepath}: {e}")
            return ""
        except OSError as e:
            logger.warning(f"Erro ao acessar arquivo {filepath}: {e}")
            return ""

    def has_duplicate(self, file_hash: str, item_id: str = None) -> bool:
        """
        Verifica se um hash já existe no state.

        Args:
            file_hash: Hash a procurar
            item_id: ID do item atual (para excluir da busca)

        Returns:
            True se o hash já existir
        """
        if not file_hash:
            return False

        str_id = str(item_id) if item_id else None

        for k, v in self.state.items():
            if str_id and k == str_id:
                continue
            if v.get("hash") == file_hash:
                return True
        return False

    def get_state_size(self) -> int:
        """Retorna o número de itens no estado."""
        return len(self.state)

    def get_state_file_path(self) -> Path:
        """Retorna o caminho do arquivo state.json."""
        return self.state_file