import sys
import requests
import subprocess
import os
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, 
                             QLabel, QComboBox, QLineEdit, QDialog, QProgressBar, 
                             QStackedWidget, QFrame, QScrollArea, QListView, QGridLayout, QMessageBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QIcon, QPixmap

# --- SILENZIA LOGS QT ---
os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.gui.imageio=false"

IMAGE_CACHE = {}

class StalkerTurboEngine(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, host, mac, session):
        super().__init__()
        self.host = host.rstrip('/')
        self.mac = mac
        self.session = session
        self.endpoint = None

    def safe_get(self, url):
        try:
            r = self.session.get(url, timeout=5)
            return r.json() if r.status_code == 200 else None
        except: return None

    def run(self):
        try:
            db = {"itv": [], "genres": {}, "info": {}, "endpoint": ""}
            endpoints = [
                "/portal.php", "/stalker2.php", "/server/load.php", "/server%2fload.php",
                "/load.php", "/stalker_portal.php/server/load.php", "/stalker_portal%2fserver%2fload.php",
                "/c/portal.php", "/c%2fportal.php", "/c/stalker2.php", "/c%2fstalker2.php",
                "/c/server/load.php", "/c%2fserver%2fload.php", "/c/load.php", "/c%2fload.php"
            ]
            
            self.progress.emit(10, "Ricerca Endpoint...")
            found = False
            for ep in endpoints:
                test_url = f"{self.host}{ep}?type=stb&action=handshake&JsHttpRequest=1-xml"
                res = self.safe_get(test_url)
                if res and "js" in res and "token" in res["js"]:
                    self.endpoint = f"{self.host}{ep}"
                    db["endpoint"] = self.endpoint
                    token = res["js"]["token"]
                    self.session.headers.update({'Authorization': f'Bearer {token}'})
                    db["token"] = token
                    found = True
                    break
            
            if not found: 
                raise Exception("Nessun endpoint valido trovato.")

            self.safe_get(f"{self.endpoint}?type=series&action=load&JsHttpRequest=1-xml")
            self.safe_get(f"{self.endpoint}?type=vod&action=load&JsHttpRequest=1-xml")
            
            r_acc = self.safe_get(f"{self.endpoint}?type=account_info&action=get_main_info&JsHttpRequest=1-xml")
            db["info"]["expire"] = r_acc["js"].get("phone", "N/D") if r_acc else "N/D"
            
            self.progress.emit(60, "Sincronizzazione...")
            r_itv = self.safe_get(f"{self.endpoint}?type=itv&action=get_all_channels&JsHttpRequest=1-xml")
            db["itv"] = r_itv["js"] if isinstance(r_itv["js"], list) else r_itv["js"].get("data", [])
            
            for k in ["itv", "vod", "series"]:
                act = "get_genres" if k == "itv" else "get_categories"
                g = self.safe_get(f"{self.endpoint}?type={k}&action={act}&JsHttpRequest=1-xml")
                db["genres"][k] = g["js"] if g else []
            
            self.progress.emit(100, "Pronto!")
            self.finished.emit(db)
        except Exception as e: 
            self.error.emit(str(e))

class StalkerPlayer(QMainWindow):
    def __init__(self, host, mac):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.host, self.mac = host.rstrip('/'), mac
        self.db, self.mpv, self.old_pos = {}, None, None
        self.endpoint = ""
        self.logout_requested = False
        self.current_load_id = None # ID per tracciare il caricamento attivo

        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.execute_search)
        self.pending_search = {"key": None, "text": ""}

        self.session = requests.Session()
        self.ua = 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3'
        self.session.headers.update({'User-Agent': self.ua})
        self.session.cookies.update({'mac': self.mac, 'stb_lang': 'en', 'timezone': 'Europe/Rome'})

        self.resize(1300, 900)
        self.init_ui()
        self.start_loading()

    def init_ui(self):
        self.bg_frame = QFrame(self); self.bg_frame.setObjectName("BgFrame")
        self.setCentralWidget(self.bg_frame)
        self.main_layout = QVBoxLayout(self.bg_frame); self.main_layout.setContentsMargins(0,0,0,0); self.main_layout.setSpacing(0)

        self.title_bar = QWidget(); self.title_bar.setObjectName("TitleBar"); self.title_bar.setFixedHeight(40)
        tb_lay = QHBoxLayout(self.title_bar); tb_lay.setContentsMargins(15,0,0,0)
        self.title_lbl = QLabel("STB Player - Ak1r4 Yuk1"); self.title_lbl.setObjectName("AppTitle")
        tb_lay.addWidget(self.title_lbl); tb_lay.addStretch()
        
        for txt, slot in [("–", self.showMinimized), ("▢", self.toggle_maximized), ("✕", self.close_app)]:
            btn = QPushButton(txt); btn.setObjectName("BtnClose" if txt=="✕" else "BtnTitle")
            btn.clicked.connect(slot); tb_lay.addWidget(btn)
        self.main_layout.addWidget(self.title_bar)

        self.master_stack = QStackedWidget()
        self.loader_page = QFrame(); lp_lay = QVBoxLayout(self.loader_page); lp_lay.addStretch()
        self.status_lbl = QLabel("CONNESSIONE..."); self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pbar = QProgressBar(); self.pbar.setFixedWidth(400); self.pbar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lp_lay.addWidget(self.status_lbl, alignment=Qt.AlignmentFlag.AlignCenter); lp_lay.addWidget(self.pbar, alignment=Qt.AlignmentFlag.AlignCenter); lp_lay.addStretch()
        self.master_stack.addWidget(self.loader_page)

        self.main_page = QWidget(); self.page_lay = QVBoxLayout(self.main_page)
        
        self.header_widget = QWidget()
        self.header_lay = QHBoxLayout(self.header_widget)
        self.header_lay.setContentsMargins(0, 0, 15, 0)
        
        self.lbl_expire = QLabel("ACCOUNT EXPIRES: --"); self.lbl_expire.setObjectName("ExpireLabel")
        self.btn_logout = QPushButton("⏏ LOGOUT"); self.btn_logout.setObjectName("LogoutBtn")
        self.btn_logout.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_logout.clicked.connect(self.perform_logout)

        self.header_lay.addWidget(self.lbl_expire)
        self.header_lay.addStretch()
        self.header_lay.addWidget(self.btn_logout)
        
        self.page_lay.addWidget(self.header_widget)

        self.nav_widget = QWidget(); self.nav_box = QHBoxLayout(self.nav_widget); self.nav_box.setContentsMargins(0,0,0,0)
        self.btn_tv = QPushButton("LIVE TV"); self.btn_film = QPushButton("FILM"); self.btn_serie = QPushButton("SERIE")
        self.nav_btns = [self.btn_tv, self.btn_film, self.btn_serie]
        for i, btn in enumerate(self.nav_btns):
            btn.setCheckable(True); btn.setObjectName("NavBtn"); self.nav_box.addWidget(btn)
            btn.clicked.connect(lambda _, x=i: self.switch_mode(x))
        self.page_lay.addWidget(self.nav_widget)

        self.body_container = QWidget(); self.body_layout = QHBoxLayout(self.body_container)
        self.left_panel = QFrame(); self.left_panel.setObjectName("SidePanel"); lp_v = QVBoxLayout(self.left_panel)
        self.stack = QStackedWidget(); self.ui_map = {}
        for k in ["itv", "vod", "series"]:
            w = QWidget(); vl = QVBoxLayout(w); vl.setContentsMargins(0,0,0,0)
            
            cb = QComboBox(); cb.setObjectName("CatCombo")
            cb.setStyleSheet("QComboBox { combobox-popup: 0; }")
            cb.setView(QListView()); cb.setMaxVisibleItems(10)
            
            search = QLineEdit(); search.setPlaceholderText("🔍 Cerca..."); search.setObjectName("SearchInput")
            lw = QListWidget(); lw.setIconSize(QSize(45,30) if k=="itv" else QSize(80,120))
            vl.addWidget(cb); vl.addWidget(search); vl.addWidget(lw)
            self.stack.addWidget(w); self.ui_map[k] = {"combo": cb, "search": search, "list": lw}
            cb.currentIndexChanged.connect(lambda _, x=k: self.load_content_on_demand(x))
            search.textChanged.connect(lambda t, x=k: self.filter_list(x, t))
            lw.itemClicked.connect(lambda i, x=k: self.show_details(i, x))
        lp_v.addWidget(self.stack); self.body_layout.addWidget(self.left_panel, 1)

        self.right_panel = QFrame(); self.right_panel.setObjectName("InfoPanel"); self.rp_v = QVBoxLayout(self.right_panel)
        self.video_container = QWidget(); self.video_container.setObjectName("VideoCont"); self.video_container.setMinimumHeight(300)
        
        self.scroll_info = QScrollArea(); self.scroll_info.setWidgetResizable(True); self.scroll_info.setStyleSheet("background: transparent; border: none;")
        self.info_content = QWidget(); self.info_lay = QVBoxLayout(self.info_content)
        
        self.lbl_title = QLabel("Seleziona un contenuto"); self.lbl_title.setObjectName("DetailTitle"); self.lbl_title.setWordWrap(True)
        
        self.meta_widget = QWidget(); self.meta_lay = QHBoxLayout(self.meta_widget); self.meta_lay.setContentsMargins(0,5,0,5)
        self.lbl_year = QLabel(""); self.lbl_rating = QLabel(""); self.lbl_genre = QLabel("")
        
        for l in [self.lbl_year, self.lbl_rating, self.lbl_genre]: 
            l.setStyleSheet("color: #0078ff; font-weight: bold; font-size: 12px;"); self.meta_lay.addWidget(l)
        
        self.series_selectors = QFrame(); self.series_selectors.setObjectName("SeriesSelectorBox"); ss_lay = QHBoxLayout(self.series_selectors); ss_lay.setContentsMargins(15,10,15,10)
        self.combo_seasons = QComboBox(); self.combo_episodes = QComboBox()
        for combo in [self.combo_seasons, self.combo_episodes]:
            combo.setObjectName("CatCombo"); combo.setStyleSheet("QComboBox { combobox-popup: 0; }"); combo.setView(QListView()); combo.setMaxVisibleItems(10)
        
        lbl_s = QLabel("STAGIONE:"); lbl_s.setStyleSheet("color: #8a8a9d; font-size: 10px; font-weight: bold;")
        lbl_e = QLabel("EPISODIO:"); lbl_e.setStyleSheet("color: #8a8a9d; font-size: 10px; font-weight: bold;")
        
        ss_lay.addWidget(lbl_s); ss_lay.addWidget(self.combo_seasons, 1); ss_lay.addSpacing(15)
        ss_lay.addWidget(lbl_e); ss_lay.addWidget(self.combo_episodes, 1)
        self.series_selectors.hide()
        
        self.mid_layout = QHBoxLayout(); self.mid_layout.setSpacing(15)
        self.big_poster = QLabel(); self.big_poster.setFixedSize(180, 270); self.big_poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tech_info = QLabel(); self.tech_info.setWordWrap(True); self.tech_info.setObjectName("ExtraInfo")
        self.mid_layout.addWidget(self.big_poster); self.mid_layout.addWidget(self.tech_info, 1)

        self.lbl_plot = QLabel(""); self.lbl_plot.setWordWrap(True); self.lbl_plot.setObjectName("DetailPlot")
        
        self.info_lay.addWidget(self.lbl_title); self.info_lay.addWidget(self.meta_widget); self.info_lay.addWidget(self.series_selectors)
        self.info_lay.addLayout(self.mid_layout); self.info_lay.addWidget(self.lbl_plot); self.info_lay.addStretch()
        
        self.scroll_info.setWidget(self.info_content)
        self.btn_play = QPushButton("▶ RIPRODUCI ORA"); self.btn_play.setObjectName("PlayBtn"); self.btn_play.hide()
        self.btn_play.clicked.connect(self.play_selection)
        
        self.rp_v.addWidget(self.video_container, 1); self.rp_v.addWidget(self.scroll_info, 2); self.rp_v.addWidget(self.btn_play)
        
        self.body_layout.addWidget(self.right_panel, 2); self.page_lay.addWidget(self.body_container); self.master_stack.addWidget(self.main_page); self.main_layout.addWidget(self.master_stack)
        self.setStyleSheet(STYLE)

    def start_loading(self):
        self.worker = StalkerTurboEngine(self.host, self.mac, self.session)
        self.worker.progress.connect(lambda v, m: (self.pbar.setValue(v), self.status_lbl.setText(m)))
        self.worker.finished.connect(self.on_data_ready)
        self.worker.error.connect(self.on_connection_error)
        self.worker.start()

    def on_connection_error(self, err_msg):
        self.status_lbl.setText(f"Errore: {err_msg}")
        QTimer.singleShot(1500, self.perform_logout)

    def perform_logout(self):
        self.logout_requested = True
        self.close()

    def on_data_ready(self, db):
        self.db, self.endpoint = db, db["endpoint"]
        self.lbl_expire.setText(f"ACCOUNT EXPIRES: {db['info']['expire']}")
        for k in ["itv", "vod", "series"]:
            ui = self.ui_map[k]; ui["combo"].blockSignals(True); ui["combo"].clear()
            for g in db["genres"][k]:
                if (g.get("title") or g.get("name") or "").lower() == "all": continue
                ui["combo"].addItem(g.get("title") or g.get("name"), g.get("id"))
            if ui["combo"].count() > 0: ui["combo"].setCurrentIndex(0)
            ui["combo"].blockSignals(False)
        self.master_stack.setCurrentIndex(1); self.switch_mode(0)

    def switch_mode(self, index):
        mode = ["itv", "vod", "series"][index]
        self.stack.setCurrentIndex(index); [b.setChecked(i == index) for i, b in enumerate(self.nav_btns)]
        self.video_container.setVisible(mode == "itv"); self.series_selectors.hide(); self.load_content_on_demand(mode)

    def download_single_logo(self, url):
        if not url or url in IMAGE_CACHE: return
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                pix = QPixmap(); pix.loadFromData(r.content); IMAGE_CACHE[url] = pix
        except: pass

    def load_content_on_demand(self, key):
        ui = self.ui_map[key]
        cat_id = ui["combo"].currentData()
        ui["list"].clear()
        if cat_id is None: return
        
        self.lbl_title.setText("Caricamento...")
        self.current_load_id = f"{key}_{cat_id}" # Impedisce sovrapposizione caricamenti
        
        if key == "itv":
            items = [ch for ch in self.db["itv"] if str(ch.get("tv_genre_id")) == str(cat_id)]
            self.display_search_results(key, items)
            self.lbl_title.setText("Pronto")
        else:
            # Avviamo il caricamento a pagine ricorsivo
            self.fetch_pages_recursive(key, cat_id, page=1)

    def fetch_pages_recursive(self, key, cat_id, page):
        # Verifica se l'utente ha cambiato categoria nel frattempo
        if self.current_load_id != f"{key}_{cat_id}": return

        url = f"{self.endpoint}?type={key}&action=get_ordered_list&category={cat_id}&p={page}&JsHttpRequest=1-xml"
        
        try:
            res = self.session.get(url, timeout=7).json()
            if res and "js" in res:
                data = res["js"].get("data", [])
                total_items = int(res["js"].get("total_items", 0))
                
                if data:
                    # Mostra subito i risultati scaricati in questa pagina
                    self.display_search_results(key, data, append=True)
                    
                    current_count = self.ui_map[key]["list"].count()
                    if current_count < total_items and len(data) > 0:
                        # Richiama la pagina successiva con un micro-delay per mantenere la UI fluida
                        QTimer.singleShot(5, lambda: self.fetch_pages_recursive(key, cat_id, page + 1))
                    else:
                        self.lbl_title.setText("Pronto")
                else:
                    self.lbl_title.setText("Fine risultati")
        except:
            pass

    def filter_list(self, key, text):
        self.pending_search = {"key": key, "text": text}; self.search_timer.start(800)

    def execute_search(self):
        key, text = self.pending_search["key"], self.pending_search["text"]
        if not key or not self.endpoint: return
        if not text: self.load_content_on_demand(key); return
        ui = self.ui_map[key]; ui["list"].clear(); search_term = text.lower()
        if key == "itv":
            self.display_search_results(key, [ch for ch in self.db["itv"] if search_term in ch.get("name", "").lower()])
        else:
            url = f"{self.endpoint}?type={key}&action=get_ordered_list&search={search_term}&JsHttpRequest=1-xml"
            try:
                res = self.session.get(url, timeout=5).json()
                data = res["js"].get("data", []) if res and "js" in res else []
                if not data:
                    res_f = self.session.get(f"{self.endpoint}?type={key}&action=get_ordered_list&category={ui['combo'].currentData()}&search={search_term}&JsHttpRequest=1-xml").json()
                    data = res_f["js"].get("data", []) if res_f and "js" in res_f else []
                self.display_search_results(key, data)
            except: pass

    def display_search_results(self, key, items, append=False):
        ui = self.ui_map[key]
        if not append:
            ui["list"].clear()
            
        if not items: 
            if not append: self.lbl_title.setText("Nessun risultato.")
            return
            
        urls = [i.get("logo") or i.get("screenshot_uri") for i in items if (i.get("logo") or i.get("screenshot_uri"))]
        with ThreadPoolExecutor(max_workers=30) as ex: ex.map(self.download_single_logo, urls)
        
        for item in items:
            it = QListWidgetItem(item.get("name") or item.get("o_name"))
            it.setData(Qt.ItemDataRole.UserRole, item)
            img = item.get("logo") or item.get("screenshot_uri")
            if img in IMAGE_CACHE: it.setIcon(QIcon(IMAGE_CACHE[img]))
            ui["list"].addItem(it)
            
        # Aggiorna la UI per mostrare i contenuti man mano che arrivano
        QApplication.processEvents()

    def show_details(self, item, key):
        data = item.data(Qt.ItemDataRole.UserRole); self.active_selection = (data, key)
        self.lbl_title.setText(data.get("name", "N/D").upper())
        
        if key == "itv":
            self.lbl_plot.hide(); self.meta_widget.hide(); self.tech_info.hide(); self.series_selectors.hide()
            self.big_poster.setFixedSize(270, 180)
        else:
            self.lbl_plot.show(); self.meta_widget.show(); self.tech_info.show()
            self.big_poster.setFixedSize(180, 270)
            self.lbl_plot.setText(f"<b>TRAMA:</b><br>{data.get('description', 'Non disponibile.')}")
            self.lbl_year.setText(f"📅 {data.get('year', 'N/D')[:4]}")
            self.lbl_rating.setText(f"⭐ IMDB: {data.get('rating_imdb', 'N/D')}")
            self.lbl_genre.setText(f"🏷️ {data.get('genres_str', 'N/D')}")
            tech = f"<p style='line-height:1.5;'><b>REGISTA:</b><br>{data.get('director', 'N/D')}<br><br><b>CAST:</b><br>{data.get('actors', 'N/D')}</p>"
            self.tech_info.setText(tech)

        self.series_selectors.hide()
        self.combo_seasons.blockSignals(True); self.combo_seasons.clear(); self.combo_seasons.blockSignals(False)
        self.combo_episodes.blockSignals(True); self.combo_episodes.clear(); self.combo_episodes.blockSignals(False)

        if key == "series":
            self.series_selectors.show()
            res = self.session.get(f"{self.endpoint}?type=series&action=get_ordered_list&movie_id={data['id']}&JsHttpRequest=1-xml").json()
            if res and "js" in res:
                self.combo_seasons.blockSignals(True)
                for s in res["js"].get("data", []):
                    self.combo_seasons.addItem(s.get("name"), {"id": data['id'].split(':')[0], "num": s.get("id").split(':')[-1], "eps": s.get("series", [])})
                self.combo_seasons.blockSignals(False)
                if self.combo_seasons.count() > 0: self.combo_seasons.setCurrentIndex(0); self.update_episodes()

        img = data.get("logo") or data.get("screenshot_uri")
        if img in IMAGE_CACHE:
            self.big_poster.setPixmap(IMAGE_CACHE[img].scaled(self.big_poster.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else: self.big_poster.clear()
        self.btn_play.show()

    def update_episodes(self):
        self.combo_episodes.blockSignals(True); self.combo_episodes.clear()
        s_data = self.combo_seasons.currentData()
        if s_data:
            for ep in s_data["eps"]: self.combo_episodes.addItem(f"Episodio {ep}", ep)
            if self.combo_episodes.count() > 0: self.combo_episodes.setCurrentIndex(0) 
        self.combo_episodes.blockSignals(False)

    def play_selection(self):
        if not hasattr(self, 'active_selection'): return
        
        self.btn_play.setEnabled(False)
        self.btn_play.setText("⌛ AVVIO...")
        QApplication.processEvents()
        
        data, key = self.active_selection
        try:
            if key == "series":
                s_data = self.combo_seasons.currentData(); ep = self.combo_episodes.currentData()
                if not s_data or not ep: raise Exception("No season/episode")
                payload = {"series_id": int(s_data["id"]), "season_num": int(s_data["num"]), "episode_num": int(ep), "type": "series"}
                url = f"{self.endpoint}?type=vod&action=create_link&cmd={base64.b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode()}&series=1&JsHttpRequest=1-xml"
            else:
                cmd = data.get("id") if key=="itv" else data.get("cmd")
                url = f"{self.endpoint}?type={'itv' if key=='itv' else 'vod'}&action=create_link&cmd={f'http://localhost/ch/{cmd}' if key=='itv' else cmd}&JsHttpRequest=1-xml"
            
            r = self.session.get(url, timeout=10).json()
            if r and "js" in r and "cmd" in r["js"]:
                if self.mpv: self.mpv.terminate()
                self.mpv = subprocess.Popen(["mpv", "--fs", "--ontop", "--really-quiet", f"--user-agent={self.ua}", r["js"]["cmd"].replace("ffmpeg ", "").split(" ")[0]])
        except: pass
        
        self.btn_play.setText("▶ RIPRODUCI ORA")
        self.btn_play.setEnabled(True)

    def close_app(self):
        if hasattr(self, 'mpv') and self.mpv: self.mpv.terminate()
        self.close()

    def toggle_maximized(self):
        if self.isMaximized(): self.showNormal()
        else: self.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.title_bar.underMouse(): self.old_pos = event.globalPosition().toPoint()
    def mouseMoveEvent(self, event):
        if hasattr(self, 'old_pos') and self.old_pos:
            delta = event.globalPosition().toPoint() - self.old_pos; self.move(self.x() + delta.x(), self.y() + delta.y()); self.old_pos = event.globalPosition().toPoint()
    def mouseReleaseEvent(self, event): self.old_pos = None

class Login(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.old_pos = None 
        self.setStyleSheet("""
            #LoginBg { background: #0f0f13; border: 1px solid #2a2a35; border-radius: 12px; }
            #LoginTitleBar { background: #1a1a24; border-top-left-radius: 12px; border-top-right-radius: 12px; }
            QLabel { color: #8a8a9d; font-weight: bold; font-size: 11px; }
            QLineEdit { background: #252535; border: 1px solid #3d3d5c; color: white; padding: 10px; border-radius: 8px; }
            QPushButton#CloseBtn { background: transparent; color: white; border: none; }
            QPushButton#LoginBtn { background: #0078ff; color: white; font-weight: bold; padding: 15px; border-radius: 6px; }
            QPushButton#LoginBtn:hover { background: #1a8aff; }
            QPushButton#LoginBtn:pressed { background: #005bb5; }
        """)
        self.setFixedSize(400, 320); layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        bg = QFrame(); bg.setObjectName("LoginBg"); layout.addWidget(bg); bg_lay = QVBoxLayout(bg); bg_lay.setContentsMargins(0,0,0,0)
        
        self.title_bar = QWidget(); self.title_bar.setObjectName("LoginTitleBar"); self.title_bar.setFixedHeight(40)
        tb_lay = QHBoxLayout(self.title_bar)
        tb_lay.addWidget(QLabel("ACCESSO")); tb_lay.addStretch(); cb = QPushButton("✕"); cb.setObjectName("CloseBtn"); cb.clicked.connect(self.reject); tb_lay.addWidget(cb)
        bg_lay.addWidget(self.title_bar)
        
        form = QVBoxLayout(); form.setContentsMargins(30,20,30,30); 
        self.srv = QLineEdit("http://SERVER:PORT/c/"); self.mac = QLineEdit("00:1A:79:XX:XX:XX")
        btn = QPushButton("ACCEDI"); btn.setObjectName("LoginBtn"); btn.clicked.connect(self.accept)
        form.addWidget(QLabel("URL")); form.addWidget(self.srv); form.addWidget(QLabel("MAC")); form.addWidget(self.mac); form.addStretch(); form.addWidget(btn); bg_lay.addLayout(form)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.title_bar.underMouse(): 
            self.old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.old_pos:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.old_pos = None

STYLE = """
    #BgFrame { background: #0f0f13; border: 1px solid #2a2a35; border-radius: 12px; }
    #TitleBar { background: #1a1a24; border-top-left-radius: 12px; border-top-right-radius: 12px; }
    #AppTitle { color: #8a8a9d; font-weight: bold; font-size: 11px; }
    #BtnTitle, #BtnClose { background: transparent; color: white; border: none; font-size: 14px; width: 35px; }
    #BtnClose:hover { background: #e81123; }
    #NavBtn { background: #1a1a24; border: 1px solid #2a2a35; color: #a0a0b0; padding: 12px; font-weight: bold; border-radius: 6px; }
    #NavBtn:checked { background: #0078ff; color: white; }
    #SidePanel, #InfoPanel { background: #16161e; border-radius: 10px; padding: 10px; margin: 5px; }
    
    QComboBox, QLineEdit { 
        background: #252535; border: 1px solid #3d3d5c; color: #e0e0e0; padding: 8px; border-radius: 6px; font-weight: bold;
    }
    QComboBox:hover, QLineEdit:hover { background: #2d2d44; border: 1px solid #0078ff; }
    QComboBox:focus, QLineEdit:focus { border: 1px solid #0078ff; }

    #SeriesSelectorBox { background: #1e1e2d; border: 1px solid #3d3d5c; border-radius: 10px; margin: 10px 0px; }
    QComboBox::drop-down { border: none; width: 30px; }
    QComboBox::down-arrow { border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 5px solid #0078ff; margin-right: 10px; }
    QComboBox QAbstractItemView { background-color: #1a1a24; color: #d0d0d0; selection-background-color: #0078ff; selection-color: white; border: 1px solid #3d3d5c; outline: none; padding: 5px; }

    QListWidget { background: transparent; border: none; color: #ccc; }
    QListWidget::item:selected { background: #0078ff22; color: #0078ff; border-left: 4px solid #0078ff; }
    
    #PlayBtn { 
        background: #0078ff; 
        color: white; 
        font-weight: bold; 
        padding: 15px; 
        border-radius: 6px; 
    }
    #PlayBtn:hover {
        background: #1a8aff;
    }
    #PlayBtn:pressed {
        background: #005bb5;
        padding-top: 16px;
        padding-bottom: 14px;
    }

    #LogoutBtn {
        background: transparent;
        color: #e81123;
        font-weight: bold;
        border: 1px solid #e81123;
        border-radius: 4px;
        padding: 4px 8px;
    }
    #LogoutBtn:hover {
        background: #e81123;
        color: white;
    }
    
    #DetailTitle { color: white; font-size: 18px; font-weight: bold; margin-bottom: 5px; }
    #DetailPlot { color: #ccc; font-size: 13px; line-height: 1.5; margin-top: 15px; }
    #ExtraInfo { color: #999; font-size: 12px; }
"""

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    while True:
        log = Login()
        if log.exec() != QDialog.DialogCode.Accepted:
            break
            
        win = StalkerPlayer(log.srv.text(), log.mac.text())
        win.show()
        
        app.exec() 
        
        if not win.logout_requested:
            break
    
    sys.exit()
