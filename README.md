# SpeakVault

SpeakVault to uniwersalne narzędzie do zaawansowanego generowania mowy z tekstu (TTS) i wsadowej obróbki plików audio.

---

## ▶️ 1. Generator mowy z tekstu (TTS)

Obsługiwane formaty wejściowe:
- TXT, CSV, SRT (napisy filmowe)
- Automatyczne rozpoznawanie formatu i wyciąganie tekstów do syntezy

Silniki mowy:
- Edge TTS
- Azure Cognitive Services (API)
- Google Cloud Text-to-Speech (API)
- Google Gemini TTS (API)
- gTTS (Google)
- Windows TTS (offline, głosy systemowe)
- ElevenLabs (API, AI głosy)
- Piper TTS (open source, offline)

Parametry mowy:
- Tempo, ton, głośność
- Dodatkowy „prompt” stylu/brzmienia
- Opcjonalny tryb prostego tekstu (bez znaczników)

Szybki odsłuch:
- Przycisk „Testuj TTS” – sprawdź frazę testową w sekundę

Eksport audio:
- .ogg, .mp3, .wav
- Działa od razu dzięki wbudowanemu konwerterowi audio (ffmpeg) – nic nie trzeba doinstalowywać

Scalanie lub rozdzielanie:
- Jeden duży plik audio lub osobne pliki dla każdej linii/zdania

---

## ▶️ 2. Obsługa napisów SRT (tryb filmowy / lektorski)

Synchronizacja audio z czasami napisów:
- Podkładanie lektora pod film dzięki automatycznemu dopasowaniu do SRT

Tryby:
- Scalanie całego SRT w jeden plik audio
- Generowanie osobnych plików dla każdego wpisu SRT
- Opcjonalna cisza (1 sekunda) po każdej kwestii

---

## ▶️ 3. Wsadowa obróbka plików audio (Batch Tools)

Funkcje batch:
- Dodawanie wielu plików/folderów na raz
- Zmiana tempa, tonu, głośności dla wielu plików jednocześnie
- Usuwanie ciszy z nagrań
- Konwersja formatów (.ogg, .mp3, .wav)
- Przycinanie nagrań (ustaw start i koniec)

---

## ▶️ 4. Odtwarzanie audio w programie

- Podgląd ostatniego wygenerowanego pliku
- Odtwarzanie wybranego pliku z listy batch

---

## ▶️ 5. Zarządzanie ustawieniami

Profile ustawień:
- Zapis/odczyt konfiguracji do pliku JSON
- Szybka zmiana wszystkich opcji jednym kliknięciem
- Przenoszenie ustawień między komputerami
- Zgodność wstecz: starsze profile dalej działają (brakujące opcje uzupełniamy domyślnie)

---

## ▶️ 6. Dziennik zdarzeń i logi

- Pełna historia operacji (generowanie, błędy, zapis, odczyt)
- Łatwe debugowanie i analiza procesów

---

## ▶️ 7. Nowoczesny interfejs

- Ciemny motyw, podział na zakładki (TTS, Batch, Logi)
- Filtr silników: Wszystkie / Darmowe / Płatne
- Intuicyjna obsługa – bez potrzeby znajomości kodu

---

## ▶️ 8. Praktyczne zastosowania

- Tworzenie lektora do filmów, seriali, kursów online (SRT)
- Nagrywanie audiobooków (scalanie, tempo, ton)
- Generowanie audio do quizów, gier, aplikacji edukacyjnych
- Obróbka własnych nagrań (usuwanie ciszy, normalizacja)
- Szybki odsłuch efektów pracy
- Praca offline/online + wsparcie dla AI silników (np. ElevenLabs)

---

## 🖥️ Uruchamianie

- Windows: pobierz plik .exe i uruchom.
- Aplikacja jest kompilowana do jednego pliku wykonywalnego (Nuitka) i zawiera wszystkie potrzebne biblioteki. Może ważyć trochę więcej, ale dzięki temu działa „od strzału” – bez dodatkowych instalacji i problemów z zależnościami.

---

## 📬 Wsparcie

Masz pytania, pomysły na nowe funkcje lub potrzebujesz pomocy?
➡️ discord: https://discord.gg/ht9dfanaRE  
🎥 Możemy też zrobić prezentację na żywo lub pomóc w konfiguracji.

🙏 Dzięki za uwagę i miłego korzystania z SpeakVault! 🎙️🔊✍️
