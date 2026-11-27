# Co nowego w PilotDesk

## 3.11
- Lepsza jakość obrazu: nowy domyślny tryb „Najlepsza jakość (ostry tekst)” – pełna informacja o kolorze (4:4:4) i stała jakość obrazu zamiast niskiej przepływności; limit dopasowany do rozdzielczości.
- Ostrzejsze powiększanie na dużych monitorach (np. obraz 1080p na monitorze 4K): powiększenie 2× bez rozmycia, lepsze filtry przy innych skalach.
- Nowe menu „Skala obrazu” w oknie sesji: Dopasuj do okna, Ostre piksele, 100%, 150%, 200%.
- Zmiana rozdzielczości komputera zdalnego (Windows) z menu „Skala obrazu” – po rozłączeniu wraca oryginalna.
- Naprawione: pliki skopiowane Ctrl+C na jednym komputerze nie dawały się wkleić Ctrl+V na drugim (Windows odrzucał je ze schowka). Kopiowanie tekstu i plików sprawdzone automatycznie w obie strony, także w trybie usługi.
- Nowy menedżer plików w stylu Eksploratora Windows: drzewo folderów („Ten komputer”, Pulpit, Dokumenty, Pobrane, dyski), kolumny Nazwa / Data modyfikacji / Typ / Rozmiar, sortowanie, menu pod prawym przyciskiem, skróty F2, F5, Delete, Backspace.
- Przeciąganie plików (drag & drop): między panelami menedżera plików, z Eksploratora Windows na panel komputera zdalnego, a także bezpośrednio na okno sesji – pliki trafiają wtedy na pulpit komputera zdalnego.
- W trybie usługi Pulpit i Pobrane wskazują foldery zalogowanego użytkownika (wcześniej folder systemowy).

## 3.10
- Okienko „Sesja zdalna aktywna” na sterowanym komputerze można zminimalizować (przycisk „–”) do małej karteczki „● Zdalnie” w rogu ekranu. Kliknięcie karteczki rozwija okienko, można ją też przeciągnąć. PilotDesk zapamiętuje wybór na kolejne sesje.

## 3.9
- Naprawione: okno PilotDesk zawieszało się na stałe (najczęściej podczas wyszukiwania komputerów w sieci). Przyczyną było sprzątanie pamięci uruchamiane w wątku pobocznym – teraz odbywa się wyłącznie w wątku okna.
- Naprawione: po ponownej instalacji lub aktualizacji usługi systemowej stary proces usługi działał dalej i odrzucał wszystkie połączenia („Połączenie zostało zamknięte”). Usługa zamyka teraz swoje stare procesy przy starcie, instalacji, aktualizacji i odinstalowaniu, a przestarzały proces sam się wyłącza.
- Naprawione: zamykanie programu (i odinstalowanie usługi) zawieszało się w trybie usługi.
- Naprawione: polskie znaki w komunikatach Windows psuły odczyt stanu usługi.

## 3.8
- Naprawione: gdy PilotDesk się zawiesił, ponowne uruchomienie nic nie dawało (trzeba było odinstalować program). Teraz nowe uruchomienie wykrywa zawieszoną kopię, zamyka ją i startuje od nowa. Aktualizacja i odinstalowanie też radzą sobie z zawieszoną kopią.
- Naprawione: okno zamierało na czas instalowania/odinstalowywania usługi systemowej i „Napraw zaporę” – teraz dzieje się to w tle.
- Naprawione: po nieudanej instalacji albo niepełnym odinstalowaniu usługi program mógł przestać przyjmować połączenia. Tryb usługi włącza się tylko wtedy, gdy usługa naprawdę jest zainstalowana.
- Okno pokazuje wyraźnie, gdy usługa systemowa nie odpowiada (zamiast „Gotowy”), i od razu aktualizuje starszą usługę.
- Zamiast ogólnego „Połączenie zostało zamknięte” PilotDesk pokazuje prawdziwy powód odmowy (np. blokada po zbyt wielu nieudanych próbach – z czasem do odblokowania).
- Naprawione: obraz mógł zamarznąć na stałe po zgubieniu potwierdzenia klatki.
- Nowe: przycisk „Sprawdź połączenie” – sprawdza krok po kroku, czy drugi komputer jest widoczny, czy port jest otwarty i co odpowiada PilotDesk po drugiej stronie.
- Nowe: „Zapisz raport” (Ustawienia → Dziennik zdarzeń) – jeden plik na pulpicie z dziennikami programu i usługi oraz opisem systemu, bez haseł.
- Program automatycznie testowany na Windows także w zwykłym trybie (połączenie bez hasła z akceptacją, drugie uruchomienie, zawieszenia okna).

## 3.7
- Naprawione: po włączeniu usługi systemowej nie można było połączyć się z komputerem – zapora Windows blokowała usługę (działa ona z osobnej kopii programu, której nie obejmowała dotychczasowa reguła). Usługa sama dodaje teraz regułę zapory, także na komputerach, na których została zainstalowana wcześniej.
- Zapamiętane komputery („Zapamiętaj ten komputer”) działają także w trybie usługi.
- Dziennik usługi: %PROGRAMDATA%\PilotDesk\logs.
- Usługa jest teraz automatycznie testowana na prawdziwym Windows (instalacja, połączenie, obraz, kliknięcia, wyszukiwanie po ID).

## 3.6
- Naprawione: kliknięcia nie działały w oknie sesji, gdy na sterowanym komputerze była włączona „Wspólna mysz” – zdalny ruch kursora do krawędzi ekranu przełączał mysz na drugi komputer i od tej chwili wszystkie kliknięcia były połykane.
- Mysz w Windows sterowana bezpośrednio (SendInput): kliknięcie trafia dokładnie w miejsce kursora, a gdy Windows je odrzuci (ekran blokady, okno UAC, program uruchomiony jako administrator), PilotDesk pokazuje komunikat z rozwiązaniem.
- Wykrywanie okna administratora sprawdza okno pod kursorem (tam trafia kliknięcie), a nie tylko okno na pierwszym planie.
- Dziennik zdarzeń zapisuje pierwsze kliknięcia sesji (po obu stronach), tryb DPI i układ monitorów – łatwiej znaleźć przyczynę, gdyby problem wrócił.

## 3.5
- Naprawione: sterowanie myszą i klawiaturą mogło przestać działać, gdy przesyłanie obrazu się zatykało – obsługa myszy nie czeka już na sieć.
- Naprawione: „Rozłącz” działa od razu, nawet gdy połączenie jest zablokowane.
- Naprawione: okno mogło się zawieszać na komputerach z problematycznym DNS (np. druga karta sieciowa do drukarki).
- Gdy okno na komputerze zdalnym działa jako administrator (np. oprogramowanie drukarki), PilotDesk mówi wprost, że Windows blokuje jego sterowanie, i podpowiada rozwiązanie (usługa systemowa).
- Dziennik zdarzeń z wykrywaniem zawieszeń: Ustawienia → Dziennik zdarzeń → Otwórz.

## 3.4
- Naprawione sprawdzanie i pobieranie aktualizacji na komputerach, na których program błędnie zgłaszał brak internetu (np. z drugą kartą sieciową do drukarki): systemowa weryfikacja certyfikatów Windows, zapasowy DNS i obsługa proxy.
- Komunikat podaje prawdziwą przyczynę błędu, a przycisk „Diagnostyka” w zakładce Aktualizacje sprawdza DNS, proxy i certyfikat.

## 3.3
- Naprawione łączenie z komputerem widocznym na liście „W Twojej sieci”, gdy jego zapora blokuje połączenia przychodzące – PilotDesk prosi wtedy o połączenie zwrotne.
- Gdy port 47800 jest zajęty lub zarezerwowany przez Windows (Hyper-V, WSL, Docker), program sam wybiera inny.
- Dokładniejsze komunikaty o błędach połączenia.
- Przycisk „Napraw zaporę” w zakładce Dostęp.

## 3.2
- Nowa zakładka **Aktualizacje**: sprawdzanie i instalowanie nowych wersji jednym kliknięciem, z paskiem postępu i listą zmian.
- „Sprawdź aktualizacje” także w menu ikony przy zegarze.
- Gdy pojawi się nowa wersja, w menu bocznym widać kropkę przy „Aktualizacje”.

## 3.1
- Wspólna mysz i klawiatura: kursor przechodzi na komputer obok przez krawędź ekranu, z wizualnym układem ekranów i przełącznikiem wł./wył.
- Łączenie po ID bez serwera: komputery same znajdują się w sieci lokalnej i w Tailscale (lista „W Twojej sieci”).
- „Zapamiętaj ten komputer” przy akceptacji połączenia – kolejne połączenia bez pytania.

## 3.0
- Nowy wygląd, karty z wieloma połączeniami, wideo H.264, dźwięk, schowek z plikami, tryb prywatności, zdalny restart, Wake-on-LAN, usługa systemowa (ekran logowania i UAC), automatyczne aktualizacje.
