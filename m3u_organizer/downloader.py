#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M3U Downloader e Organizador para Jellyfin
Sistema de download com yt-dlp (threading, retry, backoff)
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable
from datetime import datetime


class DownloadResult:
    """Resultado de um download individual."""

    def __init__(self, item_id: str, success: bool, output_file: str = "", 
                 error: str = "", duration: float = 0):
        self.item_id = item_id
        self.success = success
        self.output_file = output_file
        self.error = error
        self.duration = duration

    def to_dict(self):
        return {
            "item_id": self.item_id,
            "success": self.success,
            "output_file": self.output_file,
            "error": self.error,
            "duration": self.duration,
        }


class Downloader:
    """Gerencia downloads de arquivos usando yt-dlp com threading e retry."""

    def __init__(self, config: dict):
        self.config = config
        self.retries = config.get("retries", 3)
        self.temp_dir = Path(config.get("download_dir", "temp"))
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.yt_dlp_path = config.get("yt_dlp_path", "yt-dlp")
        self.max_concurrent = config.get("max_concurrent_downloads", 3)
        self.cookies_file = config.get("cookies_file", "")

    def download_item(self, item: dict, progress_callback: Callable = None,
                     output_dir: str = None) -> DownloadResult:
        """
        Baixa um item único usando yt-dlp.
        
        Args:
            item: Dicionário com 'id', 'url', 'titulo'
            progress_callback: Função chamada com progresso (percent, speed, eta)
            output_dir: Diretório de saída (padrão: self.temp_dir)
        
        Returns:
            DownloadResult com status da operação
        """
        output_dir = Path(output_dir) if output_dir else self.temp_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        item_id = str(item.get("id", "unknown"))
        url = item.get("url", "")
        titulo = item.get("titulo", item_id)

        if not url:
            return DownloadResult(item_id, False, error="URL não informada")

        # Nome do arquivo de saída
        output_template = str(output_dir / f"{item_id}.%(ext)s")

        # Constrói o comando yt-dlp
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
                result = self._run_yt_dlp(cmd, item_id, progress_callback)

                if result.success:
                    return result

                last_error = result.error

            except Exception as e:
                last_error = str(e)
                if progress_callback:
                    progress_callback(item_id, f"Erro na tentativa {attempt + 1}: {e}")

        return DownloadResult(
            item_id, False, 
            error=f"Falha após {self.retries} tentativas: {last_error}",
            duration=time.time() - start_time
        )

    def _build_yt_dlp_command(self, url: str, output_template: str) -> list[str]:
        """Constrói o comando yt-dlp com as opções apropriadas."""
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

    def _run_yt_dlp(self, cmd: list[str], item_id: str,
                    progress_callback: Callable = None) -> DownloadResult:
        """Executa o comando yt-dlp e monitora progresso."""
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
                for line in process.stdout:
                    output_lines.append(line.strip())
                    if progress_callback:
                        # yt-dlp envia progresso em formato: [download]   5.0% of ...
                        if "[download]" in line and "%" in line:
                            # Extrai porcentagem
                            import re
                            pct_match = re.search(r"(\d+\.?\d*)%", line)
                            if pct_match:
                                pct = pct_match.group(1)
                                # Extrai speed e eta
                                speed_match = re.search(r"(\d+\.?\d*\s*[KM]?bits/s)", line)
                                eta_match = re.search(r"ETA\s+(\d+:\d+)", line)
                                speed = speed_match.group(1) if speed_match else ""
                                eta = eta_match.group(1) if eta_match else ""
                                progress_callback(item_id, f"Baixando: {pct}% ({speed}) ETA: {eta}")

            import threading
            output_thread = threading.Thread(target=read_output, daemon=True)
            output_thread.start()

            # Timeout configurável (padrão 10 minutos por item)
            timeout = 600
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                return DownloadResult(
                    item_id, False,
                    error=f"Timeout após {timeout}s",
                    duration=time.time() - start_time
                )

            output_thread.join(timeout=5)

            if process.returncode == 0:
                # Procura o arquivo baixado
                output_file = self._find_downloaded_file(output_template.replace(".%(ext)s", ""), process.returncode)
                
                return DownloadResult(
                    item_id, True,
                    output_file=output_file,
                    duration=time.time() - start_time
                )
            else:
                error_lines = [l for l in output_lines if "ERROR" in l or "error" in l.lower()]
                error_msg = error_lines[-1] if error_lines else "Erro desconhecido"
                
                return DownloadResult(
                    item_id, False,
                    error=error_msg,
                    duration=time.time() - start_time
                )

        except FileNotFoundError:
            return DownloadResult(
                item_id, False,
                error="yt-dlp não encontrado. Instale via 'pip install yt-dlp'",
                duration=time.time() - start_time
            )
        except Exception as e:
            return DownloadResult(
                item_id, False,
                error=str(e),
                duration=time.time() - start_time
            )

    def _find_downloaded_file(self, base_name: str, returncode: int) -> str:
        """Procura o arquivo baixado correspondente."""
        for ext in [".mp4", ".mkv", ".webm", ".avi", ".mov", ".mp3"]:
            filepath = f"{base_name}{ext}"
            if Path(filepath).exists():
                return filepath
        return ""

    def download_batch(self, items: list[dict], progress_callback: Callable = None) -> dict:
        """
        Baixa múltiplos itens em paralelo.
        
        Returns dict com estatísticas.
        """
        results = {}
        successful = 0
        failed = 0
        skipped = 0

        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            # Submete todos os downloads
            future_to_item = {
                executor.submit(self.download_item, item, progress_callback): item
                for item in items
            }

            # Coleta resultados
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

                # Callback geral de progresso
                if progress_callback:
                    progress_callback("batch", {
                        "total": len(items),
                        "completed": successful + failed + skipped,
                        "successful": successful,
                        "failed": failed,
                        "skipped": skipped
                    })

        return {
            "total": len(items),
            "successful": successful,
            "failed": failed,
            "skipped": skipped,
            "results": results
        }

    def check_disk_space(self, min_mb: int = 500) -> tuple[bool, str]:
        """Verifica se há espaço em disco suficiente."""
        try:
            usage = os.statvfs(self.temp_dir) if hasattr(os, 'statvfs') else None
            
            if usage is None:
                # Windows fallback
                import shutil
                total, used, free = shutil.disk_usage(self.temp_dir)
                free_mb = free // (1024 * 1024)
            else:
                free_mb = (usage.f_bavail * usage.f_frsize) // (1024 * 1024)
            
            if free_mb < min_mb:
                return False, f"Pouco espaço em disco: {free_mb}MB disponível (mínimo: {min_mb}MB)"
            return True, f"{free_mb}MB disponível"
        except Exception as e:
            return True, "Não foi possível verificar espaço em disco"
