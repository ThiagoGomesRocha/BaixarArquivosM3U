#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M3U Downloader e Organizador para Jellyfin
Parser M3U com extração de metadados
"""

import re
import logging
from pathlib import Path
from typing import Optional, Iterator

from m3u_organizer.utils import extract_id_from_url, sanitize_filename

# Configura logger
logger = logging.getLogger(__name__)


class M3UEntry:
    """
    Representa uma entrada parsada da lista M3U.

    Atributos:
        url: URL do stream/video
        titulo: Título exibido (do EXTINF)
        group_title: Grupo/categoria (do group-title)
        tvg_name: Nome EPG (do tvg-name)
        serie: Nome da série (extraído do título)
        temporada: Número da temporada (extraído do título)
        episodio: Número do episódio (extraído do título)
        is_filme: True se classificado como filme
        id: ID único extraído da URL
        raw_title: Título original sem processamento
    """

    def __init__(self):
        self.url: str = ""
        self.titulo: str = ""
        self.group_title: str = ""
        self.tvg_name: str = ""
        self.serie: str = ""
        self.temporada: Optional[int] = None
        self.episodio: Optional[int] = None
        self.is_filme: bool = False
        self.id: str = ""
        self.raw_title: str = ""

    def to_dict(self) -> dict:
        """Converte a entrada para dicionário."""
        return {
            "id": self.id,
            "url": self.url,
            "titulo": self.titulo,
            "raw_title": self.raw_title,
            "group_title": self.group_title,
            "tvg_name": self.tvg_name,
            "serie": self.serie,
            "temporada": self.temporada,
            "episodio": self.episodio,
            "is_filme": self.is_filme,
        }


class M3UParser:
    """
    Parser para arquivos e URLs M3U/M3U8.

    Implementa um parser baseado em estado para eficiência,
    processando linha a linha sem carregar todo o conteúdo em memoria.
    """

    DEFAULT_SERIE_REGEX = r"^(.*?)[\s_]+S(\d{1,2})E(\d{2})"

    def __init__(self, serie_regex: str = None):
        self.serie_regex = serie_regex or self.DEFAULT_SERIE_REGEX
        self.pattern = re.compile(self.serie_regex, re.IGNORECASE)

    def parse_file(self, filepath: str) -> list[M3UEntry]:
        """
        Lê e parseia um arquivo M3U local.

        Args:
            filepath: Caminho para o arquivo M3U

        Returns:
            Lista de objetos M3UEntry

        Raises:
            FileNotFoundError: Se o arquivo não existir
            IOError: Se houver erro de leitura
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Arquivo M3U não encontrado: {filepath}")

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except IOError as e:
            logger.error(f"Erro ao ler arquivo M3U {filepath}: {e}")
            raise

        return self._parse_content(content)

    def parse_url(self, url: str, timeout: int = 30) -> list[M3UEntry]:
        """
        Baixa e parseia uma lista M3U de uma URL.

        Args:
            url: URL da lista M3U
            timeout: Timeout em segundos (padrão: 30)

        Returns:
            Lista de objetos M3UEntry

        Raises:
            urllib.error.URLError: Se falhar ao baixar
            ValueError: Se a URL for inválida
        """
        import urllib.request
        import ssl
        import urllib.error

        if not url:
            raise ValueError("URL não informada")

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "M3U-Organizer/1.0 (yt-dlp; +https://github.com/yt-dlp/yt-dlp)"}
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
                content = response.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as e:
            logger.error(f"Erro ao baixar M3U de {url}: {e}")
            raise

        return self._parse_content(content)

    def _parse_content(self, content: str) -> list[M3UEntry]:
        """
        Parseia o conteúdo M3U usando parser baseado em estado.

        Refatorado para ser mais eficiente, evitando buscas progressivas
        desnecessárias e iterando diretamente sobre as linhas.

        Args:
            content: Conteúdo do arquivo M3U como string

        Returns:
            Lista de objetos M3UEntry
        """
        entries: list[M3UEntry] = []
        lines = content.strip().splitlines()

        # Estado do parser
        current_extinf: str = ""
        line_index = 0
        total_lines = len(lines)

        # Verifica cabeçalho M3U
        if total_lines > 0 and lines[0].strip().startswith("#EXTM3U"):
            line_index = 1

        while line_index < total_lines:
            line = lines[line_index].strip()
            line_index += 1

            if not line:
                # Linha vazia - ignora
                continue

            if line.startswith("#"):
                if line.startswith("#EXTINF"):
                    # Extrair metadados da tag EXTINF
                    current_extinf = line

                    # Procurar a próxima linha não-vazia como URL
                    while line_index < total_lines:
                        next_line = lines[line_index].strip()
                        if next_line and not next_line.startswith("#"):
                            url = next_line
                            line_index += 1
                            entry = self._create_entry(current_extinf, url)
                            if entry:
                                entries.append(entry)
                            break
                        line_index += 1
                # Outras tags (EXTM3U, etc.) são ignoradas
            else:
                # Linha direta sem EXTINF (formato simplificado M3U)
                entry = M3UEntry()
                entry.url = line
                entry.id = extract_id_from_url(line)
                entry.titulo = entry.id
                entry.raw_title = entry.id
                entry.is_filme = True
                entry.serie = "Filmes"
                entries.append(entry)
                logger.debug(f"Entrada sem EXTINF: {line}")

        logger.info(f"Parseados {len(entries)} itens do M3U")
        return entries

    def _create_entry(self, extinf_line: str, url: str) -> Optional[M3UEntry]:
        """
        Cria uma entrada M3UEntry a partir de metadados EXTINF e URL.

        Refatorado para:
        - Removido o bug crítico 'or True'
        - Classificação precisa de filmes
        - Nomes de variáveis mais descritivos

        Args:
            extinf_line: Linha completa EXTINF (ex: #EXTINF:-1 tvg-id="..." group-title="...", Título)
            url: URL do item

        Returns:
            M3UEntry preenchido ou None se inválido
        """
        m3u_entry = M3UEntry()
        m3u_entry.url = url
        m3u_entry.id = extract_id_from_url(url)

        # Extrair duração e título do EXTINF
        # Formato: #EXTINF:-1 tvg-id="..." tvg-name="..." group-title="...", Título
        extinf_content = extinf_line[len("#EXTINF"):].strip()

        # Encontrar a vírgula que separa os atributos do título
        comma_pos = extinf_content.find(",")
        if comma_pos != -1:
            # Parte antes da vírgula são atributos
            attrs_part = extinf_content[:comma_pos]
            # Título é tudo após a última vírgula (pode conter vírgulas)
            m3u_entry.titulo = extinf_content[comma_pos + 1:].strip()
            m3u_entry.raw_title = m3u_entry.titulo
        else:
            # Nenhum título - usa ID como fallback
            m3u_entry.titulo = m3u_entry.id
            m3u_entry.raw_title = m3u_entry.id
            attrs_part = extinf_content

        # Extrair group-title
        group_match = re.search(r'group-title\s*=\s*"([^"]*)"', attrs_part, re.IGNORECASE)
        if group_match:
            m3u_entry.group_title = group_match.group(1).strip()

        # Extrair tvg-name
        tvg_match = re.search(r'tvg-name\s*=\s*"([^"]*)"', attrs_part, re.IGNORECASE)
        if tvg_match:
            m3u_entry.tvg_name = tvg_match.group(1).strip()

        # Aplicar regex para extrair série/temp/ep
        match = self.pattern.match(m3u_entry.titulo)

        if match:
            # É um episódio de série
            m3u_entry.serie = match.group(1).strip()
            m3u_entry.temporada = int(match.group(2))
            m3u_entry.episodio = int(match.group(3))
            m3u_entry.is_filme = False
        else:
            # Verificar se é filme (grupo ou sem padrão de série)
            # BUG CORRIGIDO: removido 'or True' que classificava tudo como filme
            group_lower = m3u_entry.group_title.lower()
            is_movie_group = "filme" in group_lower or "movie" in group_lower

            m3u_entry.is_filme = is_movie_group

            if not m3u_entry.serie:
                m3u_entry.serie = "Filmes" if m3u_entry.is_filme else "Outros"

        if not url:
            logger.warning(f"Entrada sem URL: {m3u_entry.titulo}")
            return None

        return m3u_entry

    def _extract_id(self, url: str) -> str:
        """
        Extrai um ID único da URL (último número).

        Args:
            url: URL do item

        Returns:
            ID extraído ou hash MD5 como fallback
        """
        return extract_id_from_url(url)