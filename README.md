# PilotDesk 3.0

Zdalny pulpit do Twoich komputerów: bez limitów, bez konta, z szyfrowaniem end-to-end.
Program to jeden plik **PilotDesk.exe**, który przy pierwszym uruchomieniu sam się instaluje.

## Instalacja (Windows)

1. **Zbuduj PilotDesk.exe (jeden raz).** Kliknij dwukrotnie `ZBUDUJ_PILOTDESK_EXE.bat`. Jeśli nie masz
   Pythona, skrypt sam go pobierze.
   Możesz też zlecić to GitHubowi: wrzuć ten folder do repozytorium, a `.github/workflows/build.yml`
   zbuduje plik automatycznie (Actions → Artifacts; po tagu `v3.0` także w zakładce Releases).
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
| **Bez hasła** | komputer zdalny pokazuje **Akceptuj / Odrzuć** z 6-cyfrowym kodem do porównania |
| **Usługa systemowa** | dostęp do ekranu logowania, okien UAC i Ctrl+Alt+Del, także po restarcie |
| **Aktualizacje** | automatyczne, z GitHub Releases albo z Twojego pliku JSON |
| **Bezpieczeństwo** | X25519 + AES-256-GCM (nowe klucze w każdej sesji), hasło nigdy nie idzie przez sieć, blokada po błędnych próbach |

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

1. Opublikuj nową wersję jako GitHub Release. Po wypchnięciu taga `v3.1` workflow sam dołączy
   `PilotDesk.exe` i `PilotDesk.exe.sha256`.
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
* Wszystkie komputery muszą mieć PilotDesk 3.x (protokół się zmienił).

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
| `fonts/` | czcionka Geist (licencja SIL Open Font License) |
