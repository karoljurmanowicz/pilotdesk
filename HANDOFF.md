# PilotDesk – przekazanie projektu (handoff)

Stan na: 2026-11-26 · wersja **3.6** (wydawana przez CI) · repozytorium **github.com/karoljurmanowicz/pilotdesk** (publiczne)

Ten plik jest dla osoby (lub kolejnej sesji Claude), która przejmuje prace. Najpierw przeczytaj
**„Otwarte problemy”** – pierwszy z nich zgłosił użytkownik tuż przed przekazaniem.

---

## 1. Czym jest PilotDesk

Własny zdalny pulpit (w stylu AnyDesk) do łączenia się między **własnymi komputerami użytkownika** (Windows 10/11).
Python 3.12 + customtkinter, budowany do jednego pliku `PilotDesk.exe` (PyInstaller), który jest jednocześnie
instalatorem. Interfejs i komunikaty – **po polsku**.

Funkcje (wszystkie zaimplementowane): sterowanie w oknie sesji z kartami, wideo H.264 (fallback JPEG), dźwięk
(Opus), schowek tekst + pliki (Ctrl+C/Ctrl+V), menedżer plików, czat, tryb prywatności, zdalny restart
z ponownym łączeniem, Wake-on-LAN, połączenia bez hasła z „Akceptuj/Odrzuć” + „Zapamiętaj ten komputer”,
wyszukiwanie komputerów po ID w LAN/Tailscale bez serwera, połączenie zwrotne (gdy zapora blokuje), wspólna
mysz i klawiatura (przejście kursorem przez krawędź ekranu), usługa Windows (ekran logowania/UAC),
automatyczne aktualizacje z GitHub Releases, dziennik zdarzeń z wykrywaniem zawieszeń.

## 2. Użytkownik i jego środowisko (ważne przy diagnozie)

- Komunikuje się po polsku, nie jest programistą – oczekuje prostych instrukcji krok po kroku i maksymalnie
  prostej obsługi („aplikacja ma być jak najprostsza i intuicyjna”).
- **Dwa komputery z Windows** w tej samej sieci domowej:
  - PC 1 ma **Tailscale**.
  - PC 2 (Windows 11) ma **Wi-Fi + kabel Ethernet do urządzenia (drukarki)** – ta druga karta prawdopodobnie ma
    własny, niedziałający DNS (stąd wcześniejsze problemy z aktualizacjami). **Nie można na nim zainstalować
    Tailscale.** Oprogramowanie drukarki często działa jako administrator.
  - Nazwy komputerów, ich ID i adresy IP celowo nie są tu zapisane (repozytorium jest publiczne) – poproś
    użytkownika albo zobacz w programie.
- Chce łączyć się **przez internet bez wspólnej sieci** → wybrał **własny serwer pośredniczący**. Ma serwer ze
  stroną internetową – **nie wiemy jeszcze, czy to VPS z SSH, czy zwykły hosting** (pytanie wisi, patrz §8).
- Pierwsza wersja 3.0 była zainstalowana z paczki zip (bez źródła aktualizacji); od 3.2+ aktualizacje działają
  z programu, ale na PC 2 trzeba było aktualizować ręcznie z GitHub Releases.

## 3. Otwarte problemy (priorytet)

### 3.1 [3.6 – POPRAWKA WYDANA, CZEKA NA POTWIERDZENIE] Przyciski myszy nie działają w oknie sesji
Zgłoszenie (po 3.5): *„przyciski myszki nie działają we współdzielonym ekranie”* – ruch działał, kliknięcia nie.

Co zrobiono w 3.6:
1. **Znaleziony i naprawiony błąd we „Wspólnej myszy”** (odtworzony w teście): `HostSession` przesuwa kursor,
   pynput przekazuje taki ruch do `EdgeSwitch` w tym samym procesie (`Controller._emit`), więc zdalny ruch do
   krawędzi ekranu przełączał wspólną mysz na drugi komputer → haki `suppress=True` połykały wszystkie
   kliknięcia (`SetCursorPos` omija hak, więc ruch nadal działał). Teraz `EdgeSwitch` ignoruje ruchy
   `injected` i ruchy w ciągu 1 s od zdalnego wejścia (`pd_common.note_remote_input/remote_input_recent`).
   Uwaga: w trybie usługi (agent w osobnym procesie) działa tylko flaga `injected` (LLMHF_INJECTED).
2. Mysz w Windows przez własne `SendInput` (`pd_winutil.mouse_move/mouse_button/mouse_wheel`):
   `SetCursorPos` + zdarzenie z `MOVE|ABSOLUTE|VIRTUALDESK` i przyciskiem, znacznik `dwExtraInfo=PD_INPUT_TAG`,
   sprawdzanie wyniku; odrzucenie (np. błąd 5 – ekran blokady/UAC) → wpis w dzienniku i toast u przeglądającego.
   Przy wyjątku automatyczny powrót do pynput. Klawiatura nadal przez pynput.
3. UIPI: `_check_uipi(point)` sprawdza okno **pod kursorem** (`window_info_at`), dla klawiszy – pierwszy plan.
4. Dziennik: tryb DPI + ekran wirtualny + monitory mss na starcie sesji, pierwsze 6 zdarzeń przycisków
   z wynikiem (host) i pierwsze 3 kliknięcia z pozycją (przeglądający).
5. Autotest CI (`launcher.mouse_selftest`): rozmiar struktury INPUT (musi być 40/28 – inaczej błąd wydania)
   oraz prawdziwe kliknięcie w okno Tk na maszynie Windows (`click_received` – tylko informacyjnie).

Jeśli problem wróci: poprosić o `pilotdesk.log` z **obu** komputerów (Ustawienia → Dziennik zdarzeń → Otwórz)
i szukać linii „Mysz: …”, „Okno sesji …: klik”, „Wspólna mysz: przejście”, „odrzucone przez Windows”.
Pozostałe hipotezy: UIPI (program DTF jako administrator → usługa systemowa), DPI (porównać „DPI-awareness”,
„ekran wirtualny” i monitory mss w dzienniku).

### 3.2 Łączenie przez internet (bez wspólnej sieci) – czeka na użytkownika
Gotowe: `pd_relay.py` (serwer asyncio, bez zależności) + `scripts/install_relay.sh` (jedno polecenie:
Python, systemd, zapora ufw/firewalld/iptables Oracle Cloud). Czekamy na informację, czy serwer użytkownika
to VPS z SSH. Gdy serwer działa: wpisać jego adres jako domyślny (np. stała `DEFAULT_RELAY` w `pd_common.py`
używana, gdy `cfg["relay"]` puste), podnieść `VERSION`, wypchnąć – oba komputery pobiorą aktualizację.
Jeśli to zwykły hosting (cPanel) – relay TCP tam nie zadziała; alternatywa: Oracle Cloud Always Free.

### 3.3 Niesprawdzone na prawdziwym Windows (napisane, sprawdzone tylko importy w CI)
Usługa systemowa i agent (`pd_service.py`), tryb prywatności (`PrivacyScreen`), schowek plików CF_HDROP,
dźwięk (soundcard/WASAPI), ikona w zasobniku (pystray), instalator/odinstalowanie/skróty, podmiana exe przy
aktualizacji (`--apply-update`), „Napraw zaporę”, wspólna mysz z hakami Windows (`suppress=True`).

## 4. Architektura (pliki)

| Plik | Rola |
|---|---|
| `launcher.py` | **Punkt wejścia exe.** Łapie błędy startu → `error.log`; `--selftest PLIK.json` (używany w CI) |
| `pilotdesk.py` | Okno główne (klasa `App`), strony: Połącz, Komputery, Mysz i klawiatura, Dostęp, Ustawienia, Aktualizacje; instalator (`InstallWindow`); CLI i tryby wewnętrzne (`--service`, `--agent`, `--install-service`, `--uninstall-service`, `--service-update`, `--apply-update`) |
| `pd_common.py` | `VERSION`, protokół, szyfrowanie, konfiguracja, transfer plików, `get_local_ips` (nieblokujące), WoL |
| `pd_host.py` | `HostService` (nasłuch TCP z zapasowymi portami, relay, discovery, połączenie zwrotne), `HostSession` (ekran JPEG/H.264, wejście przez pynput, schowek, pliki, prywatność, restart, UIPI) |
| `pd_viewer.py` | `SessionsWindow` (karty), `SessionView` (obraz, wejście, ponowne łączenie), `ChatWindow`, `FileManager`, `ConnectedBanner` |
| `pd_kvm.py` | Wspólna mysz: `KvmLink` (połączenie bez obrazu), `EdgeSwitch` (krawędź, haki pynput `suppress=True`, powrót Ctrl+Alt+Esc), `ArrangementCanvas` (układ ekranów) |
| `pd_discovery.py` | UDP 47802: wyszukiwanie po ID (broadcast, Tailscale `tailscale status --json`, zapamiętane IP), `request_callback` |
| `pd_media.py` | H.264 (PyAV: libx264 → h264_mf → nvenc/qsv/amf), Opus, przechwytywanie/odtwarzanie dźwięku |
| `pd_clipfiles.py` | `ClipboardSync` (tekst + pliki w obie strony), CF_HDROP (Windows), text/uri-list (Linux) |
| `pd_winutil.py` | Prywatność, `BlockInput`, `sync_input_desktop` (agent), restart, `run_elevated`, `foreground_info` (UIPI) |
| `pd_service.py` | Usługa Windows + agent w sesji użytkownika (token SYSTEM), kanał sterujący 127.0.0.1:47803, `ServiceHostProxy` dla okna |
| `pd_update.py` / `pd_net.py` | Aktualizacje (GitHub Releases / JSON); HTTPS: truststore (certyfikaty systemu), zapasowy DNS 1.1.1.1/8.8.8.8, proxy, `diagnose()` |
| `pd_install.py` | Instalacja do `%LOCALAPPDATA%\Programs\PilotDesk`, skróty (PowerShell COM), autostart (HKCU Run), wpis w „Aplikacje”, jedna instancja (TCP 47801) |
| `pd_log.py` | Dziennik `pilotdesk.log` (rotacja), błędy wątków, `UiWatchdog` (stos wątków przy zawieszeniu okna > 4 s) |
| `pd_ui.py` / `pd_theme.py` | Komponenty i system wizualny (patrz §6), logo i ikony rysowane w PIL |
| `pd_relay.py` | Serwer pośredniczący (TCP 47900) |

Porty: TCP 47800 (bezpośrednie, zapasowe 47810…), UDP 47802 (discovery/callback), TCP 47801 (jedna instancja,
localhost), TCP 47803 (agent↔okno, localhost), TCP 47900 (relay).

Konfiguracja: `~/.pilotdesk.json` (użytkownik); w trybie usługi ustawienia udostępniania w
`%PROGRAMDATA%\PilotDesk\host.json` (`host_config_path()`).

## 5. Protokół (v2, `PROTO = 2`)

- Ramki: 4 bajty długości + AES-256-GCM (licznik jako nonce, osobne klucze w obie strony).
- Uzgadnianie: jawne hello hosta (sól hasła, nonce, klucz X25519, `pw`, `ask`) → odpowiedź klienta (nonce, X25519, `mode` = `password`|`ask`) → klucze = HKDF(ECDH ‖ scrypt(hasło) albo zera). Kod weryfikacyjny 6 cyfr z materiału klucza.
- `auth` od klienta może zawierać `device_pub` + `device_sig` (Ed25519 nad transkryptem) → host porównuje z `cfg["trusted"]` („Zapamiętaj ten komputer”).
- Typy: `M_JSON=1`, `M_FRAME=2` (kafelki JPEG), `M_FILE=3`, `M_VIDEO=4` (H.264), `M_AUDIO=5` (Opus).
- Przepływ obrazu: maks. 2 niepotwierdzone klatki (`ack`). Host wysyła JSON przez kolejkę `outq` (od 3.5), żeby wątek wejścia nigdy nie czekał na sieć.

## 6. Zasady wyglądu (nie wracać do „AI slop”)

Neutralne szarości (`#09090B` tło, powierzchnie `#111114`, cienkie obramowania), **jeden kolor sygnałowy**
(zielony `#3DD68C` = online/włączone), główny przycisk = biała „pigułka”, etykiety sekcji czcionką mono
wersalikami z linią („OSTATNIE ────”), czcionki Geist/Geist Mono dołączone w `fonts/` (OFL, nazwy „PD Geist…”).
Bez gradientów, emoji i kolorowych plakietek pod ikonami. Inspiracja: getduodesk.vercel.app (podana przez
użytkownika). Logo: dwa nachodzące ekrany + zielona kropka.

## 7. Budowanie, wydania, aktualizacje

- **Wydanie = podniesienie `VERSION` w `pd_common.py` + wpis w `CHANGELOG.md` (`## X.Y`) + push na `main`.**
  Workflow `.github/workflows/build.yml` (windows-latest): instalacja zależności → `build_exe.py` →
  **autotest `PilotDesk.exe --selftest`** → publikacja wydania `vX.Y` (exe + `.sha256`, opis z CHANGELOG).
  Programy u użytkownika sprawdzają `releases/latest` przy starcie i co 12 h.
- Zmiany bez wydania (np. dokumentacja) – w treści commita `[skip ci]`.
- Z tej sesji **nie da się wypchnąć tagów ani tworzyć repozytoriów** (polityka środowiska) – dlatego wydania
  tworzy workflow z numeru wersji. Push na `main` działa (bywa zrywany – ponawiać).
- Postęp/wynik CI można czytać bez logowania: `curl https://api.github.com/repos/karoljurmanowicz/pilotdesk/actions/runs?head_sha=SHA`
  i logi: `.../actions/runs/ID/logs` (zip; raport autotestu w kroku „Autotest”). `gh` CLI ma tu nieważny token.
- Commity: autor `karoljurmanowicz <karoljurmanowicz@users.noreply.github.com>`, na końcu wiadomości linie
  atrybucji z bieżącej sesji (Co-Authored-By / Claude-Session) zgodnie z instrukcją systemową.
- Lokalnie: `python build_exe.py` (na Linuksie powstaje binarka linuksowa – przydatne do sprawdzenia spakowania).
  Budowanie exe przez Wine w tym kontenerze nie działa (Wine się wywraca).

## 8. Testowanie w tym środowisku (Linux, bez Windows)

- Python 3.12 (`python3.12`, ma tkinter); zależności z `requirements.txt` zainstalowane.
- Wirtualne ekrany: `Xvfb :99` (komputer sterowany) i `Xvfb :98` (sterujący); `xdotool`, `xclip`, `mss` do zrzutów.
- Host bez okna: `HOME=<katalog_testowy> DISPLAY=:99 python3.12 launcher.py --host` (hasło testowe ustawiane
  przez `set_host_password`). Klient testowy: `open_tcp` + `viewer_handshake` z `pd_common`.
- Sprawdzone tak w tej sesji: wszystkie tryby uzgadniania, H.264 i Opus, schowek plików w obie strony, WoL,
  karty i ponowne łączenie, discovery + zapasowy port + połączenie zwrotne, wspólna mysz (wejście przez
  krawędź, klik, pisanie, Ctrl+Alt+Esc), sterowanie przy zatkanym wysyłaniu obrazu, watchdog, aktualizator
  (prawdziwy GitHub, zła suma kontrolna, zapasowy DNS).
- Rozgłoszenie UDP nie wraca w sieci kontenera – discovery testuj adresem podanym w `extra`.

## 9. Następne kroki (propozycja)

1. Potwierdzić z użytkownikiem §3.1 (kliknięcia) po aktualizacji do 3.6; w razie czego – logi z obu PC.
2. Dokończyć §3.2 (relay na serwerze użytkownika) i wpisać domyślny adres w programie.
3. Na prawdziwym Windows przejść listę §3.3 (najpierw usługa systemowa – rozwiązuje też UIPI).
4. Rozważyć podpis cyfrowy exe (SmartScreen) i ewentualnie przejście z PyInstaller onefile na onedir
   (szybszy start, mniej fałszywych alarmów antywirusów).
