# PilotDesk 3.1

Zdalny pulpit do Twoich komputerów: bez limitów, bez konta, z szyfrowaniem end-to-end.
Program to jeden plik **PilotDesk.exe**, który przy pierwszym uruchomieniu sam się instaluje.

## Instalacja (Windows)

1. **Zbuduj PilotDesk.exe (jeden raz).** Kliknij dwukrotnie `ZBUDUJ_PILOTDESK_EXE.bat`. Jeśli nie masz
   Pythona, skrypt sam go pobierze.
   Najprościej: pobierz gotowy plik z https://github.com/karoljurmanowicz/pilotdesk/releases/latest
   (GitHub buduje go automatycznie po każdej zmianie w repozytorium).
2. **Na każdym komputerze** kliknij dwukrotnie `PilotDesk.exe` i wybierz **Zainstaluj**. Dostaniesz
   skrót na pulpicie, wpis w menu Start, start razem z Windows i wpis w Ustawienia → Aplikacje.
   Nie są potrzebne uprawnienia administratora.
3. **Na komputerze, którym chcesz sterować**, otwórz **Dostęp**, ustaw hasło i włącz zdalny dostęp.

> Windows może pokazać „System Windows ochronił ten komputer”, bo plik nie ma płatnego podpisu
> cyfrowego. Wybierz **Więcej informacji → Uruchom mimo to**.

## Funkcje

| | |
|---|---|
| **Sterowanie** | mysz, klawiatura, polskie znaki, wiele monitorów, pełny ekran, tryb tylko podglądu |
| **Karty** | kilka połączeń w jednym oknie; `+` otwiera nowe połączenie |
| **Wideo H.264** | ok. 5–30 razy mniej danych niż JPEG, płynniej na słabym łączu (w razie potrzeby sam wraca do JPEG) |
| **Dźwięk** | dźwięk z komputera zdalnego (kodek Opus), włączany ikoną głośnika |
| **Schowek** | Ctrl+C / Ctrl+V dla **tekstu i plików**: kopiujesz plik w Eksploratorze, wklejasz na drugim komputerze |
| **Pliki** | dwupanelowy menedżer plików, foldery, postęp przesyłania |
| **Tryb prywatności** | ekran komputera zdalnego robi się czarny dla osób przy nim; Ty nadal widzisz obraz |
| **Zdalny restart** | „⋯” → Uruchom ponownie; PilotDesk sam połączy się ponownie, gdy komputer wróci |
| **Automatyczne ponowne łączenie** | po zerwaniu połączenia (do 90 s) i po restarcie (do 10 min) |
| **Wake-on-LAN** | Komputery → „⋯” → Obudź; sygnał idzie też przez inne połączone komputery |
| **Bez hasła** | komputer zdalny pokazuje **Akceptuj / Odrzuć** z 6-cyfrowym kodem; „Zapamiętaj ten komputer” = następnym razem bez pytania |
| **Wspólna mysz i klawiatura** | kursor przechodzi na komputer obok przez krawędź ekranu, wizualny układ ekranów, wł./wył. |
| **Łączenie po ID bez serwera** | komputery same znajdują się w sieci lokalnej i Tailscale |
| **Usługa systemowa** | dostęp do ekranu logowania, okien UAC i Ctrl+Alt+Del, także po restarcie |
| **Aktualizacje** | automatyczne, z GitHub Releases albo z Twojego pliku JSON |
| **Bezpieczeństwo** | X25519 + AES-256-GCM (nowe klucze w każdej sesji), hasło nigdy nie idzie przez sieć, blokada po błędnych próbach |

## Łączenie z drugim komputerem (najprościej)

1. Na drugim komputerze włącz **Zdalny dostęp**.
2. Na tym komputerze w zakładce **Połącz** pojawi się on na liście **„W Twojej sieci”**. Kliknij **Połącz**.
   Możesz też wpisać jego ID.
3. Na drugim komputerze kliknij **Akceptuj**. Zaznacz **„Zapamiętaj ten komputer”**, a następnym razem
   połączy się bez pytania.

Wyszukiwanie po ID działa bez żadnego serwera: w sieci lokalnej i w Tailscale (jeśli go masz).
Listę zapamiętanych komputerów wyczyścisz w zakładce **Dostęp**.

## Wspólna mysz i klawiatura (komputer obok)

Zakładka **Mysz i klawiatura**:
1. Wybierz **Komputer obok** i włącz przełącznik. Możesz to zrobić także z ikony przy zegarze.
2. W polu **Układ ekranów** przeciągnij ekran drugiego komputera tam, gdzie naprawdę stoi (po prawej,
   po lewej, nad albo pod). Zielona linia pokazuje krawędź, przez którą przechodzi kursor.
3. Przesuń kursor za tę krawędź: mysz i klawiatura sterują teraz drugim komputerem.
4. **Ctrl+C / Ctrl+V** działa między komputerami dla tekstu i plików.

**Powrót:** przesuń kursor z powrotem przez krawędź albo naciśnij **Ctrl+Alt+Esc**. Wyłącz przełącznik,
gdy nie potrzebujesz tej funkcji (po starcie programu jest zawsze wyłączona).

W opcjach wybierzesz też „Przejście przez krawędź: od razu / po chwili” (chroni przed przypadkowym
przeskokiem) oraz monitor drugiego komputera.

## Łączenie przez internet

* **W tej samej sieci:** wpisz adres IP (widać go w programie).
* **Po ID, jak w AnyDesk:** na dowolnym serwerze z publicznym IP uruchom
  `python3 pd_relay.py --port 47900 --key KLUCZ` (wystarczy sam Python, bez bibliotek). Potem w
  **Ustawienia → Sieć** każdego komputera wpisz adres serwera i klucz.
* **Inne sposoby:** Tailscale lub ZeroTier (wpisujesz adres 100.x.x.x) albo przekierowanie portu TCP 47800
  na routerze.

## Usługa systemowa (ekran logowania i UAC)

**Dostęp → Usługa systemowa → Zainstaluj**. Windows poprosi o zgodę administratora.

Od tej chwili:
* PilotDesk działa jako usługa Windows i uruchamia agenta w aktywnej sesji,
* agent przełącza się na ekran logowania i okna UAC, kiedy się pojawią,
* okno programu pokazuje listę sesji, czat i prośby o akceptację.

Usługa sama się aktualizuje, jeśli ustawisz źródło aktualizacji.

## Wake-on-LAN

Na budzonym komputerze Wake-on-LAN musi być włączony w BIOS/UEFI i w ustawieniach karty sieciowej
(Menedżer urządzeń → karta → Zarządzanie energią). Pakiet działa tylko w sieci lokalnej, dlatego
PilotDesk wysyła go też przez inne komputery, z którymi masz połączenie (np. przez stale włączony
komputer w domu).

## Automatyczne aktualizacje

1. Podnieś `VERSION` w `pd_common.py` (np. na `"3.1"`) i wyślij zmianę na gałąź `main`. GitHub sam
   zbuduje `PilotDesk.exe` i opublikuje wydanie `v3.1` w zakładce Releases (razem z sumą kontrolną).
2. Domyślnym źródłem jest repozytorium `karoljurmanowicz/pilotdesk` (można je zmienić w **Ustawienia → Aktualizacje**).

Program sprawdza aktualizacje przy starcie i co 12 godzin. Nową wersję instaluje, gdy nie trwa żadna
sesja, i sprawdza sumę kontrolną SHA-256. Zamiast GitHuba możesz podać adres pliku JSON:
`{"version": "3.1", "url": "https://…/PilotDesk.exe", "sha256": "…"}`.

## Ograniczenia

* Linux wymaga sesji X11 (nie Wayland) i programu `xclip`. macOS wymaga uprawnień „Nagrywanie ekranu”
  i „Dostępność”.
* Tryb prywatności wymaga Windows 10 2004 lub nowszego. Lokalną mysz i klawiaturę blokuje tylko w trybie
  usługi, bo wtedy ma uprawnienia administratora.
* Schowek przesyła pliki od razu po skopiowaniu (do 4 GB). Większe przesyłaj menedżerem plików.
* Wszystkie komputery muszą mieć PilotDesk 3.x.
* Wspólna mysz: w Windows nie da się przejąć ekranu Ctrl+Alt+Del i okien UAC drugiego komputera bez usługi systemowej.

## Pliki projektu

| Plik | Do czego |
|---|---|
| `pilotdesk.py` | okno główne, instalator, polecenia |
| `pd_viewer.py` | karty, sesja, czat, pliki |
| `pd_host.py` | udostępnianie |
| `pd_media.py` | H.264 i dźwięk |
| `pd_clipfiles.py` | pliki w schowku |
| `pd_winutil.py` | prywatność, restart, ekran logowania |
| `pd_service.py` | usługa Windows |
| `pd_update.py` | aktualizacje |
| `pd_common.py` | protokół i szyfrowanie |
| `pd_ui.py`, `pd_theme.py` | wygląd, logo, ikony |
| `pd_relay.py` | serwer pośredniczący |
| `pd_kvm.py` | wspólna mysz i klawiatura |
| `pd_discovery.py` | wyszukiwanie komputerów po ID |
| `fonts/` | czcionka Geist (licencja SIL Open Font License) |
