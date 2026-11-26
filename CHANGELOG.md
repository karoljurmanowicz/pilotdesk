# Co nowego w PilotDesk

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
