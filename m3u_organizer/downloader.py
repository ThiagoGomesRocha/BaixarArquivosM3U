#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M3U Downloader e Organizador para Jellyfin
Sistema de download com yt-dlp (threading, retry, backoff)
"""

import os
import re
import sys
import json
import time
import logging
import subprocess
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable

# Configura logger
logger = logging.getLogger(__name__)


class DownloadResult:
    """
    Resultado de um download individual.

    Atributos:
        item_id: ID do item baixado
        success: True se o download foi bem-sucedido
        output_file: Caminho do arquivo baixado
        error: Mensagem de erro, se houver
        duration: Duração do download em segundos
    """

    def __init__(self, item_id: str, success: bool, output_file: str = "",
                 error: str = "", duration: float = 0):
        self.item_id = item_id
        self.success = success
        self.output_file = output_file
        self.error = error
        self.duration = duration

    def to_dict(self) -> dict:
        """Converte o resultado para dicionário."""
        return {
            "item_id": self.item_id,
            "success": self.success,
            "output_file": self.output_file,
            "error": self.error,
            "duration": self.duration,
        }


class Downloader:
    """
    Gerencia downloads de arquivos usando yt-dlp com threading e retry.

    Recursos:
    - Downloads paralelos com ThreadPoolExecutor
    - Backoff exponencial para retries
    - Detecção de arquivos baixados
    - Verificação de espaço em disco
    """

    # Extensões de arquivo suportadas
    SUPPORTED_EXTENSIONS = [".mp4", ".mkv", ".webm", ".avi", ".mov", ".mp3"]

    # Timeout máximo por item (10 minutos)
    DEFAULT_TIMEOUT = 600

    def __init__(self, config: dict):
        """
        Inicializa o downloader com configuração.

        Args:
            config: Dicionário de configuração
        """
        self.config = config
        self.retries = config.get("retries", 3)
        base_dir = config.get("base_dir", "")
        
        # Usa temp dentro de base_dir se especificado, senão usa download_dir ou "temp"
        if base_dir:
            self.temp_dir = Path(base_dir) / "temp"
        else:
            self.temp_dir = Path(config.get("download_dir", "temp"))
        
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.yt_dlp_path = config.get("yt_dlp_path", "yt-dlp")
        self.max_concurrent = config.get("max_concurrent_downloads", 3)
        self.cookies_file = config.get("cookies_file", "")

        # Garantir retries positivo
        if self.retries < 1:
            self.retries = 3
            logger.warning("Retries configurado incorretamente, usando padrão (3)")

        logger.debug(f"Downloader inicializado: {self.max_concurrent} workers, {self.retries} retries")

    def download_item(self, m3u_metadata: dict, progress_callback: Callable = None,
                     output_dir: str = None) -> DownloadResult:
        """
        Baixa um item único usando yt-dlp.

        Args:
            m3u_metadata: Dicionário com 'id', 'url', 'titulo'
            progress_callback: Função chamada com progresso (item_id, message)
            output_dir: Diretório de saída (padrão: self.temp_dir)

        Returns:
            DownloadResult com status da operação
        """
        output_dir_path = Path(output_dir) if output_dir else self.temp_dir
        output_dir_path.mkdir(parents=True, exist_ok=True)

        item_id = str(m3u_metadata.get("id", "unknown"))
        url = m3u_metadata.get("url", "")
        titulo = m3u_metadata.get("titulo", item_id)

        if not url:
            if progress_callback:
                progress_callback(item_id, "URL não informada")
            return DownloadResult(item_id, False, error="URL não informada")

        # Nome do arquivo de saída
        output_template = str(output_dir_path / f"{item_id}.%(ext)s")

        # Construir o comando yt-dlp
        cmd = self._build_yt_dlp_command(url, output_template)

        start_time = time.time()
        last_error = ""

        for attempt in range(self.retries):
            if attempt > 0:
                # Backoff exponencial: 2^attempt segundos
                backoff = 2 ** attempt
                if progress_callback:
                    progress_callback(item_id, f"Tentativa {attempt + 1}/{self.retries}, aguardando {backoff}s...")
                time.sleep(backoff)

            try:
                result = self._run_yt_dlp(cmd, item_id, output_template, progress_callback)

                if result.success:
                    return result

                last_error = result.error

            except subprocess.SubprocessError as e:
                last_error = str(e)
                logger.error(f"Subprocess error na tentativa {attempt + 1}: {e}")
            except Exception as e:
                last_error = str(e)
                logger.error(f"Erro inesperado na tentativa {attempt + 1}: {e}")

            if progress_callback:
                progress_callback(item_id, f"Erro na tentativa {attempt + 1}: {last_error}")

        return DownloadResult(
            item_id, False,
            error=f"Falha após {self.retries} tentativas: {last_error}",
            duration=time.time() - start_time
        )

    def _build_yt_dlp_command(self, url: str, output_template: str) -> list[str]:
        """
        Constrói o comando yt-dlp com as opções apropriadas.

        Args:
            url: URL do item
            output_template: Template de saída

        Returns:
            Lista de argumentos para o comando
        """
        cmd = []

        # Usa python -m yt_dlp se configurado assim
        if self.yt_dlp_path.startswith("python"):
            cmd = [sys.executable, "-m", "yt_dlp"]
        elif self.yt_dlp_path == "yt-dlp":
            cmd = ["yt-dlp"]
        else:
            cmd = [self.yt_dlp_path]

        # Opções essenciais
        cmd.extend([
            "--no-overwrites",
            "--output", output_template,
            "--format", "best",
            "--continue",
            "--no-part",  # Remove arquivos .part temporários
        ])

        # Cookies se configurado
        if self.cookies_file and Path(self.cookies_file).exists():
            cmd.extend(["--cookies", self.cookies_file])

        # Controle de qualidade de log
        cmd.append("--no-warnings")

        cmd.append(url)

        return cmd

    def _run_yt_dlp(self, cmd: list[str], item_id: str, output_template: str,
                    progress_callback: Callable = None) -> DownloadResult:
        """
        Executa o comando yt-dlp e monitora progresso.

        Args:
            cmd: Comando a executar
            item_id: ID do item
            output_template: Template de saída
            progress_callback: Função para notificar progresso

        Returns:
            DownloadResult com status da operação
        """
        start_time = time.time()

        if progress_callback:
            progress_callback(item_id, "Iniciando download...")

        try:
            # Executa yt-dlp como subprocesso
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            output_lines = []

            def read_output():
                """Thread para ler saída em tempo real."""
                try:
                    for line in process.stdout:
                        output_lines.append(line.strip())
                        if progress_callback:
                            # yt-dlp envia progresso em formato: [download]   5.0% of ...
                            if "[download]" in line and "%" in line:
                                # Extrair porcentagem
                                pct_match = re.search(r"(\d+\.?\d*)%", line)
                                if pct_match:
                                    pct = pct_match.group(1)
                                    # Extrair speed e eta
                                    speed_match = re.search(r"(\d+\.?\d*\s*[KM]?bits/s)", line)
                                    eta_match = re.search(r"ETA\s+(\d+:\d+)", line)
                                    speed = speed_match.group(1) if speed_match else ""
                                    eta = eta_match.group(1) if eta_match else ""
                                    progress_callback(item_id, f"Baixando: {pct}% ({speed}) ETA: {eta}")
                except Exception as e:
                    logger.error(f"Erro ao ler saída do yt-dlp: {e}")

            import threading
            output_thread = threading.Thread(target=read_output, daemon=True)
            output_thread.start()

            # Timeout configurável
            timeout = self.DEFAULT_TIMEOUT
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.error(f"Timeout após {timeout}s para item {item_id}")
                process.kill()
                process.wait()
                return DownloadResult(
                    item_id, False,
                    error=f"Timeout após {timeout}s",
                    duration=time.time() - start_time
                )

            output_thread.join(timeout=5)

            if process.returncode == 0:
                # Procurar o arquivo baixado
                output_file = self._find_downloaded_file(
                    output_template.replace(".%(ext)s", "")
                )

                logger.info(f"Download concluído: {item_id} -> {output_file}")
                return DownloadResult(
                    item_id, True,
                    output_file=output_file,
                    duration=time.time() - start_time
                )
            else:
                # Extrair mensagens de erro
                error_lines = [l for l in output_lines if "ERROR" in l or "error" in l.lower()]
                error_msg = error_lines[-1] if error_lines else "Erro desconhecido"

                logger.error(f"Download falhou para {item_id}: {error_msg}")
                return DownloadResult(
                    item_id, False,
                    error=error_msg,
                    duration=time.time() - start_time
                )

        except FileNotFoundError as e:
            error_msg = "yt-dlp não encontrado. Instale via 'pip install yt-dlp'"
            logger.error(f"{error_msg}: {e}")
            return DownloadResult(
                item_id, False,
                error=error_msg,
                duration=time.time() - start_time
            )
        except PermissionError as e:
            error_msg = f"Permissão negada: {e}"
            logger.error(f"{error_msg}")
            return DownloadResult(
                item_id, False,
                error=error_msg,
                duration=time.time() - start_time
            )
        except subprocess.SubprocessError as e:
            error_msg = f"Erro de subprocesso: {e}"
            logger.error(f"{error_msg}")
            return DownloadResult(
                item_id, False,
                error=error_msg,
                duration=time.time() - start_time
            )
        except OSError as e:
            error_msg = f"Erro do sistema: {e}"
            logger.error(f"{error_msg}")
            return DownloadResult(
                item_id, False,
                error=error_msg,
                duration=time.time() - start_time
            )

    def _find_downloaded_file(self, base_name: str, returncode: int = 0) -> str:
        """
        Procura o arquivo baixado correspondente.

        Args:
            base_name: Nome base do arquivo sem extensão
            returncode: Código de retorno do processo

        Returns:
            Caminho do arquivo encontrado ou string vazia
        """
        for ext in self.SUPPORTED_EXTENSIONS:
            filepath = f"{base_name}{ext}"
            if Path(filepath).exists():
                return filepath
        return ""

    def download_batch(self, m3u_metadata_list: list[dict],
                      progress_callback: Callable = None) -> dict:
        """
        Baixa múltiplos itens em paralelo.

        Args:
            m3u_metadata_list: Lista de dicionários com metadados
            progress_callback: Função chamada com progresso geral

        Returns:
            Dicionário com estatísticas (total, successful, failed, skipped, results)
        """
        results = {}
        successful = 0
        failed = 0
        skipped = 0

        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            # Submeter todos os downloads
            future_to_item = {
                executor.submit(self.download_item, item, progress_callback): item
                for item in m3u_metadata_list
            }

            # Coletar resultados
            for future in as_completed(future_to_item):
                item = future_to_item[future]
                item_id = str(item.get("id", "unknown"))
                try:
                    result = future.result()
                    results[item_id] = result.to_dict()
                    if result.success:
                        successful += 1
                    else:
                        failed += 1
                except Exception as e:
                    results[item_id] = {"success": False, "error": str(e)}
                    failed += 1
                    logger.error(f"Exceção no download de {item_id}: {e}")

                # Callback geral de progresso
                if progress_callback:
                    try:
                        progress_callback("batch", {
                            "total": len(m3u_metadata_list),
                            "completed": successful + failed + skipped,
                            "successful": successful,
                            "failed": failed,
                            "skipped": skipped
                        })
                    except Exception as cb_error:
                        logger.warning(f"Erro no callback de progresso: {cb_error}")

        logger.info(
            f"Download em lote concluído: {successful} sucesso(s), {failed} falha(s)"
        )

        return {
            "total": len(m3u_metadata_list),
            "successful": successful,
            "failed": failed,
            "skipped": skipped,
            "results": results
        }

    def check_disk_space(self, min_mb: int = 500) -> tuple[bool, str]:
        """
        Verifica se há espaço em disco suficiente.

        Args:
            min_mb: Espaço mínimo necessário em MB

        Returns:
            Tupla (tem_espaço, mensagem)
        """
        try:
            total, used, free = shutil.disk_usage(self.temp_dir)
            free_mb = free // (1024 * 1024)

            if free_mb < min_mb:
                return False, f"Pouco espaço em disco: {free_mb}MB disponível (mínimo: {min_mb}MB)"
            return True, f"{free_mb}MB disponível"

        except OSError as e:
            logger.warning(f"Não foi possível verificar espaço em disco: {e}")
            return True, "Não foi possível verificar espaço em disco"

    def get_download_dir(self) -> Path:
        """Retorna o diretório de download atual."""
        return self.temp_dir