# M3U Downloader e Organizador para Jellyfin

Um aplicativo de interface gráfica (GUI) em Python que automatiza o download e organização de arquivos a partir de uma lista M3U, formatando-os para compatibilidade com **Jellyfin**.

## 🎯 Objetivo

Substituir o processo manual atual:
1. Filtro no Notepad++ → App faz a leitura e exibição com filtro interativo
2. Criação de lista de URLs → App gera lista interna dos itens selecionados
3. Download com yt-dlp → App chama yt-dlp para cada URL selecionada
4. Renomeação e organização manual → App renomeia e move automaticamente para a estrutura Jellyfin

## ✨ Funcionalidades

- 📋 **Carregamento M3U** - Carrega listas de URLs (.m3u/.m3u8) via arquivo local ou URL
- 🌳 **Visualização Hierárquica** - Árvore de episódios agrupada por série e temporada
- 🔍 **Filtro em Tempo Real** - Filtra episódios por nome, série, temporada, etc.
- ✅ **Seleção Inteligente** - Checkboxes tristate (série → temporada → episódio)
- ⬇️ **Download com yt-dlp** - Motor robusto de download com retry e backoff exponencial
- 📁 **Organização Jellyfin** - Renomeia e move arquivos para estrutura padrão do Jellyfin
- 📊 **Progresso em Tempo Real** - Barras de progresso e logs coloridos
- 💾 **Estado Persistente** - `state.json` evita re-downloads duplicados
- 🎬 **Auto-Detecção** - Reconstroi o mapeamento a partir de arquivos existentes
- 📤 **Exportação** - Relatórios em CSV ou TXT

## ⚙️ Estrutura de Pastas (Jellyfin)

```
BASE_DIR/
├── Série Exemplo/
│   ├── Season 01/
│   │   ├── Série Exemplo - S01E01 - Título do Episódio.mp4
│   │   └── Série Exemplo - S01E02 - Outro Episódio.mkv
│   └── Season 02/
│       └── ...
└── Filmes/
    ├── Filme 1.mp4
    └── Filme 2.mkv
```

## 🚀 Instalação

### Pré-requisitos

- Python 3.10+
- `yt-dlp` (instalado via `pip install yt-dlp` ou disponível no PATH)

### Passos

```bash
# Clone ou baixe este repositório
git clone https://github.com/seu-usuario/m3u-organizer.git
cd m3u-organizer

# Instale as dependências
pip install -r requirements.txt

# Execute o aplicativo
python main.py
```

### Dependências (requirements.txt)

```
yt-dlp>=2024.0
PySide6>=6.6.0
PyInstaller>=5.13.0
```

## 📦 Executável (PyInstaller)

Para gerar um executável standalone:

```bash
pyinstaller --onefile --windowed main.py
```

O executável será gerado em `dist/main.exe`.

## 🛠️ Configuração (config.json)

```json
{
    "base_dir": "",              // Pasta de destino
    "last_m3u_url": "",          // Última URL carregada
    "regex_serie": "^(.*?)\\s+S(\\d+)E(\\d+)",  // Regex para séries
    "retries": 3,                // Tentativas de download
    "duplicate_policy": "skip",  // Política de duplicatas: skip/overwrite/ask
    "auto_organize": true,       // Organizar automaticamente após download
    "theme": "dark",             // Tema: dark/light
    "max_concurrent_downloads": 3
}
```

## 📋 Uso

### 1. Carregar Lista M3U
- Insira uma **URL** da lista M3U e clique "Carregar URL"
- Ou clique "Abrir Arquivo..." para selecionar um `.m3u` local

### 2. Filtrar e Selecionar
- Digite no campo "Filtrar" para filtrar em tempo real
- Use os checkboxes para selecionar episódios individuais ou por série/temporada

### 3. Baixar
- Defina a **pasta de destino** (Browse)
- Clique "Baixar selecionados"
- Monitore o progresso na barra e nos logs

### 4. Organizar
- Clique "Organizar agora" após o download
- Ou deixe a **auto-organização** fazer isso automaticamente

### 5. Relatório
- Visualize o resumo de downloads e organização
- Exporte para CSV ou TXT

## 📁 Arquivos do Projeto

```
m3u-organizer/
├── main.py                          # Ponto de entrada
├── config.json                      # Configurações do usuário
├── requirements.txt                 # Dependências Python
├── m3u_organizer/
│   ├── __init__.py                  # Módulo de inicialização
│   ├── m3u_parser.py                # Parser M3U com extração de metadados
│   ├── gui.py                       # Interface gráfica PySide6
│   ├── downloader.py                # Sistema de download com yt-dlp
│   ├── organizer.py                 # Organizador Jellyfin
│   └── state_manager.py             # Gerenciamento de estado persistente
└── logs/                            # Arquivos de log
```

## 🔄 Fluxo de Trabalho

1. **Carrega M3U** → parser → árvore de episódios
2. **Filtra** em tempo real
3. **Seleciona** (tristate checkboxes)
4. **Baixa** com yt-dlp (threads, retry, progresso)
5. **Organiza** para estrutura Jellyfin
6. **Reporta** resultados

## 🛡️ Tratamento de Erros

- **URL inacessível** → Registrar erro e continuar
- **Token expirado** → yt-dlp lida automaticamente. Suporte a `--cookies`
- **Arquivo corrompido** → Verificação de tamanho > 0
- **Falta de espaço** → Alerta antes de iniciar
- **Cancelamento** → Botão "Cancelar" interrompe downloads

## 📝 Licença

Este projeto é um software livre. Sinta-se à vontade para modificar e distribuir.

## 📧 Contato

Para dúvidas, abra uma *issue* no repositório.

---

### Screenshots

*(Adicione screenshots da interface aqui)*

---

## 🌟 Agradecimentos

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Motor de download
- [PySide6](https://doc.qt.io/pyside6/) - Framework GUI
- [Jellyfin](https://jellyfin.org/) - Sistema de mídia
