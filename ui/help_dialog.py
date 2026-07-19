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

from ui.theme import polish_widget_tree

HELP_SECTIONS = (
    (
        "快速开始",
        """
        <h2>琳琅乐府使用说明</h2>
        <p>先在左侧“素材”添加音乐或视频文件夹，再从素材列表选择文件。
        左侧只保留四个任务入口；批量工作通过顶部“批量任务”进入。</p>
        <ul>
          <li><b>识别：</b>Groq、讯飞或本地 Whisper 生成同名 LRC。</li>
          <li><b>模型库：</b>在“在线识别模型”选择 Groq/讯飞，或下载并使用本地 Whisper。</li>
          <li><b>翻译：</b>使用当前 AI，或下载 Argos 语言包后离线翻译。</li>
          <li><b>在线匹配：</b>搜索 LRCLIB 歌词和 Apple 快速封面，未命中时回退
          MusicBrainz/CAA，也可导入本地封面。</li>
          <li><b>音频编辑：</b>波形选区、裁剪、拼接、混音、降噪、变速变调和标签。</li>
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
          UVR DeNoise Lite 或 UVR DeEcho-DeReverb，再勾选右侧增强选项；
          每个处理阶段都会实时显示。</li>
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
        <p>“歌词与标签”按三个页签组织：在线歌词与封面、本地识别编辑、歌词核对。
        在线页位于最前，点击“一键搜索歌词与封面”会并行查询 LRCLIB 和快速封面源；
        在线歌词内部为候选在左、正文在右的可拖动分栏，播放器横跨两栏底部；
        页面右侧用“封面候选 / 音频标签”页签切换，
        不会再把标签保存按钮挤出可视区域。</p>
        <p>“歌词核对”提供本地与在线双栏播放器。双击任一侧会暂停并进入编辑，
        后续采用、合并或 AI 校准使用修改后的内容。</p>
        <p>写入歌词只修改 LRC，不修改媒体音轨；已有文件会先生成递增备份。
        AI 校准会用左侧当前时间轴和右侧当前文字直接更新左侧，同时保留左侧时间戳。</p>
        <p>精确歌词会先显示，完整候选随后补齐；封面优先使用 Apple 公开目录，
        未命中时回退 MusicBrainz/CAA。相同搜索会缓存 10 分钟，封面缩略图并发加载。
        也可选择本地 JPEG/PNG。音频标签页可直接修改标题、歌手、专辑、年份和
        轨道号；封面和文字标签写入都不会重新编码音轨。素材列表会显示小封面。</p>
        <p>详细文档：<code>docs/在线歌词匹配与AI校准指南.md</code></p>
        """,
    ),
    (
        "音频编辑",
        """
        <h2>音频编辑工作区</h2>
        <p>选择音乐或视频素材后打开左侧“音频编辑”。左侧按用途排列工具，
        右侧整个区域会切换为当前工具自己的工作台，不共用单一参数模板。</p>
        <ul>
          <li><b>裁剪：</b>精确选区、提取/删除片段、音量、速度、变调、延迟和淡化。</li>
          <li><b>音质：</b>处理前后双波形降噪、目标响度卡、八段均衡器和变速预设。</li>
          <li><b>多轨：</b>轨道静音、独奏、分轨音量、主输出和左右声道合成。</li>
          <li><b>输出：</b>分段、拼接、混音和提取均有独立操作界面；音频标签统一到“歌词与标签”维护。</li>
        </ul>
        <p>默认输出到素材旁的
        <code>Echovault编辑输出</code>，不会覆盖原文件；手机任务结果会自动进入待回传。</p>
        <p>波形在后台生成并缓存，隐藏工具按需加载；播放和拖动只刷新当前工作台的
        播放头或选区，不会让全部工具一起重绘。</p>
        <p>所有横向和纵向滑动条都可直接点击灰色轨道跳到对应值，也可继续拖动滑块。</p>
        <p>全软件同时只保留一个播放焦点：在新界面点击播放会自动暂停上一界面；
        人声分离的人声与伴奏作为同一组继续同步试听。</p>
        <p>详细文档：<code>docs/音频编辑使用指南.md</code></p>
        """,
    ),
    (
        "手机传输",
        """
        <h2>手机传入、处理并回传</h2>
        <ol>
          <li>打开“导出与传输 → 接收”，选择接收目录并开启接收。</li>
          <li>手机 LocalSend 选择 Echovault；每次发送会建立独立传输任务。</li>
          <li>在现有识别、翻译、人声分离或视频页面处理素材。</li>
          <li>打开“导出与传输 → 发送”刷新结果；新生成和已修改文件默认勾选。</li>
          <li>双击查看文件，选择发现到的手机设备后发送回去。</li>
        </ol>
        <p>处理结果会进入独立“待回传”目录；同盘优先使用硬链接。发送成功后，
        回传副本移入已发送缓存并从传输列表隐藏。“设置 → 缓存”可查看数量、
        大小并清理，正式处理结果和待回传文件不会被删除。</p>
        <p>标准 LocalSend 不能指定手机任意文件夹；最终保存位置由手机 LocalSend
        和手机系统权限决定。“发送、接收、批量任务、高级文件夹同步”是四个独立页面，
        A/B 文件夹同步不再折叠在手机流程底部。</p>
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
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        polish_widget_tree(self)
