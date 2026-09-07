#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
M3U Downloader e Organizador para Jellyfin
Interface Gráfica PySide6
"""

import os
import json
import re
import sys
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QLineEdit, QPushButton, QProgressBar,
    QTextEdit, QLabel, QFileDialog, QCheckBox, QFrame, QSpacerItem,
    QSizePolicy, QGroupBox, QSplitter, QMenu, QMessageBox, QStyle, QStyleFactory, QHeaderView
)
from PySide6.QtCore import Qt, Signal, QThread, QSize, QDir, QUrl
from PySide6.QtGui import QFont, QColor, QTextCursor, QIcon, QAction, QDesktopServices

# Importa módulos internos
from m3u_organizer.m3u_parser import M3UParser, M3UEntry
from m3u_organizer.downloader import Downloader, DownloadResult
from m3u_organizer.organizer import Organizer, OrganizationResult
from m3u_organizer.state_manager import StateManager


class DownloadThread(QThread):
    """Thread para gerenciar downloads sem travar a UI."""
    
    progress_update = Signal(str, str)  # item_id, message
    download_finished = Signal(str, dict)  # item_id, result
    batch_finished = Signal(dict)  # stats

    def __init__(self, downloader: Downloader, items: list[dict]):
        super().__init__()
        self.downloader = downloader
        self.items = items
        self._cancelled = False

    def run(self):
        def progress_callback(item_id, message):
            if self._cancelled:
                return
            self.progress_update.emit(str(item_id), message)

        for item in self.items:
            if self._cancelled:
                break

            result = self.downloader.download_item(item, progress_callback)
            self.download_finished.emit(str(item.get("id", "")), result.to_dict())

        self.batch_finished.emit({"cancelled": self._cancelled})

    def cancel(self):
        self._cancelled = True


class OrganizeThread(QThread):
    """Thread para organizar arquivos sem travar a UI."""
    
    progress_update = Signal(str, str)
    item_organized = Signal(str, dict)
    organize_finished = Signal(dict)

    def __init__(self, organizer: Organizer, items: list[dict], 
                 state_manager: StateManager, base_dir: str):
        super().__init__()
        self.organizer = organizer
        self.items = items
        self.state_manager = state_manager
        self.base_dir = base_dir

    def run(self):
        source_dir = Path(self.base_dir) / "temp"
        stats = self.organizer.organize_directory(source_dir, self.items, self.state_manager,
                                                    lambda fid, msg: self.progress_update.emit(str(fid), json.dumps(msg.to_dict()) if hasattr(msg, 'to_dict') else str(msg)))
        self.organize_finished.emit(stats)


class M3UOrganizerGUI(QMainWindow):
    """Janela principal do aplicativo M3U Organizer."""

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.setWindowTitle("M3U Organizer - Download & Jellyfin")
        self.resize(1200, 800)

        # Inicializa componentes
        self.parser = M3UParser(config.get("regex_serie"))
        self.downloader = Downloader(config)
        self.organizer = Organizer(
            config.get("base_dir", ""),
            config.get("duplicate_policy", "skip")
        )

        # Estado
        self.state_manager = None
        self.current_entries: list[M3UEntry] = []
        self.download_thread: DownloadThread = None
        self.organize_thread: OrganizeThread = None

        # Carrega state.json se base_dir existir
        if config.get("base_dir") and Path(config["base_dir"]).exists():
            self.state_manager = StateManager(config["base_dir"])

        # Configura UI
        self._setup_ui()
        self._apply_theme()
        self._setup_signals()

    def _setup_ui(self):
        """Constrói a interface gráfica completa."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # === Área de Carregamento ===
        self._setup_load_area(main_layout)

        # Splitter principal (árvore + painel lateral)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # Painel esquerdo (árvore + filtro)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        self._setup_filter_area(left_layout)
        self._setup_tree_area(left_layout)
        splitter.addWidget(left_panel)

        # Painel direito (destino + ação + progresso + logs)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self._setup_target_area(right_layout)
        self._setup_action_area(right_layout)
        self._setup_progress_area(right_layout)
        right_panel.setMinimumWidth(400)
        splitter.addWidget(right_panel)

        # Barra de status
        self.status_bar = self.statusBar()
        self.status_label = QLabel("Pronto. Carregue uma lista M3U para começar.")
        self.status_bar.addPermanentWidget(self.status_label)

    def _setup_load_area(self, parent_layout):
        """Área de carregamento da lista M3U."""
        group = QGroupBox("1. Carregar Lista M3U")
        group.setFlat(True)
        layout = QHBoxLayout(group)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Digite a URL da lista M3U (http://exemplo.com/lista.m3u8)")
        self.url_input.returnPressed.connect(self.load_m3u_url)
        layout.addWidget(self.url_input, 1)

        self.load_url_btn = QPushButton("Carregar URL")
        self.load_url_btn.clicked.connect(self.load_m3u_url)
        self.load_url_btn.setMinimumWidth(120)
        layout.addWidget(self.load_url_btn)

        self.load_file_btn = QPushButton("Abrir Arquivo...")
        self.load_file_btn.clicked.connect(self.load_m3u_file)
        layout.addWidget(self.load_file_btn)

        self.loading_indicator = QLabel("⏳")
        self.loading_indicator.setVisible(False)
        self.loading_indicator.setStyleSheet("font-size: 16px;")
        layout.addWidget(self.loading_indicator)

        parent_layout.addWidget(group)

    def _setup_filter_area(self, parent_layout):
        """Área de filtro com botão de pesquisa."""
        group = QGroupBox("2. Filtrar")
        group.setFlat(True)
        layout = QHBoxLayout(group)

        layout.addWidget(QLabel("Filtrar:"))
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Digite para filtrar por série, temporada, título...")
        self.filter_input.returnPressed.connect(self._apply_filter)
        layout.addWidget(self.filter_input, 1)
        
        self.search_btn = QPushButton("Pesquisar")
        self.search_btn.clicked.connect(self._apply_filter)
        layout.addWidget(self.search_btn)

        self.select_all_btn = QPushButton("Selecionar todos")
        self.select_all_btn.clicked.connect(self._select_all)
        layout.addWidget(self.select_all_btn)

        parent_layout.addWidget(group)

    def _setup_tree_area(self, parent_layout):
        """Área da árvore de episódios."""
        group = QGroupBox("3. Episódios")
        group.setFlat(True)
        layout = QVBoxLayout(group)

        # Toolbar da árvore
        tree_toolbar = QHBoxLayout()
        self.expand_all_btn = QPushButton("Expandir tudo")
        self.expand_all_btn.clicked.connect(lambda: self.tree_widget.expandAll())
        tree_toolbar.addWidget(self.expand_all_btn)

        self.collapse_all_btn = QPushButton("Recolher tudo")
        self.collapse_all_btn.clicked.connect(lambda: self.tree_widget.collapseAll())
        tree_toolbar.addWidget(self.collapse_all_btn)

        self.clear_selection_btn = QPushButton("Limpar seleção")
        self.clear_selection_btn.clicked.connect(self._clear_selection)
        tree_toolbar.addWidget(self.clear_selection_btn)

        tree_toolbar.addStretch()

        self.selection_count_label = QLabel("Selecionados: 0")
        tree_toolbar.addWidget(self.selection_count_label)

        layout.addLayout(tree_toolbar)

        # Árvore de episódios
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["Título", "Ep/Temp", "Status", "Tamanho", "URL"])
        self.tree_widget.setHeaderHidden(False)
        self.tree_widget.setSelectionMode(QTreeWidget.NoSelection)
        self.tree_widget.itemChanged.connect(self._on_item_changed)
        header = self.tree_widget.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.resizeSection(1, 120)
        header.resizeSection(2, 100)
        header.resizeSection(3, 100)

        layout.addWidget(self.tree_widget)
        parent_layout.addWidget(group)

    def _setup_target_area(self, parent_layout):
        """Área de pasta de destino."""
        group = QGroupBox("4. Pasta de Destino")
        group.setFlat(True)
        layout = QHBoxLayout(group)

        self.target_dir_input = QLineEdit()
        self.target_dir_input.setText(self.config.get("base_dir", ""))
        self.target_dir_input.setPlaceholderText("Selecione a pasta de destino")
        layout.addWidget(self.target_dir_input, 1)

        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self._browse_target_dir)
        layout.addWidget(self.browse_btn)

        parent_layout.addWidget(group)

    def _setup_action_area(self, parent_layout):
        """Área de botões de ação."""
        group = QGroupBox("5. Ações")
        group.setFlat(True)
        layout = QHBoxLayout(group)

        self.download_btn = QPushButton("Baixar selecionados")
        self.download_btn.clicked.connect(self._start_downloads)
        self.download_btn.setMinimumHeight(30)
        self.download_btn.setStyleSheet("""
            QPushButton { background: #4CAF50; color: white; border: none; padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background: #45a049; }
            QPushButton:disabled { background: #555; }
        """)
        layout.addWidget(self.download_btn, 1)

        self.organize_btn = QPushButton("Organizar agora")
        self.organize_btn.clicked.connect(self._start_organize)
        self.organize_btn.setMinimumHeight(30)
        self.organize_btn.setStyleSheet("""
            QPushButton { background: #2196F3; color: white; border: none; padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background: #0b7dda; }
        """)
        layout.addWidget(self.organize_btn, 1)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.clicked.connect(self._cancel_downloads)
        self.cancel_btn.setMinimumHeight(30)
        self.cancel_btn.setVisible(False)
        layout.addWidget(self.cancel_btn)

        parent_layout.addWidget(group)

    def _setup_progress_area(self, parent_layout):
        """Área de progresso e logs."""
        group = QGroupBox("Progresso e Logs")
        group.setFlat(True)
        group.setMinimumHeight(200)
        layout = QVBoxLayout(group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Pronto")
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setLineWrapMode(QTextEdit.WidgetWidth)
        layout.addWidget(self.log_area, 1)

        parent_layout.addWidget(group, 1)

        # Botão para exportar relatório
        self.export_report_btn = QPushButton("Exportar relatório")
        self.export_report_btn.clicked.connect(self._export_report)
        parent_layout.addWidget(self.export_report_btn)

    def _apply_theme(self):
        """Aplica o tema da interface."""
        theme = self.config.get("theme", "dark").lower()
        
        if theme == "dark":
            app_style = """
                QMainWindow { background: #2d2d30; color: #d4d4d4; }
                QGroupBox { 
                    font-weight: bold; 
                    border: 1px solid #444; 
                    border-radius: 4px; 
                    margin-top: 8px; 
                    padding-top: 4px;
                }
                QGroupBox::title { color: #4FC1FF; padding: 0 4px; }
                QPushButton {
                    background: #3c3c3c; color: #d4d4d4; border: 1px solid #555;
                    border-radius: 4px; padding: 4px 8px;
                }
                QPushButton:hover { background: #4a4A4A; border-color: #666; }
                QLineEdit, QTextEdit, QTreeWidget {
                    background: #1e1e1e; border: 1px solid #555;
                    border-radius: 3px; color: #d4d4d4;
                }
                QTreeWidget::item { padding: 2px 4px; }
                QTreeWidget::item:selected { background: #2a4d69; }
                QTreeWidget::item:alternate { background: #252526; }
                QHeaderView::section {
                    background: #3c3c3c; color: #d4d4d4;
                    padding: 4px; border: 1px solid #555;
                }
            """
        else:
            app_style = """
                QMainWindow { background: #f5f5f5; color: #333; }
                QGroupBox { 
                    font-weight: bold; 
                    border: 1px solid #ccc; 
                    border-radius: 4px; 
                    margin-top: 8px; 
                    padding-top: 4px;
                }
                QGroupBox::title { color: #1976D2; padding: 0 4px; }
                QPushButton {
                    background: #e0e0e0; color: #333; border: 1px solid #aaa;
                    border-radius: 4px; padding: 4px 8px;
                }
                QPushButton:hover { background: #d0d0d0; }
                QLineEdit, QTextEdit, QTreeWidget {
                    background: white; border: 1px solid #aaa;
                    border-radius: 3px; color: #333;
                }
                QHeaderView::section {
                    background: #e0e0e0; color: #333;
                    padding: 4px; border: 1px solid #aaa;
                }
            """

        self.setStyleSheet(app_style)

    def _log(self, message: str, level: str = "INFO"):
        """Adiciona mensagem ao log com cores."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {
            "INFO": "#4FC1FF",
            "OK": "#4CAF50",
            "ERROR": "#F44336",
            "WARN": "#FF9800"
        }
        color = colors.get(level, "#d4d4d4")
        formatted = f"<span style='color: {color};'>[{timestamp}] [{level}]</span> {message}"
        self.log_area.append(formatted)
        # Auto-scroll para o final
        self.log_area.moveCursor(QTextCursor.End)

    def _log_html(self, message: str, level: str = "INFO"):
        """Log direto em HTML (para cores nos resultados)."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {
            "INFO": "#4FC1FF",
            "OK": "#4CAF50",
            "ERROR": "#F44336",
            "WARN": "#FF9800"
        }
        color = colors.get(level, "#d4d4d4")
        formatted = f"<span style='color: {color};'>[{timestamp}] [{level}]</span> {message}"
        self.log_area.append(formatted)

    def load_m3u_url(self):
        """Carrega M3U de uma URL."""
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Erro", "Digite uma URL válida.")
            return

        # Salva na config
        self.config["last_m3u_url"] = url
        self._save_config()

        self.loading_indicator.setVisible(True)
        self._log(f"Carregando lista M3U da URL: {url}", "INFO")

        def load():
            try:
                entries = self.parser.parse_url(url)
                self.current_entries = entries
                self._populate_tree(entries)
                self._log(f"Lista carregada: {len(entries)} itens encontrados", "OK")
                self.status_label.setText(f"Carregado {len(entries)} itens da lista M3U.")
            except Exception as e:
                self._log(f"Erro ao carregar M3U: {e}", "ERROR")
            finally:
                self.loading_indicator.setVisible(False)

        threading.Thread(target=load, daemon=True).start()

    def load_m3u_file(self):
        """Carrega M3U de um arquivo local."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Selecionar arquivo M3U", "", "Listas M3U (*.m3u *.m3u8);;Todos os arquivos (*)"
        )
        if not filepath:
            return

        # Salva na config
        self.config["last_m3u_url"] = filepath
        self._save_config()

        self.loading_indicator.setVisible(True)
        self._log(f"Carregando arquivo M3U: {filepath}", "INFO")

        def load():
            try:
                entries = self.parser.parse_file(filepath)
                self.current_entries = entries
                self._populate_tree(entries)
                self._log(f"Lista carregada: {len(entries)} itens encontrados", "OK")
                self.status_label.setText(f"Carregado {len(entries)} itens da lista M3U.")
            except Exception as e:
                self._log(f"Erro ao carregar M3U: {e}", "ERROR")
            finally:
                self.loading_indicator.setVisible(False)

        threading.Thread(target=load, daemon=True).start()

    def _populate_tree(self, entries: list[M3UEntry]):
        """Popula a árvore de episódios com as entradas."""
        self.tree_widget.clear()

        # Organiza por série/grupo
        series_data = {}
        movies = []

        for entry in entries:
            if entry.is_filme or (not entry.serie or entry.serie == "Filmes" or not entry.temporada):
                movies.append(entry)
            else:
                key = entry.serie
                if key not in series_data:
                    series_data[key] = {}
                
                season_key = entry.temporada
                if season_key not in series_data[key]:
                    series_data[key][season_key] = []
                
                series_data[key][season_key].append(entry)

        # Cria nó raiz virtual
        # Adiciona séries
        for serie_name, seasons in sorted(series_data.items()):
            serie_item = QTreeWidgetItem([serie_name, "", "", "", ""])
            serie_item.setFlags(serie_item.flags() | Qt.ItemIsUserCheckable)
            serie_item.setCheckState(0, Qt.Unchecked)
            serie_item.setData(0, Qt.UserRole, "serie")
            serie_item.setForeground(0, self._get_item_color("serie"))

            total_episodes = 0

            for season_num, episodes in sorted(seasons.items()):
                season_item = QTreeWidgetItem([
                    f"Temporada {season_num}", "", "", "", ""
                ])
                season_item.setFlags(season_item.flags() | Qt.ItemIsUserCheckable)
                season_item.setCheckState(0, Qt.Unchecked)
                season_item.setData(0, Qt.UserRole, "season")
                season_item.setForeground(0, self._get_item_color("season"))

                for ep in episodes:
                    ep_text = ep.titulo or ep.raw_title
                    ep_item = QTreeWidgetItem([
                        ep_text,
                        f"S{ep.temporada:02d}E{ep.episodio:02d}",
                        "⬜",
                        "",
                        ep.url
                    ])
                    ep_item.setFlags(ep_item.flags() | Qt.ItemIsUserCheckable)
                    ep_item.setCheckState(0, Qt.Unchecked)
                    ep_item.setData(0, Qt.UserRole, "episode")
                    ep_item.setData(0, Qt.UserRole + 1, ep.to_dict())
                    season_item.addChild(ep_item)
                    total_episodes += 1

                season_item.setText(1, f"{total_episodes} episódios")
                serie_item.addChild(season_item)

            serie_item.setText(1, f"{total_episodes} episódios")
            self.tree_widget.addTopLevelItem(serie_item)

        # Adiciona filmes
        if movies:
            movie_root = QTreeWidgetItem(["Filmes", "", "", "", ""])
            movie_root.setFlags(movie_root.flags() | Qt.ItemIsUserCheckable)
            movie_root.setCheckState(0, Qt.Unchecked)
            movie_root.setData(0, Qt.UserRole, "movies")
            movie_root.setForeground(0, self._get_item_color("movie_root"))

            for movie in movies:
                movie_item = QTreeWidgetItem([
                    movie.titulo or movie.raw_title,
                    "Filme",
                    "⬜",
                    "",
                    movie.url
                ])
                movie_item.setFlags(movie_item.flags() | Qt.ItemIsUserCheckable)
                movie_item.setCheckState(0, Qt.Unchecked)
                movie_item.setData(0, Qt.UserRole, "movie")
                movie_item.setData(0, Qt.UserRole + 1, movie.to_dict())
                movie_root.addChild(movie_item)

            movie_root.setText(1, f"{len(movies)} filmes")
            self.tree_widget.addTopLevelItem(movie_root)

        # Expande tudo inicialmente
        self.tree_widget.expandAll()

    def _setup_signals(self):
        """Configura conexões de sinais após setup completo."""
        self.tree_widget.itemChanged.connect(self._on_item_changed)

    def _get_item_color(self, item_type: str):
        """Retorna cor para diferentes tipos de itens."""
        colors = {
            "serie": QColor("#4FC1FF"),
            "season": QColor("#FFA726"),
            "movies": QColor("#AB47BC"),
            "movie_root": QColor("#AB47BC"),
            "movie": QColor("#E0E0E0"),
            "episode": QColor("#E0E0E0"),
        }
        return colors.get(item_type, QColor("#D4D4D4"))

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        """Manipula mudanças de checkbox na árvore."""
        if column != 0:
            return

        item_type = item.data(0, Qt.UserRole)
        state = item.checkState(0)

        if item_type == "serie":
            # Atualiza todas as temporadas e episódios
            for i in range(item.childCount()):
                season = item.child(i)
                season.setCheckState(0, state)
                for j in range(season.childCount()):
                    season.child(j).setCheckState(0, state)

        elif item_type == "season":
            # Atualiza todos os episódios da temporada
            for i in range(item.childCount()):
                item.child(i).setCheckState(0, state)
            self._update_parent_partial(item.parent())

        elif item_type == "movies":
            # Atualiza todos os filmes
            for i in range(item.childCount()):
                item.child(i).setCheckState(0, state)

        elif item_type in ("episode", "movie"):
            # Atualiza o estado parcial do pai
            self._update_parent_partial(item.parent())

        self._update_selection_count()

    def _update_parent_partial(self, parent: QTreeWidgetItem):
        """Atualiza o estado parcial de um nó pai."""
        if not parent:
            return

        checked_count = 0
        total_count = 0

        for i in range(parent.childCount()):
            child = parent.child(i)
            total_count += 1
            for j in range(child.childCount()):
                if child.child(j).checkState(0) == Qt.Checked:
                    checked_count += 1
                total_count += 1

        if checked_count == 0:
            parent.setCheckState(0, Qt.Unchecked)
        elif checked_count == total_count:
            parent.setCheckState(0, Qt.Checked)
        else:
            parent.setCheckState(0, Qt.PartiallyChecked)

    def _update_selection_count(self):
        """Atualiza o contador de ítens selecionados."""
        count = 0
        self._count_checked(self.tree_widget.invisibleRootItem(), count_ref := [0])
        count = count_ref[0]
        self.selection_count_label.setText(f"Selecionados: {count}")

    def _count_checked(self, item: QTreeWidgetItem, count_ref: list):
        """Conta recursivamente itens marcados."""
        for i in range(item.childCount()):
            child = item.child(i)
            if child.data(0, Qt.UserRole) in ("episode", "movie"):
                if child.checkState(0) == Qt.Checked:
                    count_ref[0] += 1
            self._count_checked(child, count_ref)

    def _apply_filter(self):
        """Aplica filtro quando o usuário digita e pressiona Enter ou clica em Pesquisar."""
        filter_text = self.filter_input.text().strip().lower()

        # Limpa filtros anteriores
        self._clear_tree_filters()

        if not filter_text:
            return

        def filter_item(item: QTreeWidgetItem) -> bool:
            """Retorna True se o item deve ser visível."""
            text = item.text(0).lower()
            item_type = item.data(0, Qt.UserRole)

            if item_type in ("episode", "movie"):
                subtitle = item.text(1).lower()
                return filter_text in text or filter_text in subtitle

            elif item_type == "movies":
                for i in range(item.childCount()):
                    movie = item.child(i)
                    if filter_item(movie):
                        return True
                return False

            else:
                # Séries e temporadas
                for i in range(item.childCount()):
                    child = item.child(i)
                    if filter_item(child):
                        return True
                return False

        for i in range(self.tree_widget.topLevelItemCount()):
            item = self.tree_widget.topLevelItem(i)
            item.setHidden(not filter_item(item))

        self.tree_widget.expandAll()

    def _clear_tree_filters(self):
        """Limpa todos os filtros aplicados a árvore."""
        for i in range(self.tree_widget.topLevelItemCount()):
            item = self.tree_widget.topLevelItem(i)
            item.setHidden(False)
            for j in range(item.childCount()):
                child = item.child(j)
                child.setHidden(False)
                for k in range(child.childCount()):
                    grandchild = child.child(k)
                    grandchild.setHidden(False)

    def _filter_tree(self):
        """Filtra a árvore em tempo real."""
        filter_text = self.filter_input.text().lower()

        def filter_item(item: QTreeWidgetItem) -> bool:
            """Retorna True se o item deve ser visível."""
            text = item.text(0).lower()
            item_type = item.data(0, Qt.UserRole)

            if item_type in ("episode", "movie"):
                # Mostra episódios/filmes que correspondem
                return filter_text in text or filter_text in item.text(2).lower()
            else:
                # Para nós pai, mostra se algum filho corresponde
                matches = False
                for i in range(item.childCount()):
                    child = item.child(i)
                    if filter_item(child):
                        matches = True
                return matches or filter_text in text

        # Aplica o filtro
        for i in range(self.tree_widget.topLevelItemCount()):
            item = self.tree_widget.topLevelItem(i)
            if filter_text:
                item.setHidden(not filter_item(item))
            else:
                item.setHidden(False)

        if filter_text:
            self.tree_widget.expandAll()

    def _select_all(self):
        """Seleciona todos os episódios/filmes."""
        self.tree_widget.expandAll()
        # Desconecta sinal durante operação em lote
        self.tree_widget.itemChanged.disconnect(self._on_item_changed)
        root = self.tree_widget.invisibleRootItem()
        self._set_check_state_recursive(root, Qt.Checked)
        self.tree_widget.itemChanged.connect(self._on_item_changed)
        self._update_selection_count()

    def _clear_selection(self):
        """Limpa todas as seleções."""
        self.tree_widget.itemChanged.disconnect(self._on_item_changed)
        root = self.tree_widget.invisibleRootItem()
        self._set_check_state_recursive(root, Qt.Unchecked)
        self.tree_widget.itemChanged.connect(self._on_item_changed)
        self._update_selection_count()

    def _set_check_state_recursive(self, item: QTreeWidgetItem, state):
        """Define estado de checkbox recursivamente para todos os itens de uma árvore."""
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)
            self._set_check_state_recursive(child, state)

    def _update_parent_partial(self, parent: QTreeWidgetItem):
        """Atualiza o estado parcial de um nó pai."""
        if not parent:
            return

        checked_count = 0
        total_count = 0

        for i in range(parent.childCount()):
            child = parent.child(i)
            for j in range(child.childCount()):
                grandchild = child.child(j)
                if grandchild.checkState(0) == Qt.Checked:
                    checked_count += 1
                total_count += 1

        if checked_count == 0:
            parent.setCheckState(0, Qt.Unchecked)
        elif checked_count == total_count:
            parent.setCheckState(0, Qt.Checked)
        else:
            parent.setCheckState(0, Qt.PartiallyChecked)

    def _browse_target_dir(self):
        """Abre diálogo para selecionar pasta de destino."""
        dir_path = QFileDialog.getExistingDirectory(
            self, "Selecionar pasta de destino", self.config.get("base_dir", "")
        )
        if dir_path:
            self.target_dir_input.setText(dir_path)
            self.config["base_dir"] = dir_path
            self._save_config()

            # Atualiza organizer e state_manager
            self.organizer = Organizer(dir_path, self.config.get("duplicate_policy", "skip"))
            if not self.state_manager or Path(dir_path) != Path(self.config.get("base_dir", "")):
                self.state_manager = StateManager(dir_path)

            self._log(f"Pasta de destino definida: {dir_path}", "INFO")

    def _get_selected_items(self) -> list[dict]:
        """Retorna lista de metadados dos itens selecionados."""
        selected = []
        root = self.tree_widget.invisibleRootItem()

        for i in range(root.childCount()):
            serie_item = root.child(i)
            serie_item_type = serie_item.data(0, Qt.UserRole)

            if serie_item_type == "movies":
                for j in range(serie_item.childCount()):
                    movie_item = serie_item.child(j)
                    if movie_item.checkState(0) == Qt.Checked:
                        data = movie_item.data(0, Qt.UserRole + 1)
                        if data:
                            selected.append(data)
            else:
                for j in range(serie_item.childCount()):
                    season_item = serie_item.child(j)
                    for k in range(season_item.childCount()):
                        ep_item = season_item.child(k)
                        if ep_item.checkState(0) == Qt.Checked:
                            data = ep_item.data(0, Qt.UserRole + 1)
                            if data:
                                selected.append(data)

        return selected

    def _start_downloads(self):
        """Inicia downloads dos itens selecionados."""
        selected = self._get_selected_items()

        if not selected:
            QMessageBox.warning(self, "Aviso", "Nenhum item selecionado para download.")
            return

        target_dir = self.target_dir_input.text().strip()
        if not target_dir:
            QMessageBox.warning(self, "Aviso", "Defina uma pasta de destino.")
            return

        self.config["base_dir"] = target_dir
        self._save_config()

        # Verifica espaço em disco
        ok, msg = self.downloader.check_disk_space(500)
        if not ok:
            QMessageBox.warning(self, "Aviso", f"Pouco espaço em disco:\n{msg}")
            return

        # Atualiza state_manager
        if not self.state_manager:
            self.state_manager = StateManager(target_dir)

        # Filtra itens já baixados
        self._log(f"Iniciando download de {len(selected)} itens...", "INFO")
        self.download_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Download")

        # Cria thread de download
        self.download_thread = DownloadThread(self.downloader, selected)
        self.download_thread.progress_update.connect(self._on_download_progress)
        self.download_thread.download_finished.connect(self._on_download_item_finished)
        self.download_thread.batch_finished.connect(self._on_batch_finished)
        self.download_thread.start()

    def _cancel_downloads(self):
        """Cancela downloads em andamento."""
        if self.download_thread:
            self.download_thread.cancel()
            self._log("Download cancelado pelo usuário.", "WARN")
            self.download_btn.setEnabled(True)
            self.cancel_btn.setVisible(False)
            self.progress_bar.setFormat("Cancelado")

    def _on_download_progress(self, item_id: str, message: str):
        """Atualiza progresso de download individual."""
        self._log(f"{item_id}: {message}", "INFO")

        # Atualiza status na árvore
        self._update_tree_status(item_id, "⏬")

    def _on_download_item_finished(self, item_id: str, result: dict):
        """Callback quando um item termina de download."""
        if result.get("success"):
            self._log_html(
                f"✅ <strong>{result.get('output_file', item_id)}</strong> - Download concluído!",
                "OK"
            )
            self._update_tree_status(item_id, "✔")
        else:
            self._log_html(
                f"❌ <strong>{item_id}</strong> - Erro: {result.get('error', 'Desconhecido')}",
                "ERROR"
            )
            self._update_tree_status(item_id, "✗")

        # Atualiza state.json
        if self.state_manager and result.get("success"):
            item = next((i for i in self._get_selected_items() if str(i.get("id", "")) == item_id), None)
            if item:
                self.state_manager.add_item(item_id, {
                    "id": item_id,
                    "url": item.get("url", ""),
                    "titulo": item.get("titulo", ""),
                    "serie": item.get("serie", ""),
                    "temporada": item.get("temporada"),
                    "episodio": item.get("episodio"),
                    "is_filme": item.get("is_filme", False),
                    "caminho_atual": result.get("output_file", ""),
                    "tamanho": 0,
                    "data_download": datetime.now().isoformat(),
                    "hash": ""
                })

    def _on_batch_finished(self, stats: dict):
        """Callback quando todos os downloads terminam."""
        self.download_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("Concluído")

        self._log(f"\n=== Resultado do Download ===\n", "INFO")
        self._log(f"Itens baixados: {stats.get('successful', 0)}", "OK")
        if stats.get('failed', 0) > 0:
            self._log(f"Itens com falha: {stats['failed']}", "ERROR")
        if stats.get('cancelled', False):
            self._log("Download cancelado parcialmente.", "WARN")

        # Auto-organiza se configurado
        if self.config.get("auto_organize", True) and stats.get('successful', 0) > 0:
            self._log("Auto-organização ativada. Iniciando organização...", "INFO")
            self._start_organize_internal()

        self.status_label.setText(
            f"Download concluído: {stats.get('successful', 0)} sucesso(s), "
            f"{stats.get('failed', 0)} falha(s)"
        )

    def _update_tree_status(self, item_id: str, status: str):
        """Atualiza o status de um item na árvore."""
        root = self.tree_widget.invisibleRootItem()

        for i in range(root.childCount()):
            serie_item = root.child(i)
            for j in range(serie_item.childCount()):
                season_or_movie = serie_item.child(j)
                if season_or_movie.data(0, Qt.UserRole) == "movies":
                    target = season_or_movie
                else:
                    target = season_or_movie

                self._find_and_update_item(target, item_id, status)

    def _find_and_update_item(self, parent: QTreeWidgetItem, item_id: str, status: str):
        """Busca e atualiza o status de um item na árvore."""
        for i in range(parent.childCount()):
            child = parent.child(i)
            item_type = child.data(0, Qt.UserRole)

            if item_type in ("episode", "movie"):
                data = child.data(0, Qt.UserRole + 1)
                if data and str(data.get("id", "")) == item_id:
                    self.tree_widget.topLevelItem(0)  # Force update
                    # Apenas atualiza status visual
                    child.setText(2, status)
                    child.setForeground(2, QColor("#4CAF50") if status == "✔" else 
                                         QColor("#F44336") if status == "✗" else 
                                         QColor("#FF9800"))
            elif child.childCount() > 0:
                self._find_and_update_item(child, item_id, status)

    def _start_organize(self):
        """Inicia organização manual."""
        target_dir = self.target_dir_input.text().strip()
        if not target_dir:
            QMessageBox.warning(self, "Aviso", "Defina uma pasta de destino.")
            return

        self._log("Iniciando organização de arquivos...","INFO")
        self.organize_btn.setEnabled(False)
        self.progress_bar.setFormat("Organizando")

        self.organize_thread = OrganizeThread(
            self.organizer, self.current_entries, self.state_manager, target_dir
        )
        self.organize_thread.progress_update.connect(self._on_organize_progress)
        self.organize_thread.organize_finished.connect(self._on_organize_finished)
        self.organize_thread.start()

    def _start_organize_internal(self):
        """Organização automática pós-download."""
        target_dir = self.target_dir_input.text().strip()
        if not target_dir:
            return

        self.organize_btn.setEnabled(False)
        self.progress_bar.setFormat("Organizando")

        self.organize_thread = OrganizeThread(
            self.organizer, self.current_entries, self.state_manager, target_dir
        )
        self.organize_thread.progress_update.connect(self._on_organize_progress)
        self.organize_thread.organize_finished.connect(self._on_organize_finished)
        self.organize_thread.start()

    def _on_organize_progress(self, item_id: str, message: str):
        """Atualiza progresso de organização."""
        try:
            msg_data = json.loads(message)
            if msg_data.get("action") == "moved":
                self._log_html(f"📁 <strong>{msg_data.get('new_path', '').split('/')[-1]}</strong> organizado", "OK")
            elif msg_data.get("action") == "duplicate_removed":
                self._log(f'Duplicata removida: {msg_data.get("new_path", "").split("/")[-1]}', "WARN")
            elif msg_data.get("action") == "skipped":
                self._log(f'Item ignorado: {msg_data.get("new_path", "").split("/")[-1]}', "WARN")
        except (json.JSONDecodeError, AttributeError):
            self._log(message, "INFO")

    def _on_organize_finished(self, stats: dict):
        """Callback quando organização termina."""
        self.organize_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("Organizado")

        self._log(f"\n=== Resultado da Organização ===\n", "INFO")
        self._log(f"Arquivos movidos: {stats.get('moved', 0)}", "OK")
        self._log(f"Duplicatas removidas: {stats.get('duplicates_removed', 0)}", "WARN")
        if stats.get("skipped", 0) > 0:
            self._log(f"Itens ignorados: {stats['skipped']}", "WARN")
        if stats.get("errors", 0) > 0:
            self._log(f"Erros: {stats['errors']}", "ERROR")

        self.status_label.setText(
            f"Organização concluída: {stats.get('moved', 0)} movido(s), "
            f"{stats.get('duplicates_removed', 0)} duplicata(s) removida(s)"
        )

    def _export_report(self):
        """Exporta relatório em CSV."""
        report_path, _ = QFileDialog.getSaveFileName(
            self, "Salvar relatório", "", "CSV Files (*.csv);;Text Files (*.txt)"
        )
        if not report_path:
            return

        # Coleta dados da árvore
        rows = []
        root = self.tree_widget.invisibleRootItem()

        for i in range(root.childCount()):
            serie_item = root.child(i)
            serie_name = serie_item.text(0)
            item_type = serie_item.data(0, Qt.UserRole)

            if item_type == "movies":
                for j in range(serie_item.childCount()):
                    movie = serie_item.child(j)
                    data = movie.data(0, Qt.UserRole + 1) or {}
                    rows.append({
                        "ID": data.get("id", ""),
                        "Título": data.get("titulo", ""),
                        "Série": "Filmes",
                        "Temporada": "",
                        "Episódio": "",
                        "Status": movie.text(2) or "⬜",
                        "Caminho": data.get("url", "")
                    })
            else:
                for j in range(serie_item.childCount()):
                    season = serie_item.child(j)
                    for k in range(season.childCount()):
                        ep = season.child(k)
                        data = ep.data(0, Qt.UserRole + 1) or {}
                        rows.append({
                            "ID": data.get("id", ""),
                            "Título": data.get("titulo", ""),
                            "Série": data.get("serie", serie_name),
                            "Temporada": data.get("temporada", ""),
                            "Episódio": data.get("episodio", ""),
                            "Status": ep.text(2) or "⬜",
                            "Caminho": data.get("url", "")
                        })

        # Escreve arquivo
        import csv
        with open(report_path, "w", newline="", encoding="utf-8") as f:
            if report_path.endswith(".csv"):
                writer = csv.DictWriter(f, fieldnames=["ID", "Título", "Série", "Temporada", "Episódio", "Status", "Caminho"])
                writer.writeheader()
                writer.writerows(rows)
            else:
                for row in rows:
                    f.write(f"{row['ID']}\t{row['Título']}\t{row['Série']}\t{row['Temporada']}\t{row['Episódio']}\t{row['Status']}\t{row['Caminho']}\n")

        self._log(f"Relatório exportado: {report_path}", "OK")
        QMessageBox.information(self, "Sucesso", f"Relatório exportado para:\n{report_path}")

    def _save_config(self):
        """Salva configurações no arquivo config.json."""
        config_path = Path(__file__).parent.parent / "config.json"
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[WARN] Não foi possível salvar config.json: {e}")

    def closeEvent(self, event):
        """Salva configurações ao fechar."""
        self._save_config()
        super().closeEvent(event)
