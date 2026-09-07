#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M3U Downloader e Organizador para Jellyfin
Sistema de gerenciamento de estado persistente (state.json)
"""

import json
import os
import hashlib
from datetime import datetime
from pathlib import Path


class StateManager:
    """Gerencia o estado persistente dos downloads e organização."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.state_file = self.base_dir / "state.json"
        self.state = {}
        self._load()

    def _load(self):
        """Carrega o estado do arquivo state.json."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self.state = json.load(f)
                print(f"[STATE] Carregado {len(self.state)} itens do state.json")
            except (json.JSONDecodeError, IOError) as e:
                print(f"[WARN] Não foi possível carregar state.json: {e}")
                self.state = {}
        else:
            self.state = {}

    def _save(self):
        """Salva o estado no arquivo state.json."""
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"[ERROR] Não foi possível salvar state.json: {e}")

    def add_item(self, item_id: str, data: dict):
        """Adiciona ou atualiza um item no estado."""
        data["updated_at"] = datetime.now().isoformat()
        self.state[item_id] = data
        self._save()

    def get_item(self, item_id: str) -> dict | None:
        """Retorna os dados de um item pelo ID."""
        return self.state.get(str(item_id))

    def item_exists(self, item_id: str, base_dir_check: bool = True) -> bool:
        """
        Verifica se um item já foi baixado.
        Se base_dir_check=True, também verifica se o arquivo realmente existe.
        """
        item = self.state.get(str(item_id))
        if not item:
            return False

        if base_dir_check and item.get("caminho_atual"):
            return Path(item["caminho_atual"]).exists()

        return True

    def update_path(self, item_id: str, new_path: str):
        """Atualiza o caminho de um item após reorganização."""
        if str(item_id) in self.state:
            self.state[str(item_id)]["caminho_atual"] = new_path
            self.state[str(item_id)]["updated_at"] = datetime.now().isoformat()
            self._save()

    def get_all_downloaded(self) -> list:
        """Retorna lista de todos os itens baixados."""
        return [
            {"id": k, **v}
            for k, v in self.state.items()
            if v.get("data_download")
        ]

    def get_missing_items(self, items: list[dict]) -> list[dict]:
        """Filtra a lista, retornando apenas itens que ainda não foram baixados."""
        missing = []
        for item in items:
            item_id = str(item.get("id", ""))
            if not self.item_exists(item_id):
                missing.append(item)
        return missing

    def rebuild_from_directory(self, base_dir: str):
        """Auto-detect: lê arquivos existentes e preenche o state.json."""
        base_path = Path(base_dir)
        if not base_path.exists():
            return

        # Padrões conhecidos para extração de Série/Temporada/Episódio
        import re
        serie_pattern = re.compile(r"^(.*?)\s+-\s+S(\d+)E(\d+)\s*-\s*(.+)$")
        filme_pattern = re.compile(r"^(.+)\.mp4$")

        count = 0
        for root, dirs, files in os.walk(base_path):
            for filename in files:
                if filename.lower().endswith((".mp4", ".mkv", ".avi", ".mov")):
                    filepath = Path(root) / filename
                    size = filepath.stat().st_size

                    # Tenta identificar série
                    match = serie_pattern.match(filename)
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

        print(f"[STATE] Auto-detect completado: {count} itens encontrados")

    def _file_hash(self, filepath: Path) -> str:
        """Calcula hash MD5 de um arquivo (para detecção de duplicatas)."""
        try:
            hash_md5 = hashlib.md5()
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            print(f"[WARN] Não foi possível hash do arquivo {filepath}: {e}")
            return ""

    def has_duplicate(self, file_hash: str, item_id: str = None) -> bool:
        """Verifica se um hash já existe no state."""
        for k, v in self.state.items():
            if item_id and k == item_id:
                continue
            if v.get("hash") == file_hash:
                return True
        return False
