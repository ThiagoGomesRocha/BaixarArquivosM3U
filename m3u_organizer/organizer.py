#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M3U Downloader e Organizador para Jellyfin
Organizador de arquivos para estrutura Jellyfin
"""

import os
import re
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Union

from m3u_organizer.utils import sanitize_filename, calculate_file_hash, get_supported_video_extensions
from m3u_organizer.m3u_parser import M3UEntry

# Configura logger
logger = logging.getLogger(__name__)


class OrganizationResult:
    """
    Resultado da organização de um arquivo.

    Atributos:
        success: True se a operação foi bem-sucedida
        old_path: Caminho original do arquivo
        new_path: Caminho novo após organização
        action: Tipo de ação ("moved", "copied", "skipped", "duplicate_removed")
        error: Mensagem de erro, se houver
    """

    def __init__(self, success: bool, old_path: str = "", new_path: str = "",
                 action: str = "", error: str = ""):
        self.success = success
        self.old_path = old_path
        self.new_path = new_path
        self.action = action  # "moved", "copied", "skipped", "duplicate_removed"
        self.error = error

    def to_dict(self) -> dict:
        """Converte o resultado para dicionário."""
        return {
            "success": self.success,
            "old_path": self.old_path,
            "new_path": self.new_path,
            "action": self.action,
            "error": self.error,
        }


class Organizer:
    """
    Organiza arquivos baixados na estrutura de pastas do Jellyfin.

    Fornece funcionalidades para:
    - Construir caminhos de destino compatíveis com Jellyfin
    - Gerenciar arquivos duplicados
    - Organizar arquivos em lote
    """

    # Extensões de vídeo suportadas
    SUPPORTED_EXTENSIONS = tuple(get_supported_video_extensions())

    def __init__(self, base_dir: str, duplicate_policy: str = "skip",
                 duplicate_decision_callback: Optional[Callable[[str, str], bool]] = None):
        """
        Inicializa o organizador.

        Args:
            base_dir: Diretório base para organização
            duplicate_policy: Política para duplicatas ("skip", "overwrite", "ask")
            duplicate_decision_callback: Callback para política "ask" (recebe old_path, new_path, retorna bool)
        """
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.duplicate_policy = duplicate_policy.lower() if duplicate_policy else "skip"
        self._duplicate_decision_callback = duplicate_decision_callback

        # Validar política
        if self.duplicate_policy not in ("skip", "overwrite", "ask"):
            logger.warning(f"Política de duplicata inválida '{duplicate_policy}', usando 'skip'")
            self.duplicate_policy = "skip"

    def _extract_metadata(self, m3u_metadata: Union[dict, M3UEntry]) -> dict:
        """Extrai metadados de um item (dicionário ou M3UEntry)."""
        if isinstance(m3u_metadata, M3UEntry):
            return {
                "id": m3u_metadata.id,
                "serie": m3u_metadata.serie,
                "temporada": m3u_metadata.temporada,
                "episodio": m3u_metadata.episodio,
                "titulo": m3u_metadata.titulo,
                "is_filme": m3u_metadata.is_filme,
            }
        return m3u_metadata

    def organize_item(self, m3u_metadata: Union[dict, M3UEntry], source_file: str,
                      state_manager=None) -> OrganizationResult:
        """
        Organiza um arquivo individual na estrutura Jellyfin.

        Args:
            m3u_metadata: Dicionário com metadados (serie, temporada, episodio, titulo, is_filme)
            source_file: Caminho do arquivo temporário a ser organizado
            state_manager: Opcional, para atualizar state.json

        Returns:
            OrganizationResult com status da operação
        """
        source_path = Path(source_file)

        if not source_path.exists():
            logger.error(f"Arquivo de origem não encontrado: {source_file}")
            return OrganizationResult(
                success=False, old_path=source_file,
                error="Arquivo de origem não encontrado"
            )

        # Verifica espaço em disco
        if not self._check_disk_space():
            return OrganizationResult(
                success=False, old_path=source_file,
                error="Espaço insuficiente em disco"
            )

        # Converte M3UEntry para dicionário se necessário
        m3u_metadata = self._extract_metadata(m3u_metadata)

        # Obtém metadados
        serie_title = m3u_metadata.get("serie", "Outros")
        temporada = m3u_metadata.get("temporada")
        episodio = m3u_metadata.get("episodio")
        titulo = m3u_metadata.get("titulo", source_path.stem)
        is_filme = m3u_metadata.get("is_filme", False)
        item_id = str(m3u_metadata.get("id", source_path.stem))

        # Constrói caminho de destino
        dest_path = self._build_destination_path(
            serie_title, temporada, episodio, titulo, is_filme
        )

        # Verifica duplicata
        if dest_path.exists():
            result = self._handle_duplicate(
                source_path, dest_path, item_id, state_manager
            )
            if result:
                return result

        # Cria diretório de destino
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Erro ao criar diretório destino: {e}")
            return OrganizationResult(
                success=False, old_path=source_file,
                error=f"Erro ao criar diretório: {e}"
            )

        # Move o arquivo
        try:
            shutil.move(str(source_path), str(dest_path))
            download_result = OrganizationResult(
                success=True,
                old_path=str(source_path),
                new_path=str(dest_path),
                action="moved"
            )

            # Atualiza state.json
            if state_manager:
                state_manager.update_path(item_id, str(dest_path))

            logger.info(f"Arquivo organizado: {dest_path}")
            return download_result

        except (OSError, shutil.Error) as e:
            logger.error(f"Erro ao mover arquivo {source_path} para {dest_path}: {e}")
            return OrganizationResult(
                success=False, old_path=str(source_path),
                error=f"Erro ao mover arquivo: {e}"
            )

    def _build_destination_path(self, serie: str, temporada: int,
                               episodio: int, titulo: str, is_filme: bool) -> Path:
        """
        Constrói o caminho de destino no formato Jellyfin.

        Args:
            serie: Nome da série ou "Filmes"
            temporada: Número da temporada (None para filmes)
            episodio: Número do episódio (None para filmes)
            titulo: Título do episódio ou filme
            is_filme: True se for um filme

        Returns:
            Path completo para o arquivo de destino
        """
        if is_filme:
            filename = f"{sanitize_filename(titulo)}.mp4"
            return self.base_dir / "Filmes" / filename
        else:
            # Extrair o título do episódio removendo o prefixe SxxExx
            episode_title = re.sub(
                r'.*S\d{1,2}E\d{1,2}\s*-\s*',
                '', titulo, flags=re.IGNORECASE
            )
            if not episode_title or episode_title == titulo:
                episode_title = titulo  # Usa título original se não conseguir extrair

            season_dir = f"Season {temporada:02d}" if temporada else "Season 00"
            filename = (
                f"{sanitize_filename(serie)} - "
                f"S{temporada:02d}E{episodio:02d} - "
                f"{sanitize_filename(episode_title)}.mp4"
            )
            return self.base_dir / serie / season_dir / filename

    def _handle_duplicate(self, source_path: Path, dest_path: Path,
                          item_id: str, state_manager) -> Optional[OrganizationResult]:
        """
        Trata arquivos duplicados conforme a política configurada.

        Refatorado para:
        - Remover print/input que travava a GUI
        - Usar callback para política "ask"
        - Logs embutidos para debugging

        Args:
            source_path: Caminho do arquivo fonte
            dest_path: Caminho do arquivo de destino (duplicata)
            item_id: ID do item
            state_manager: Gerenciador de estado opcional

        Returns:
            OrganizationResult ou None para continuar com o movimento
        """
        # Verifica se é realmente um duplicado (mesmo conteúdo)
        is_same = self._is_same_content(source_path, dest_path)

        if is_same:
            # É uma duplicata real - remover a fonte
            try:
                source_path.unlink()
                logger.info(f"Duplicata removida: {source_path}")
            except OSError as e:
                logger.warning(f"Não foi possível remover duplicata {source_path}: {e}")

            if state_manager:
                state_manager.update_path(item_id, str(dest_path))

            return OrganizationResult(
                success=True,
                old_path=str(source_path),
                new_path=str(dest_path),
                action="duplicate_removed"
            )

        # Não é duplicado - aplicar política
        if self.duplicate_policy == "skip":
            try:
                source_path.unlink()
                logger.info(f"Arquivo ignorado (duplicata de conteúdo diferente): {source_path}")
            except OSError as e:
                logger.warning(f"Não foi possível remover arquivo ignorado {source_path}: {e}")

            return OrganizationResult(
                success=True,
                old_path=str(source_path),
                new_path=str(dest_path),
                action="skipped"
            )

        elif self.duplicate_policy == "overwrite":
            try:
                dest_path.unlink()
                logger.info(f"Sobrescrita: {dest_path}")
            except OSError as e:
                logger.error(f"Não foi possível sobrescrever {dest_path}: {e}")
                # Continua tentando mover

        elif self.duplicate_policy == "ask":
            # Usar callback da GUI se disponível
            if self._duplicate_decision_callback:
                try:
                    should_overwrite = self._duplicate_decision_callback(
                        str(source_path), str(dest_path)
                    )
                    if not should_overwrite:
                        try:
                            source_path.unlink()
                            logger.info(f"Duplicata rejeitada pelo usuário: {source_path}")
                        except OSError as e:
                            logger.warning(f"Erro ao remover arquivo rejeitado: {e}")

                        return OrganizationResult(
                            success=True,
                            old_path=str(source_path),
                            new_path=str(dest_path),
                            action="skipped"
                        )
                    else:
                        try:
                            dest_path.unlink()
                            logger.info(f"Duplicata sobrescrita pelo usuário: {dest_path}")
                        except OSError as e:
                            logger.error(f"Não foi possível sobrescrever: {e}")
                except Exception as e:
                    logger.error(f"Erro no callback de decisão de duplicata: {e}")
                    # Default: skip
                    return self._handle_duplicate(
                        source_path, dest_path, item_id, state_manager
                    )
            else:
                # Sem callback (modo CLI), usar comportamento padrão
                logger.warning(
                    "Política 'ask' sem callback - usando 'skip' como padrão"
                )
                try:
                    source_path.unlink()
                except OSError:
                    pass

                return OrganizationResult(
                    success=True,
                    old_path=str(source_path),
                    new_path=str(dest_path),
                    action="skipped"
                )

        return None  # Continua com o movimento

    def _is_same_content(self, file1: Path, file2: Path) -> bool:
        """
        Verifica se dois arquivos têm o mesmo conteúdo.

        Otimizado para comparação eficiente:
        1. Size comparison (rápido)
        2. Modification time comparison (rápido)
        3. Hash parcial (SHA256) apenas se necessário

        Args:
            file1: Primeiro arquivo
            file2: Segundo arquivo

        Returns:
            True se os arquivos tiverem o mesmo conteúdo
        """
        try:
            stat1 = file1.stat()
            stat2 = file2.stat()
        except OSError as e:
            logger.error(f"Erro ao obter stats de arquivos: {e}")
            return False

        # Comparação rápida de tamanho
        if stat1.st_size != stat2.st_size:
            return False

        # Comparação rápida de data de modificação
        # Permite tolerância de 2 segundos para erros de clock
        if abs(stat1.st_mtime - stat2.st_mtime) > 2:
            # Se datas diferentes, ainda pode ser o mesmo conteúdo
            # (ex: cópia preservando datos mas reescrevendo)
            pass

        # Cálculo de hash parcial (primeiros e últimos 1MB)
        # Mais eficiente que hash completo para arquivos grandes
        hash1 = calculate_file_hash(file1, partial=True)
        hash2 = calculate_file_hash(file2, partial=True)

        return hash1 == hash2 and hash1 != ""

    def _hash_file(self, filepath: Path) -> str:
        """
        Calcula hash SHA256 de um arquivo.

        Args:
            filepath: Caminho do arquivo

        Returns:
            Hash SHA256 em hexadecimal
        """
        return calculate_file_hash(filepath)

    def _sanitize_filename(self, name: str) -> str:
        """
        Remove caracteres inválidos para sistemas de arquivos.

        Args:
            name: Nome a ser sanitizado

        Returns:
            Nome sanitizado
        """
        return sanitize_filename(name)

    def _check_disk_space(self, min_mb: int = 500) -> bool:
        """
        Verifica se há espaço em disco suficiente.

        Args:
            min_mb: Espaço mínimo necessário em MB

        Returns:
            True se houver espaço suficiente
        """
        try:
            total, used, free = shutil.disk_usage(self.base_dir)
            free_mb = free // (1024 * 1024)

            if free_mb < min_mb:
                logger.error(f"Pouco espaço em disco: {free_mb}MB disponível (mínimo: {min_mb}MB)")
                return False

            return True

        except OSError as e:
            logger.warning(f"Não foi possível verificar espaço em disco: {e}")
            return True  # Assume OK se não puder verificar

    def organize_directory(self, source_dir: Path, m3u_metadata_list: list[dict],
                          state_manager=None, progress_callback=None) -> dict:
        """
        Organiza todos os arquivos em um diretório temporário.

        Refatorado para:
        - Usar glob único com padrão de extensões
        - Nomes de variáveis mais descritivos
        - Logs detalhados

        Args:
            source_dir: Diretório com arquivos baixados
            m3u_metadata_list: Lista de metadados para mapear arquivos
            state_manager: Para atualizar state.json
            progress_callback: Callback para notificar progresso

        Returns:
            Dicionário com estatísticas (moved, skipped, duplicates_removed, errors, results)
        """
        stats = {
            "moved": 0,
            "skipped": 0,
            "duplicates_removed": 0,
            "errors": 0,
            "results": []
        }

        # Mapeamento por ID para busca rápida
        def get_metadata_id(item):
            """Obtém ID de item (dict ou M3UEntry)."""
            if isinstance(item, M3UEntry):
                return str(item.id) if item.id else ""
            return str(item.get("id", ""))
        
        metadata_map = {get_metadata_id(item): item for item in m3u_metadata_list}

        # Usa padrão glob único para todas as extensões de vídeo
        # Cria padrão case-insensitive
        for ext in self.SUPPORTED_EXTENSIONS:
            pattern = f"*{ext}"
            for filepath in sorted(source_dir.glob(pattern)):
                # Extrair ID do nome do arquivo
                file_id = filepath.stem

                # Buscar metadados
                download_result_metadata = metadata_map.get(file_id)

                if not download_result_metadata:
                    # Tentar buscar no state_manager
                    if state_manager:
                        stored_metadata = state_manager.get_item(file_id)
                        if stored_metadata:
                            download_result_metadata = stored_metadata

                if download_result_metadata:
                    result = self.organize_item(
                        download_result_metadata, str(filepath), state_manager
                    )
                else:
                    # Sem metadados - organizar como filme com nome do arquivo
                    logger.info(f"Sem metadados, organizando como filme: {filepath}")
                    fallback_metadata = {
                        "serie": filepath.stem,
                        "titulo": filepath.stem,
                        "is_filme": True,
                        "id": file_id
                    }
                    result = self.organize_item(fallback_metadata, str(filepath), state_manager)

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
                    try:
                        progress_callback(file_id, result)
                    except Exception as e:
                        logger.warning(f"Erro no callback de progresso: {e}")

        logger.info(
            f"Organização concluída: {stats['moved']} movidos, "
            f"{stats['duplicates_removed']} duplicatas removidas, "
            f"{stats['skipped']} ignorados, {stats['errors']} erros"
        )

        return stats

    def check_path_exists(self, item_id: str, state_manager=None) -> bool:
        """
        Verifica se um item já foi baixado.

        Args:
            item_id: ID do item
            state_manager: Gerenciador de estado

        Returns:
            True se o item já existir
        """
        if not state_manager:
            return False

        item = state_manager.get_item(str(item_id))
        if not item:
            return False

        if item.get("caminho_atual"):
            return Path(item["caminho_atual"]).exists()

        return True