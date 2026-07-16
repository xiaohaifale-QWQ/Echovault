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
          <li><b>在线匹配：</b>搜索 LRCLIB 歌词和 MusicBrainz/CAA 封面，也可导入本地封面。</li>
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
        <p>“详情”用于翻译当前歌词；“批量处理”会逐份自动检测源语言，再翻译到指定目标语言。</p>
        <ul>
          <li><b>AI 翻译：</b>使用当前在线或本地 AI 接口，只发送歌词文字。</li>
          <li><b>本地库：</b>在“设置 → 歌词输出”下载 Argos 语言包，完全离线处理。</li>
          <li>译文保存为 <code>歌曲名.语言.lrc</code>，原 LRC 和时间戳不变。</li>
        </ul>
        <p>详细文档：<code>docs/歌词翻译使用指南.md</code></p>
        """,
    ),
    (
        "人声分离",
        """
        <h2>人声与伴奏分离</h2>
        <p>切到“人声分离”后，主区改为素材、实时本地歌词、处理面板三栏。
        右侧上半区显示已选歌曲、输出内容和目录；模型与 CPU/GPU 统一在顶栏模型库管理。
        下半区显示伴奏与人声双波形，可同步播放、跳转并分别调节音量。</p>
        <ol>
          <li>第一次使用先打开顶栏“模型库”，从“音频分离模型”白色卡片下载
          HTDemucs（推荐）或其他模型，并查看 GPU 状态。</li>
          <li>需要清理底噪或房间混响时，在同一张“音频分离与增强模型”卡片下载
          UVR DeNoise Lite 或 UVR DeEcho-DeReverb，再勾选右侧增强选项；每个处理阶段都会实时显示。</li>
          <li>点击“开始处理”，结果保存为 <code>_vocals.wav</code> 和
          <code>_accompaniment.wav</code>，原素材不变。</li>
          <li>红色波形线可直接拖动；支持暂停、1x–10x 倍速和本地倒放试听。</li>
          <li>播放器始终跟随 Windows 当前系统默认输出；同时输出两轨时可调音并导出新的无损 WAV。</li>
        </ol>
        <p>“设置 → 语音识别”启用 Demucs 后，本地 Whisper 会先识别临时人声音轨，
        结束后自动清理；该流程完全在本机执行。</p>
        <p>详细文档：<code>docs/人声与伴奏分离使用指南.md</code></p>
        """,
    ),
    (
        "在线歌词",
        """
        <h2>在线歌词、封面匹配与校准</h2>
        <p>在线匹配使用 LRCLIB 公开库，不需要 API Key。切到该页时，左侧素材列表
        自动换成完整歌词核对区：左半栏是本地歌词，右半栏是在线歌词，播放器在下方。
        右侧页面只放音乐/视频来源筛选、搜索结果，以及识别、直接应用、合并和校准按钮。
        在线候选会先繁转简；“开始识别”位于“搜索 LRCLIB”左边。</p>
        <p>左侧底部播放器播放当前本地素材；播放位置会分别高亮并滚动两侧时间轴歌词。
        双击任一侧会暂停并进入编辑，后续采用/合并使用修改后的内容。</p>
        <p>写入歌词只修改 LRC，不修改媒体音轨；已有文件会先生成递增备份。
        AI 校准会用左侧当前时间轴和右侧当前文字直接更新左侧，同时保留左侧时间戳。</p>
        <p>“搜索歌词”和“搜索封面”共用同一个结果区：前者显示歌词表，后者
        显示封面缩略图。也可选择本地 JPEG/PNG；点击封面后直接确认并写入
        常见音频格式的内嵌标签，不需要额外的写入按钮，也不会重新编码音轨。
        素材列表会在歌曲名称旁显示小封面。</p>
        <p>详细文档：<code>docs/在线歌词匹配与AI校准指南.md</code></p>
        """,
    ),
    (
        "手机传输",
        """
        <h2>手机传入、处理并回传</h2>
        <ol>
          <li>打开右侧“手机传输”，选择接收目录并开启接收。</li>
          <li>手机 LocalSend 选择 Echovault；每次发送会建立独立传输任务。</li>
          <li>在现有识别、翻译、人声分离或视频页面处理素材。</li>
          <li>返回传输任务刷新结果；新生成和已修改文件默认勾选。</li>
          <li>双击查看文件，选择发现到的手机设备后发送回去。</li>
        </ol>
        <p>处理结果会进入独立“待回传”目录；同盘优先使用硬链接。发送成功后，
        回传副本移入已发送缓存并从传输列表隐藏。“设置 → 缓存”可查看数量、
        大小并清理，正式处理结果和待回传文件不会被删除。</p>
        <p>标准 LocalSend 不能指定手机任意文件夹；最终保存位置由手机 LocalSend
        和手机系统权限决定。传统 A/B 文件夹同步位于页面底部的“高级文件夹同步”。</p>
        <p>详细文档：<code>docs/手机双向传输使用指南.md</code></p>
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
