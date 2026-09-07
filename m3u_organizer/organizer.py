#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M3U Downloader e Organizador para Jellyfin
Organizador de arquivos para estrutura Jellyfin
"""

import os
import re
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional


class OrganizationResult:
    """Resultado da organização de um arquivo."""

    def __init__(self, success: bool, old_path: str = "", new_path: str = "",
                 action: str = "", error: str = ""):
        self.success = success
        self.old_path = old_path
        self.new_path = new_path
        self.action = action  # "moved", "copied", "skipped", "duplicate_removed"
        self.error = error

    def to_dict(self):
        return {
            "success": self.success,
            "old_path": self.old_path,
            "new_path": self.new_path,
            "action": self.action,
            "error": self.error,
        }


class Organizer:
    """Organiza arquivos baixados na estrutura de pastas do Jellyfin."""

    def __init__(self, base_dir: str, duplicate_policy: str = "skip"):
        self.base_dir = Path(base_dir)
        self.duplicate_policy = duplicate_policy  # "skip", "overwrite", "ask"

    def organize_item(self, item: dict, source_file: str, 
                     state_manager=None) -> OrganizationResult:
        """
        Organiza um arquivo individual na estrutura Jellyfin.
        
        Args:
            item: Dict com metadados (serie, temporada, episodio, titulo, is_filme)
            source_file: Caminho do arquivo temporário a ser organizado
            state_manager: Opcional, para atualizar state.json
        
        Returns:
            OrganizationResult
        """
        source_path = Path(source_file)

        if not source_path.exists():
            return OrganizationResult(
                success=False, old_path=source_file,
                error="Arquivo de origem não encontrado"
            )

        # Obtém metadados
        serie = item.get("serie", "Outros")
        temporada = item.get("temporada")
        episodio = item.get("episodio")
        titulo = item.get("titulo", source_path.stem)
        is_filme = item.get("is_filme", False)
        item_id = str(item.get("id", source_path.stem))

        # Constrói caminho de destino
        dest_path = self._build_destination_path(serie, temporada, episodio, titulo, is_filme)

        # Verifica duplicata
        if dest_path.exists():
            result = self._handle_duplicate(source_path, dest_path, item_id, state_manager)
            if result:
                return result

        # Cria diretório de destino
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Move o arquivo
        try:
            shutil.move(str(source_path), str(dest_path))
            result = OrganizationResult(
                success=True,
                old_path=str(source_path),
                new_path=str(dest_path),
                action="moved"
            )

            # Atualiza state.json
            if state_manager:
                state_manager.update_path(item_id, str(dest_path))

            return result

        except Exception as e:
            return OrganizationResult(
                success=False, old_path=str(source_path),
                error=f"Erro ao mover arquivo: {e}"
            )

    def _build_destination_path(self, serie: str, temporada: int, 
                               episodio: int, titulo: str, is_filme: bool) -> Path:
        """Constrói o caminho de destino no formato Jellyfin."""
        if is_filme:
            filename = f"{self._sanitize_filename(titulo)}.mp4"
            return self.base_dir / "Filmes" / filename
        else:
            # Extrai o título do episódio removendo o prefixo SxxExx
            episode_title = re.sub(
                r'.*S\d{1,2}E\d{1,2}\s*-\s*', 
                '', titulo, flags=re.IGNORECASE
            )
            if not episode_title or episode_title == titulo:
                episode_title = titulo  # Usa título original se não conseguir extrair
            
            season_dir = f"Season {temporada:02d}"
            filename = f"{serie} - S{temporada:02d}E{episodio:02d} - {self._sanitize_filename(episode_title)}.mp4"
            return self.base_dir / serie / season_dir / filename

    def _handle_duplicate(self, source_path: Path, dest_path: Path, 
                         item_id: str, state_manager) -> Optional[OrganizationResult]:
        """Trata arquivos duplicados conforme a política configurada."""
        
        # Verifica se é realmente um duplicado (mesmo conteúdo)
        if self._is_same_content(source_path, dest_path):
            # Remover duplicata de origem
            try:
                source_path.unlink()
            except Exception:
                pass

            if state_manager:
                state_manager.update_path(item_id, str(dest_path))

            return OrganizationResult(
                success=True,
                old_path=str(source_path),
                new_path=str(dest_path),
                action="duplicate_removed"
            )

        # Não é duplicado ou política diferente
        if self.duplicate_policy == "skip":
            try:
                source_path.unlink()
            except Exception:
                pass
            return OrganizationResult(
                success=True,
                old_path=str(source_path),
                new_path=str(dest_path),
                action="skipped"
            )

        elif self.duplicate_policy == "overwrite":
            try:
                dest_path.unlink()
            except Exception:
                pass
            # Continua para mover o novo arquivo

        elif self.duplicate_policy == "ask":
            # Em modo GUI, isso seria uma pergunta ao usuário
            # Em modo CLI, pergunta diretamente
            print(f"[DUPLICATA] {dest_path.name} já existe. Sobrescrever? (s/n): ", end="")
            response = input().strip().lower()
            if response == "s":
                try:
                    dest_path.unlink()
                except Exception:
                    pass
            else:
                try:
                    source_path.unlink()
                except Exception:
                    pass
                return OrganizationResult(
                    success=True,
                    old_path=str(source_path),
                    new_path=str(dest_path),
                    action="skipped"
                )

        return None  # Continua com o movimento

    def _is_same_content(self, file1: Path, file2: Path) -> bool:
        """Verifica se dois arquivos têm o mesmo conteúdo via hash."""
        if file1.stat().st_size != file2.stat().st_size:
            return False

        return self._hash_file(file1) == self._hash_file(file2)

    def _hash_file(self, filepath: Path) -> str:
        """Calcula hash SHA256 de um arquivo."""
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _sanitize_filename(self, name: str) -> str:
        """Remove caracteres inválidos para sistemas de arquivos."""
        # Remove caracteres proibidos no Windows
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
        # Limita tamanho
        if len(name) > 150:
            name = name[:150]
        return name.strip()

    def organize_directory(self, source_dir: Path, items: list[dict],
                          state_manager=None, progress_callback=None) -> dict:
        """
        Organiza todos os arquivos em um diretório temporário.
        
        Args:
            source_dir: Diretório com arquivos baixados
            items: Lista de metadados para mapear arquivos
            state_manager: Para atualizar state.json
        
        Returns:
            Dicionário com estatísticas
        """
        stats = {"moved": 0, "skipped": 0, "duplicates_removed": 0, "errors": 0, "results": []}
        item_map = {str(item.get("id", "")): item for item in items}

        for filepath in sorted(source_dir.glob("*.[mMrR][pP][4vV]")) + \
                      sorted(source_dir.glob("*.[mM][kK][vV]")) + \
                      sorted(source_dir.glob("*.[aA][vV][iI]")) + \
                      sorted(source_dir.glob("*.[mM][oO][vV]")):
            
            # Extrai ID do nome do arquivo
            file_id = filepath.stem
            item = item_map.get(file_id)

            if not item:
                # Tenta extrair ID numérico da URL se item não encontrado
                if state_manager:
                    item_data = state_manager.get_item(file_id)
                    if item_data:
                        item = item_data

            if item:
                result = self.organize_item(item, str(filepath), state_manager)
            else:
                # Não tem metadados - tenta organizar como filme
                item = {
                    "serie": filepath.stem,
                    "titulo": filepath.stem,
                    "is_filme": True,
                    "id": file_id
                }
                result = self.organize_item(item, str(filepath), state_manager)

            stats["results"].append(result.to_dict())

            if result.success:
                if result.action == "moved":
                    stats["moved"] += 1
                elif result.action == "skipped":
                    stats["skipped"] += 1
                elif result.action == "duplicate_removed":
                    stats["duplicates_removed"] += 1
            else:
                stats["errors"] += 1

            if progress_callback:
                progress_callback(file_id, result)

        return stats
