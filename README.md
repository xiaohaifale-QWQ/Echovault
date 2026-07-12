# Echovault / 鐞崇悈涔愬簻

> AI 椹卞姩鐨勬瓕璇嶈瘑鍒?+ 鏈湴浼樺厛鐨勬枃浠跺悓姝?| 寮€婧愭闈㈠簲鐢?
[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green)](https://riverbankcomputing.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Status](https://img.shields.io/badge/Status-V0.2-orange)]()

---

## 姒傝堪

**鐞崇悈涔愬簻**鏄竴涓闈㈢闊充箰绠＄悊宸ュ叿銆傚畠瑙ｅ喅涓変釜鐥涚偣锛?
1. **浣犵殑鏈湴闊充箰搴撴湁鍑犲崈棣栨瓕锛屼絾澶ч儴鍒嗘病鏈夋瓕璇嶃€?*
   鐞崇悈涔愬簻鐢?AI 鑷姩銆屽惉銆嶅嚭姝岃瘝锛岀敓鎴愭爣鍑?LRC 鏃堕棿杞存枃浠躲€?
2. **浣犳兂鎶婃墜鏈轰笂鐨勬柊姝屼紶鍒扮數鑴戠粺涓€绠＄悊锛屼絾涓嶆兂鎻掓暟鎹嚎銆?*
   鐞崇悈涔愬簻瀹炵幇浜?LocalSend 鍗忚锛屾墜鏈?App 鐩存帴鏃犵嚎浼犳枃浠跺埌鐢佃剳銆?
3. **浣犻渶瑕佺鐞嗗拰缂栬緫宸叉湁姝岃瘝銆?*
   鍙鍖?LRC 缂栬緫鍣?+ CLI 鍛戒护琛?+ JSON 杈撳嚭锛屼汉鍜?AI 閮借兘鐢ㄣ€?
鍏ㄩ儴浠ｇ爜鏈湴杩愯銆備綘涓嶇敤涓婁紶姝屾洸鍒颁换浣曚簯绔湇鍔★紝闅愮瀹夊叏銆?
---

## 鏍稿績浜偣

| 鐗规€?| 璇存槑 |
|------|------|
| 鍙屽紩鎿庡垏鎹?| Groq 浜戠 Whisper锛堝厤璐广€佹瀬閫燂級+ 鏈湴 OpenAI Whisper锛堢绾匡級 |
| 涓枃浼樺寲 | 绻佺畝鑷姩杞崲锛圤penCC锛夛紝China-friendly 妯″瀷涓嬭浇锛圙itHub Releases锛?|
| 瀹屾暣 LRC 鏀寔 | 鐢熸垚銆佽В鏋愩€佺紪杈戙€佸叏灞€鏃堕棿鍋忕Щ銆佹牸寮忚浆鎹?|
| 绾煶涔愭娴?| 璇嗗埆鍚庢瓕璇嶈繃鐭嚜鍔ㄦ爣璁帮紝鎵归噺澶勭悊璺宠繃 |
| 澶氭牸寮?| MP3 / FLAC / WAV / AAC / M4A / OGG / OPUS |
| LocalSend 鍗忚 | 鎵嬫満 App 鐩磋繛锛屾棤闇€棰濆瀹夎浠讳綍鎵嬫満绔蒋浠?|
| GPU 鍔犻€?| 鎵弿鏄惧崱鈫掍竴閿畨瑁?CUDA鈫掕嚜鍔ㄩ噸鍚紝5-10x 閫熷害鎻愬崌 |
| CLI 鍏ㄨ鐩?| 11 涓懡浠わ紝--json 杈撳嚭锛孉I Agent 鍙洿鎺ユ搷浣?|
| 鐏垫椿鍚屾 | 4 绉嶆柟鍚戯紙鍗曞悜/鍙屽悜/闀滃儚锛夛紝鏂囦欢澶瑰樊寮傚彲瑙嗗寲 |
| 姝屾洸绠＄悊 | 鍙岀瓫閫夊櫒銆佹悳绱€佸弻鍑绘敼鍚嶏紙鍚屾鏀?LRC锛夈€佸彸閿爣璁?|

---

## 蹇€熷紑濮?
```bash
# 鍏嬮殕
git clone https://github.com/xiaohaifale-QWQ/Echovault.git
cd Echovault

# 瀹夎鏍稿績渚濊禆
pip install -r requirements.txt

# 瀹夎寮曟搸锛堜簩閫変竴锛?pip install groq           # 浜戠锛屾湁鍏嶈垂棰濆害锛屾帹鑽?pip install openai-whisper  # 鏈湴绂荤嚎锛岄渶涓嬭浇妯″瀷

# 鍚姩 GUI
python main.py

# 鎴?CLI
python main.py --help
```

### 妯″瀷涓嬭浇

鏈湴 Whisper 闇€瑕佺殑妯″瀷鏂囦欢鎵樼鍦ㄧ嫭绔嬩粨搴擄細

**github.com/xiaohaifale-QWQ/echovault-models/releases**

杞欢鍐呯殑涓嬭浇鎸夐挳鐩存帴浠庢浠撳簱鎷夊彇锛屽浗鍐?GitHub 鍙洿鎺ヨ闂€?
---

## 浣跨敤璇存槑

### 鍥惧舰鐣岄潰

```
+-------------------+--------------------------+
|   姝屾洸鍒楄〃         |   璇︽儏 / 闊充箰搴?/ 鍚屾    |
|   (绛涢€?鎼滅储)      |   (姝岃瘝棰勮/鏂囦欢澶规爲/浼犺緭) |
|   [鎵归噺璇嗗埆]       |                          |
+-------------------+--------------------------+
```

### 鍛戒护琛?(AI Agent 鍙嬪ソ)

```bash
# 鍒楀嚭鏃犳瓕璇嶇殑姝屾洸
python main.py list --status no-lrc --json

# 鎵归噺璇嗗埆
python main.py transcribe ./music/ --language zh --json

# 鎼滅储姝岃瘝
python main.py lyrics search "鐞嗘兂" --folder ./music/

# 绠＄悊閰嶇疆
python main.py config set asr.provider local
python main.py config set asr.language zh

# GPU 绠＄悊
python main.py gpu scan
python main.py gpu status
```

瀹屾暣 CLI 鏂囨。: `CLI.md`

### 鎵嬫満鍚屾

1. 鍒囧埌銆屽悓姝ャ€嶉€夐」鍗?鈫?鐐广€屽紑鍚?LocalSend 鎺ユ敹銆?2. 鎵嬫満 LocalSend App 鍙戠幇銆孧usicSync銆嶈澶?3. 鍙戞枃浠?鈫?鑷姩淇濆瓨鍒扮數鑴?
---

## 鍔熻兘娓呭崟

### 姝屾洸绠＄悊
- 姝岃瘝鐘舵€佺瓫閫夛紙鍏ㄩ儴 / 鏈夋瓕璇?/ 鏃犳瓕璇?/ 绾煶涔愶級
- 鏂囦欢鏍煎紡绛涢€夛紙鍔ㄦ€佸垪鍑哄綋鍓嶆枃浠跺す鍐呮墍鏈夋牸寮忥級
- 瀹炴椂鎼滅储
- 鍙屽嚮鏀瑰悕锛堣嚜鍔ㄥ悓姝ラ噸鍛藉悕 LRC 鏂囦欢锛?- 鍙抽敭鏍囪绾煶涔愶紙瀛樺偍鍒?`.musicsync_instrumental.json`锛?
### AI 璇嗗埆
- 寮曟搸鍒囨崲锛欸roq 浜戠 鈫?鏈湴 Whisper
- 鍐呯疆妯″瀷涓嬭浇鍣紙瀹炴椂閫熷害銆佽繘搴︾櫨鍒嗘瘮銆佸墿浣欐椂闂?+ 鍙栨秷鎸夐挳锛?- 鎵归噺璇嗗埆锛堣嚜鍔ㄨ烦杩囧凡鏈夋瓕璇嶅拰绾煶涔愶級
- 鍗曢璇嗗埆闃舵寮忚繘搴︽潯锛堣浆鎹⑩啋璇嗗埆鈫掑悗澶勭悊锛?- 鍋滄璇嗗埆鎸夐挳
- 鍚庡鐞嗙閬擄細鍚堝苟鐭彞 鈫?鎷嗗垎闀胯 鈫?鍒犻櫎閲嶅 鈫?绻佽浆绠€
- 鑷姩绾煶涔愭娴嬶細姝岃瘝 < 20 瀛楄嚜鍔ㄦ爣璁?- 璇嗗埆瀹屾垚鑷姩鍒锋柊鍙充晶姝岃瘝棰勮

### LRC 缂栬緫鍣?- 閫愯缂栬緫銆佹椂闂存埑鍙鍖?- 鍏ㄥ眬鏃堕棿鍋忕Щ锛?30s ~ +30s锛?- 娣诲姞 / 鍒犻櫎姝岃瘝琛?
### GPU 鍔犻€?- 榛樿 CPU 妯″紡锛堣蒋浠惰交閲忥級
- 鎵弿鏄惧崱 鈫?鏄剧ず鍨嬪彿
- 涓€閿畨瑁?PyTorch CUDA锛堝疄鏃惰繘搴?+ 鍙栨秷锛?- 瀹夎瀹屾垚鑷姩閲嶅惎
- 閲嶅惎鍚庤嚜鍔ㄦ娴嬶紝鎸夐挳鍙樼伆

### 鏂囦欢鍚屾
- LocalSend v2.1 鍗忚鎺ユ敹绔紙HTTPS + mDNS锛?- 鏂囦欢澶瑰樊寮傚姣旓紙鏂囦欢鍚?/ 澶у皬 / 鏃堕棿 / MD5锛?- 鍚屾鏂瑰悜锛欰鈫払 / B鈫扐 / 鍙屽悜鍚堝苟 / 瀹屽叏闀滃儚
- 鍘婚噸锛堝悓鍚嶅悓澶у皬璺宠繃锛夈€佸啿绐佸鐞?- HTTP 娴忚鏈嶅姟锛堟墜鏈烘祻瑙堝櫒鍙笅杞界數鑴戞枃浠讹級

### CLI锛堝懡浠よ鎺ュ彛锛?- 11 涓懡浠よ鐩栨墍鏈?GUI 鎿嶄綔
- 鍏ㄩ儴鏀寔 `--json` 杈撳嚭
- 瀹屾暣鏂囨。: `CLI.md`

---

## 鎶€鏈爤

| 灞?| 鎶€鏈?| 璇存槑 |
|------|------|------|
| 璇煶璇嗗埆 | OpenAI Whisper / Groq Whisper API | 鍙屽紩鎿庡彲鍒囨崲 |
| 妯″瀷鍔犺浇 | PyTorch | 鍏煎 HF 鍜屽師濮嬫牸寮?|
| 闊抽澶勭悊 | ffmpeg + pydub | 涓囪兘鏍煎紡杞爜 |
| 鏍囩璇诲啓 | mutagen | MP3/FLAC/M4A/OGG |
| GUI | PyQt6 | 璺ㄥ钩鍙版闈㈢晫闈?|
| 鍚屾 | LocalSend Protocol v2.1 | HTTPS + TLS 1.3 |
| 绻佽浆绠€ | OpenCC | 涓枃鍚庡鐞?|
| 浜哄０鍒嗙 | Demucs锛堝彲閫夛級 | 鎻愬崌璇嗗埆鍑嗙‘鐜?|

---

## 椤圭洰缁撴瀯

```
Echovault/
鈹溾攢鈹€ main.py                 # 鍏ュ彛 (GUI + CLI 11 鍛戒护)
鈹溾攢鈹€ CLI.md                  # CLI 瀹屾暣鍙傝€冩墜鍐?鈹溾攢鈹€ core/
鈹?  鈹溾攢鈹€ asr/               # ASR 寮曟搸灞?鈹?  鈹溾攢鈹€ config.py          # JSON 閰嶇疆鎸佷箙鍖?鈹?  鈹溾攢鈹€ audio_utils.py     # ffmpeg 闊抽杞崲
鈹?  鈹溾攢鈹€ lrc_parser.py      # LRC 瑙ｆ瀽/鏍煎紡鍖?鈹?  鈹溾攢鈹€ lrc_writer.py      # 璇嗗埆->LRC + 鍚庡鐞?鈹?  鈹溾攢鈹€ metadata.py        # mutagen 鍏冩暟鎹?鈹?  鈹溾攢鈹€ sync_engine.py     # 鍚屾寮曟搸
鈹?  鈹斺攢鈹€ whisper_loader.py  # HF 妯″瀷鍔犺浇鍣?鈹溾攢鈹€ server/
鈹?  鈹溾攢鈹€ localsend_receiver.py  # LocalSend 鎺ユ敹绔?鈹?  鈹溾攢鈹€ http_server.py     # HTTP 鏂囦欢娴忚
鈹?  鈹斺攢鈹€ discovery.py       # mDNS 鍙戠幇
鈹溾攢鈹€ ui/
鈹?  鈹溾攢鈹€ main_window.py     # 涓荤獥鍙?鈹?  鈹溾攢鈹€ library_panel.py   # 鏂囦欢澶规爲
鈹?  鈹溾攢鈹€ song_list_panel.py # 姝屾洸鍒楄〃
鈹?  鈹溾攢鈹€ detail_panel.py    # 璇︽儏/姝岃瘝棰勮
鈹?  鈹溾攢鈹€ lyrics_editor.py   # LRC 缂栬緫鍣?鈹?  鈹溾攢鈹€ settings_dialog.py # 鍋忓ソ璁剧疆
鈹?  鈹溾攢鈹€ sync_panel.py      # 鍚屾闈㈡澘
鈹?  鈹斺攢鈹€ transcribe_worker.py  # QThread 鍚庡彴璇嗗埆
鈹斺攢鈹€ requirements.txt
```

---

## 寮€鍙戠姸鎬?
- [x] AI 姝岃瘝璇嗗埆锛堜簯绔?+ 鏈湴锛?- [x] LRC 瀹屾暣绠￠亾锛堣В鏋?鐢熸垚/缂栬緫/鍚庡鐞嗭級
- [x] 鎵归噺澶勭悊 + 闃舵寮忚繘搴︽潯
- [x] 姝屾洸绛涢€?鎼滅储/鏀瑰悕
- [x] 绾煶涔愭爣璁?- [x] LocalSend 鎺ユ敹绔?- [x] 鏂囦欢澶瑰樊寮傚姣?+ 澶氭柟鍚戝悓姝?- [x] 鍐呯疆妯″瀷涓嬭浇鍣?- [x] GPU 鍔犻€燂紙鎵弿/瀹夎/鐘舵€侊級
- [x] CLI 鍏ㄨ鐩栵紙11 鍛戒护 + --json锛?- [x] 鍋滄璇嗗埆 + 鍙栨秷涓嬭浇鎸夐挳
- [ ] 妯″瀷涓婁紶 GitHub Releases锛堥渶 VPN锛?- [ ] GPU CUDA 涓嬭浇鍥藉唴鏂规
- [ ] 鐙珛 exe/dmg 鎵撳寘
- [ ] 鎵嬫満绔?App
- [ ] AI 姝岃瘝缈昏瘧

---

## 宸茬煡闂

| 闂 | 鐘舵€?| 璇存槑 |
|------|------|------|
| 妯″瀷涓嬭浇闇€ VPN | 闃诲 | 妯″瀷鏂囦欢鍦?GitHub Releases锛岃繕鏈笂浼?|
| GPU CUDA 涓嬭浇鎱?| 闃诲 | 2.5GB 浠庡浗闄?CDN锛屾竻鍗庨暅鍍忓彧鏈?CPU 鐗?|
| Whisper 澶存暟 bug | 宸蹭慨澶?| embedding 缁村害璇綋娉ㄦ剰鍔涘ご鏁帮紝瀵艰嚧 reshape 鎶ラ敊 |
| 閲嶅惎鏈哄埗 | 宸蹭慨澶?| done(42) 杩斿洖鐮?+ DETACHED_PROCESS |
| 鏂囦欢鍚嶇紪鐮?| 宸蹭慨澶?| stdout 閲嶉厤缃?UTF-8 |
| sync CLI | 宸蹭慨澶?| FileDiff dataclass 灞炴€ц闂?|

## 鑷磋阿

- [OpenAI Whisper](https://github.com/openai/whisper) 鈥?鏍稿績璇煶璇嗗埆寮曟搸
- [LocalSend](https://github.com/localsend/localsend) 鈥?璺ㄥ钩鍙版枃浠朵紶杈撳崗璁?- [LDDC](https://github.com/chenmozhijin/LDDC) 鈥?妗岄潰姝岃瘝宸ュ叿鍙傝€?- [Lyrico](https://github.com/Replica0110/Lyrico) 鈥?Android 闊充箰鏍囩缂栬緫鍣ㄥ弬鑰?
## License

MIT (c) xiaohaifale
