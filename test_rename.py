import sys, os, tempfile
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, Qt
from ui.song_list_panel import SongListPanel

app = QApplication(sys.argv)
tmp = Path(tempfile.mkdtemp())
(test_file := tmp / 'abc.mp3').write_text('x')

panel = SongListPanel()
songs = [{'path':str(test_file),'name':'abc.mp3','folder':'','size':100,'has_lrc':False,'lrc_path':None}]
panel.load_songs(songs)

# 模拟改名逻辑（新代码：直接改 _songs）
old_str = panel._songs[0]["path"]
old_path = Path(old_str)
new_path = old_path.parent / 'xyz.mp3'
os.rename(old_str, str(new_path))

for s in panel._songs:
    if s["path"] == old_str:
        s["path"] = str(new_path)
        s["name"] = 'xyz.mp3'
        break

panel._do_refresh()
print(f'_songs[0][path] = {panel._songs[0]["path"]}')
print(f'_songs[0][name] = {panel._songs[0]["name"]}')
if panel.table.rowCount() > 0:
    print(f'Table cell = {panel.table.item(0,0).text()}')
    d = panel.table.item(0,0).data(Qt.ItemDataRole.UserRole)
    print(f'Table data path = {d.get("path")}')
print('OK' if panel._songs[0]["path"].endswith('xyz.mp3') else 'FAIL')

QTimer.singleShot(100, app.quit)
app.exec()
