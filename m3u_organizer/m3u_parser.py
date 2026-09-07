#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M3U Downloader e Organizador para Jellyfin
Parser M3U com extração de metadados
"""

import re
import os
from pathlib import Path
from typing import Optional


class M3UEntry:
    """Representa uma entrada parsada da lista M3U."""

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
    """Parser para arquivos e URLs M3U/M3U8."""

    DEFAULT_SERIE_REGEX = r"^(.*?)\s+S(\d+)E(\d+)"

    def __init__(self, serie_regex: str = None):
        self.serie_regex = serie_regex or self.DEFAULT_SERIE_REGEX
        self.pattern = re.compile(self.serie_regex, re.IGNORECASE)

    def parse_file(self, filepath: str) -> list[M3UEntry]:
        """Lê e parseia um arquivo M3U local."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Arquivo M3U não encontrado: {filepath}")

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        return self._parse_content(content)

    def parse_url(self, url: str, timeout: int = 30) -> list[M3UEntry]:
        """Baixa e parseia uma lista M3U de uma URL."""
        import urllib.request
        import ssl

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "M3U-Organizer/1.0 (yt-dlp; +https://github.com/yt-dlp/yt-dlp)"}
        )

        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
            content = response.read().decode("utf-8", errors="replace")

        return self._parse_content(content)

    def _parse_content(self, content: str) -> list[M3UEntry]:
        """Parseia o conteúdo M3U em lista de entradas."""
        entries = []
        lines = content.strip().splitlines()

        i = 0
        # Verifica se começa com #EXTM3U
        if lines and lines[0].strip().startswith("#EXTM3U"):
            i = 1

        while i < len(lines):
            line = lines[i].strip()

            if line.startswith("#"):
                # É uma linha EXTINF ou tag
                if line.startswith("#EXTINF"):
                    # Extrai metadados da tag EXTINF
                    extinf = line[len("#EXTINF"):]

                    # Procura a próxima linha como URL
                    i += 1
                    while i < len(lines) and (lines[i].strip().startswith("#") or not lines[i].strip()):
                        i += 1

                    if i < len(lines):
                        url = lines[i].strip()
                        entry = self._create_entry(extinf, url)
                        if entry:
                            entries.append(entry)
                i += 1
            elif line:
                # Linha direta sem EXTINF (raremente usado)
                url = line
                entry = M3UEntry()
                entry.url = url
                entry.id = self._extract_id(url)
                entry.titulo = entry.id
                entry.raw_title = ""
                entry.is_filme = True
                entries.append(entry)
                i += 1
            else:
                i += 1

        return entries

    def _create_entry(self, extinf_line: str, url: str) -> Optional[M3UEntry]:
        """Cria uma entrada M3UEntry a partir de metadados EXTINF e URL."""
        entry = M3UEntry()
        entry.url = url
        entry.id = self._extract_id(url)

        # Extrai duração e título do EXTINF
        # Formato: #EXTINF:-1 tvg-id="..." tvg-name="..." group-title="...", Título
        parts = extinf_line.split(",", 1)

        # O título é a parte após a última vírgula
        if len(parts) > 1:
            entry.titulo = parts[1].strip()
            entry.raw_title = entry.titulo
        else:
            entry.titulo = entry.id
            entry.raw_title = entry.id

        # Extrai atributos antes da vírgula
        attrs_part = parts[0] if parts else ""

        # Extrai group-title
        group_match = re.search(r'group-title\s*=\s*"([^"]*)"', attrs_part, re.IGNORECASE)
        if group_match:
            entry.group_title = group_match.group(1)

        # Extrai tvg-name
        tvg_match = re.search(r'tvg-name\s*=\s*"([^"]*)"', attrs_part, re.IGNORECASE)
        if tvg_match:
            entry.tvg_name = tvg_match.group(1)

        # Aplica regex para extrair série/temp/ep
        match = self.pattern.match(entry.titulo)
        if match:
            entry.serie = match.group(1).strip()
            entry.temporada = int(match.group(2))
            entry.episodio = int(match.group(3))
            entry.is_filme = False
        else:
            # Clasifica como filme
            entry.is_filme = (
                "filme" in entry.group_title.lower()
                or "movie" in entry.group_title.lower()
                or True  # Se não bate o padrão, considera filme
            )
            if not entry.serie:
                entry.serie = "Filmes" if entry.is_filme else "Outros"

        return entry

    def _extract_id(self, url: str) -> str:
        """Extrai um ID único da URL (último número)."""
        # Tenta extrair número após a barra
        match = re.search(r"/(\d+)\.\w+$", url)
        if match:
            return match.group(1)

        # Usa hash da URL como fallback
        import hashlib
        return hashlib.md5(url.encode()).hexdigest()[:12]

    def get_entries_dict(self) -> dict:
        """Retorna entradas organizadas hierarquicamente."""
        pass