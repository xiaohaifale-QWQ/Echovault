"""Built-in help for local AI, interfaces, translation, and online lyrics."""

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

HELP_SECTIONS = (
    (
        "快速开始",
        """
        <h2>琳琅乐府使用说明</h2>
        <p>先在右侧“素材库”添加音乐或视频文件夹，再从素材列表选择歌曲。
        单曲操作放在“详情”和“在线匹配”；批量工作统一放在右侧“批量处理”。</p>
        <ul>
          <li><b>识别：</b>Groq、讯飞或本地 Whisper 生成同名 LRC。</li>
          <li><b>翻译：</b>使用当前 AI，或下载 Argos 语言包后离线翻译。</li>
          <li><b>在线匹配：</b>从 LRCLIB 搜索公开同步歌词，写入前会备份原 LRC。</li>
          <li><b>安全：</b>密钥只保存在当前 Windows 用户配置中，命令输出会脱敏。</li>
        </ul>
        """,
    ),
    (
        "本地部署 AI",
        """
        <h2>连接本地 AI</h2>
        <ol>
          <li>先启动 Ollama、LM Studio 或其他 OpenAI 兼容服务。</li>
          <li>打开“设置 → 本地部署 AI”，选择预设或填写 <code>/v1</code> 接口地址。</li>
          <li>填写服务端实际加载的模型 ID；本地服务不鉴权时 Key 可以留空。</li>
          <li>保存后在“AI 模式”中选择本地接口。歌词翻译和校准也会复用它。</li>
        </ol>
        <p>常用地址：Ollama <code>http://127.0.0.1:11434/v1</code>；
        LM Studio <code>http://127.0.0.1:1234/v1</code>。</p>
        <p><b>隐私：</b>回环地址只在本机传输；使用局域网或公网地址时，内容会发送到对应服务器。</p>
        <p>详细文档：<code>docs/AI接口与本地模型接入指南.md</code></p>
        """,
    ),
    (
        "AI 接口与 MCP",
        """
        <h2>AI 接口与 MCP</h2>
        <p>AI 服务使用 OpenAI 兼容的 <code>POST /chat/completions</code>：Bearer Token 可选，
        请求包含 <code>model</code>、<code>messages</code>、<code>temperature</code>。</p>
        <p>MCP 可通过标准输入输出或 Streamable HTTP 暴露现有 CLI 白名单。
        默认只读；写操作必须同时以 <code>--allow-writes</code> 启动，并在每次调用中传入
        <code>confirmed=true</code>。</p>
        <p>服务示例：<code>python mcp_server.py --transport stdio</code></p>
        <p>详细文档：<code>docs/MCP接口使用指南.md</code>、
        <code>docs/AI接口与本地模型接入指南.md</code></p>
        """,
    ),
    (
        "歌词翻译",
        """
        <h2>在线与离线翻译</h2>
        <p>“详情”用于翻译当前歌词；“批量处理”用于翻译当前素材列表中已有 LRC 的歌曲。</p>
        <ul>
          <li><b>AI 翻译：</b>使用当前在线或本地 AI 接口，只发送歌词文字。</li>
          <li><b>本地库：</b>在“设置 → 歌词输出”下载 Argos 语言包，完全离线处理。</li>
          <li>译文保存为 <code>歌曲名.语言.lrc</code>，原 LRC 和时间戳不变。</li>
        </ul>
        <p>详细文档：<code>docs/歌词翻译使用指南.md</code></p>
        """,
    ),
    (
        "在线歌词",
        """
        <h2>在线匹配与校准</h2>
        <p>在线匹配使用 LRCLIB 公开库，不需要 API Key。请选择本地歌曲和候选结果，
        对照两边歌词后再决定采用本地、在线或合并结果。</p>
        <p>写入歌词只修改 LRC，不修改媒体音轨；已有文件会先生成递增备份。
        AI 校准会以在线文本作为参考，同时保留本地时间戳。</p>
        <p>详细文档：<code>docs/在线歌词匹配与AI校准指南.md</code></p>
        """,
    ),
)


class HelpDialog(QDialog):
    """Offline help that remains available in the packaged application."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("琳琅乐府帮助")
        self.resize(760, 560)

        layout = QVBoxLayout(self)
        intro = QLabel("以下说明随软件提供，无需联网；仓库 docs 目录保留完整接口文档。")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.tabs = QTabWidget()
        self.pages: dict[str, QTextBrowser] = {}
        for title, html in HELP_SECTIONS:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setHtml(html)
            page_layout.addWidget(browser)
            self.pages[title] = browser
            self.tabs.addTab(page, title)
        layout.addWidget(self.tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

