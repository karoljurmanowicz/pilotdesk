# Co nowego w PilotDesk

## 3.8
- Zamiast ogólnego „Połączenie zostało zamknięte” PilotDesk pokazuje prawdziwy powód, dla którego komputer zdalny odmówił połączenia (np. blokada po zbyt wielu nieudanych próbach logowania – z czasem do odblokowania – albo błąd po tamtej stronie).
- Dziennik zdarzeń zapisuje każde połączenie przychodzące i jego błędy.

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
